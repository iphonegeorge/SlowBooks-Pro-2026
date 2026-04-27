# ============================================================================
# Bill Payments — pay bills (AP), DR AP (2000), CR Bank
# Feature 1 continued: Pay Bills workflow
# ============================================================================

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models.bills import Bill, BillStatus, BillPayment, BillPaymentAllocation
from app.models.users import User
from app.models.contacts import Vendor
from app.models.accounts import Account
from app.schemas.bills import BillPaymentCreate, BillPaymentResponse
from app.services.accounting import (
    create_journal_entry, get_ap_account_id, get_accounting_basis,
    get_gst_input_credits_account_id, get_checking_account_id, get_expense_account_id,
)
from app.models.bills import BillLine
from app.models.invoices import GSTClassification
from app.services.closing_date import check_closing_date

router = APIRouter(prefix="/api/bill-payments", tags=["bill_payments"])


@router.get("", response_model=list[BillPaymentResponse])
def list_bill_payments(vendor_id: int = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(BillPayment)
    if vendor_id:
        q = q.filter(BillPayment.vendor_id == vendor_id)
    payments = q.order_by(BillPayment.date.desc()).all()
    results = []
    for p in payments:
        resp = BillPaymentResponse.model_validate(p)
        if p.vendor:
            resp.vendor_name = p.vendor.name
        results.append(resp)
    return results


@router.post("", response_model=BillPaymentResponse, status_code=201)
def create_bill_payment(data: BillPaymentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    check_closing_date(db, data.date)

    vendor = db.query(Vendor).filter(Vendor.id == data.vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    alloc_total = sum(a.amount for a in data.allocations)
    if alloc_total > data.amount:
        raise HTTPException(status_code=400, detail="Allocations exceed payment amount")

    payment = BillPayment(
        vendor_id=data.vendor_id, date=data.date, amount=data.amount,
        method=data.method, check_number=data.check_number,
        pay_from_account_id=data.pay_from_account_id, notes=data.notes,
    )
    db.add(payment)
    db.flush()

    for alloc_data in data.allocations:
        bill = db.query(Bill).filter(Bill.id == alloc_data.bill_id).first()
        if not bill:
            raise HTTPException(status_code=404, detail=f"Bill {alloc_data.bill_id} not found")
        if alloc_data.amount > float(bill.balance_due):
            raise HTTPException(status_code=400, detail=f"Allocation exceeds bill balance")

        db.add(BillPaymentAllocation(
            bill_payment_id=payment.id, bill_id=alloc_data.bill_id,
            amount=alloc_data.amount,
        ))

        bill.amount_paid += Decimal(str(alloc_data.amount))
        bill.balance_due -= Decimal(str(alloc_data.amount))
        if bill.balance_due <= 0:
            bill.status = BillStatus.PAID
        else:
            bill.status = BillStatus.PARTIAL

    # Journal entry depends on accounting basis
    basis = get_accounting_basis(db)
    bank_id = data.pay_from_account_id
    if not bank_id:
        bank_id = get_checking_account_id(db)

    if bank_id:
        journal_lines = []

        if basis == "cash":
            # Cash basis: expense recognised now — DR Expense, DR GST Input, CR Bank
            gst_input_id = get_gst_input_credits_account_id(db)
            total_expense = Decimal("0")
            total_gst_input = Decimal("0")

            for alloc_data in data.allocations:
                bill = db.query(Bill).filter(Bill.id == alloc_data.bill_id).first()
                if not bill or bill.total == 0:
                    continue
                alloc_amount = Decimal(str(alloc_data.amount))
                ratio = alloc_amount / Decimal(str(bill.total))

                bill_lines = db.query(BillLine).filter(BillLine.bill_id == bill.id).all()
                for bl in bill_lines:
                    line_expense = (Decimal(str(bl.amount)) * ratio).quantize(Decimal("0.01"))
                    if line_expense == 0:
                        continue
                    expense_acct = bl.account_id
                    if not expense_acct:
                        expense_acct = get_expense_account_id(db)
                    if expense_acct:
                        journal_lines.append({
                            "account_id": expense_acct,
                            "debit": line_expense, "credit": Decimal("0"),
                            "description": bl.description or f"Bill {bill.bill_number}",
                        })
                        total_expense += line_expense

                    # GST input credits on taxable lines
                    if bl.gst_classification == GSTClassification.TAXABLE and gst_input_id:
                        line_gst = (Decimal(str(bl.gst_amount or 0)) * ratio).quantize(Decimal("0.01"))
                        if line_gst > 0:
                            journal_lines.append({
                                "account_id": gst_input_id,
                                "debit": line_gst, "credit": Decimal("0"),
                                "description": f"GST input - Bill {bill.bill_number}",
                            })
                            total_gst_input += line_gst

            # CR Bank for total
            total_debits = total_expense + total_gst_input
            if total_debits > 0:
                journal_lines.append({
                    "account_id": bank_id,
                    "debit": Decimal("0"), "credit": total_debits,
                    "description": f"Bill payment to {vendor.name}",
                })
        else:
            # Accrual basis: DR AP, CR Bank
            ap_id = get_ap_account_id(db)
            if ap_id:
                journal_lines = [
                    {"account_id": ap_id, "debit": Decimal(str(data.amount)),
                     "credit": Decimal("0"), "description": f"Bill payment to {vendor.name}"},
                    {"account_id": bank_id, "debit": Decimal("0"),
                     "credit": Decimal(str(data.amount)), "description": f"Bill payment to {vendor.name}"},
                ]

        if journal_lines:
            txn = create_journal_entry(
                db, data.date, f"Bill payment to {vendor.name}",
                journal_lines, source_type="bill_payment", source_id=payment.id,
            )
            payment.transaction_id = txn.id

    db.commit()
    db.refresh(payment)
    resp = BillPaymentResponse.model_validate(payment)
    resp.vendor_name = vendor.name
    return resp
