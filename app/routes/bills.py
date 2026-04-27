# ============================================================================
# Bills (Accounts Payable) — enter bills from vendors, track payables
# Feature 1: DR Expense, CR AP (2000) on create; DR AP, CR Bank on payment
# ============================================================================

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import get_current_user
from app.models.bills import Bill, BillLine, BillStatus
from app.models.users import User
from app.models.contacts import Vendor
from app.models.items import Item
from app.models.accounts import Account
from app.schemas.bills import BillCreate, BillUpdate, BillResponse
from app.services.accounting import (
    create_journal_entry, get_ap_account_id, get_accounting_basis,
    get_expense_account_id, get_sales_tax_account_id,
)
from app.services.closing_date import check_closing_date

router = APIRouter(prefix="/api/bills", tags=["bills"])


@router.get("", response_model=list[BillResponse])
def list_bills(vendor_id: int = None, status: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Bill).options(joinedload(Bill.vendor))
    if vendor_id:
        q = q.filter(Bill.vendor_id == vendor_id)
    if status:
        q = q.filter(Bill.status == status)
    bills = q.order_by(Bill.date.desc()).all()
    results = []
    for b in bills:
        resp = BillResponse.model_validate(b)
        if b.vendor:
            resp.vendor_name = b.vendor.name
        results.append(resp)
    return results


@router.get("/{bill_id}", response_model=BillResponse)
def get_bill(bill_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    resp = BillResponse.model_validate(bill)
    if bill.vendor:
        resp.vendor_name = bill.vendor.name
    return resp


@router.post("", response_model=BillResponse, status_code=201)
def create_bill(data: BillCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    check_closing_date(db, data.date)

    vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    due_date = data.due_date
    if not due_date and data.terms:
        try:
            days = int(data.terms.lower().replace("net ", ""))
            due_date = data.date + timedelta(days=days)
        except ValueError:
            due_date = data.date + timedelta(days=30)

    subtotal = sum(Decimal(str(l.quantity)) * Decimal(str(l.rate)) for l in data.lines)
    tax_amount = subtotal * Decimal(str(data.tax_rate))
    total = subtotal + tax_amount

    bill = Bill(
        bill_number=data.bill_number, vendor_id=data.vendor_id, date=data.date,
        due_date=due_date, terms=data.terms, ref_number=data.ref_number, po_id=data.po_id,
        subtotal=subtotal, tax_rate=data.tax_rate, tax_amount=tax_amount,
        total=total, balance_due=total, notes=data.notes,
    )
    db.add(bill)
    db.flush()

    # Default expense account for lines without explicit account
    default_expense_id = get_expense_account_id(db)

    basis = get_accounting_basis(db)
    journal_lines = []
    for i, line_data in enumerate(data.lines):
        amt = Decimal(str(line_data.quantity)) * Decimal(str(line_data.rate))
        expense_acct = line_data.account_id
        if not expense_acct and line_data.item_id:
            item = db.query(Item).filter(Item.id == line_data.item_id).first()
            if item and item.expense_account_id:
                expense_acct = item.expense_account_id
        if not expense_acct and vendor.default_expense_account_id:
            expense_acct = vendor.default_expense_account_id
        if not expense_acct:
            expense_acct = default_expense_id

        db.add(BillLine(
            bill_id=bill.id, item_id=line_data.item_id, account_id=expense_acct,
            description=line_data.description, quantity=line_data.quantity,
            rate=line_data.rate, amount=amt, line_order=line_data.line_order or i,
        ))

        # Accrual basis: recognise expense now; Cash basis: defer to payment
        if basis == "accrual" and amt > 0 and expense_acct:
            journal_lines.append({
                "account_id": expense_acct,
                "debit": amt, "credit": Decimal("0"),
                "description": line_data.description or "",
            })

    # Tax line (accrual only)
    if basis == "accrual" and tax_amount > 0:
        tax_acct_id = get_sales_tax_account_id(db)
        if tax_acct_id:
            journal_lines.append({
                "account_id": tax_acct_id,
                "debit": tax_amount, "credit": Decimal("0"),
                "description": "Sales tax on bill",
            })

    # Credit AP (accrual only)
    if basis == "accrual":
        ap_id = get_ap_account_id(db)
        if ap_id and journal_lines:
            journal_lines.append({
                "account_id": ap_id,
                "debit": Decimal("0"), "credit": total,
                "description": f"Bill {data.bill_number} - {vendor.name}",
            })
            txn = create_journal_entry(
                db, data.date, f"Bill {data.bill_number} - {vendor.name}",
                journal_lines, source_type="bill", source_id=bill.id,
            )
            bill.transaction_id = txn.id
    # Cash basis: no journal entry on bill creation

    db.commit()
    db.refresh(bill)
    resp = BillResponse.model_validate(bill)
    resp.vendor_name = vendor.name
    return resp


@router.post("/{bill_id}/void", response_model=BillResponse)
def void_bill(bill_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.status == BillStatus.VOID:
        raise HTTPException(status_code=400, detail="Bill already voided")

    if bill.transaction_id:
        from app.models.transactions import TransactionLine
        original_lines = db.query(TransactionLine).filter(
            TransactionLine.transaction_id == bill.transaction_id
        ).all()
        reverse_lines = [
            {"account_id": ol.account_id, "debit": ol.credit, "credit": ol.debit,
             "description": f"VOID: {ol.description or ''}"}
            for ol in original_lines
        ]
        if reverse_lines:
            create_journal_entry(db, bill.date, f"VOID Bill {bill.bill_number}",
                                 reverse_lines, source_type="bill_void", source_id=bill.id)

    bill.status = BillStatus.VOID
    bill.balance_due = Decimal("0")
    db.commit()
    db.refresh(bill)
    resp = BillResponse.model_validate(bill)
    if bill.vendor:
        resp.vendor_name = bill.vendor.name
    return resp
