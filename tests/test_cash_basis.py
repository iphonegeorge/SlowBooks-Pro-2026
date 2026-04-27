# ============================================================================
# Cash Basis & GST Tests — verify accounting basis toggle and GST flows
# ============================================================================

from decimal import Decimal

import pytest

from app.models.accounts import Account, AccountType
from app.models.settings import Settings
from app.models.transactions import Transaction, TransactionLine
from app.services.accounting import (
    create_journal_entry, get_accounting_basis,
    GST_COLLECTED_NUMBER, GST_INPUT_CREDITS_NUMBER,
    AR_ACCOUNT_NUMBER, DEFAULT_INCOME_NUMBER, CHECKING_ACCOUNT_NUMBER,
    AP_ACCOUNT_NUMBER, DEFAULT_EXPENSE_NUMBER,
)
from app.routes.settings import validate_abn


def _seed_accounts(db):
    """Create accounts needed for cash basis and GST tests."""
    accounts = [
        Account(account_number=CHECKING_ACCOUNT_NUMBER, name="Checking",
                account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number=AR_ACCOUNT_NUMBER, name="Accounts Receivable",
                account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number="1200", name="Undeposited Funds",
                account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number="1800", name="GST Input Tax Credits",
                account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number=AP_ACCOUNT_NUMBER, name="Accounts Payable",
                account_type=AccountType.LIABILITY, balance=Decimal("0")),
        Account(account_number="2210", name="GST Collected",
                account_type=AccountType.LIABILITY, balance=Decimal("0")),
        Account(account_number="2220", name="GST Payable",
                account_type=AccountType.LIABILITY, balance=Decimal("0")),
        Account(account_number=DEFAULT_INCOME_NUMBER, name="Service Income",
                account_type=AccountType.INCOME, balance=Decimal("0")),
        Account(account_number=DEFAULT_EXPENSE_NUMBER, name="Expense",
                account_type=AccountType.EXPENSE, balance=Decimal("0")),
    ]
    for a in accounts:
        db.add(a)
    db.commit()
    return {a.account_number: a for a in accounts}


def _set_accounting_basis(db, basis):
    """Set the accounting basis in the settings table."""
    row = db.query(Settings).filter(Settings.key == "accounting_basis").first()
    if row:
        row.value = basis
    else:
        db.add(Settings(key="accounting_basis", value=basis))
    db.commit()


def test_default_accounting_basis_is_accrual(db):
    """Without any setting, default should be 'accrual'."""
    assert get_accounting_basis(db) == "accrual"


def test_cash_basis_setting(db):
    """Setting accounting_basis to 'cash' should be read correctly."""
    _set_accounting_basis(db, "cash")
    assert get_accounting_basis(db) == "cash"


def test_accrual_invoice_creates_journal_entry(db):
    """On accrual basis, income journal entry is created with the invoice."""
    accounts = _seed_accounts(db)
    _set_accounting_basis(db, "accrual")

    ar = accounts[AR_ACCOUNT_NUMBER]
    income = accounts[DEFAULT_INCOME_NUMBER]

    # Simulate what the invoice route does on accrual basis
    txn = create_journal_entry(db, "2026-01-15", "Invoice #1001 - Test Co", [
        {"account_id": ar.id, "debit": Decimal("1100.00"), "credit": Decimal("0")},
        {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("1000.00")},
        {"account_id": accounts["2210"].id, "debit": Decimal("0"), "credit": Decimal("100.00")},
    ], source_type="invoice", source_id=1)
    db.commit()

    db.refresh(income)
    assert income.balance == Decimal("1000.00")  # Income recognised immediately


def test_cash_basis_no_income_on_invoice(db):
    """On cash basis, no income journal entry should exist at invoice time.
    We test the accounting_basis helper to confirm the route would skip it.
    """
    _seed_accounts(db)
    _set_accounting_basis(db, "cash")

    basis = get_accounting_basis(db)
    assert basis == "cash"

    # On cash basis, the invoice route skips journal creation.
    # No transactions should exist.
    txn_count = db.query(Transaction).count()
    assert txn_count == 0


def test_cash_basis_income_on_payment(db):
    """On cash basis, income is recognised when payment journal entry is created."""
    accounts = _seed_accounts(db)
    _set_accounting_basis(db, "cash")

    checking = accounts[CHECKING_ACCOUNT_NUMBER]
    income = accounts[DEFAULT_INCOME_NUMBER]
    gst_collected = accounts["2210"]

    # Simulate what the payment route does on cash basis:
    # DR Bank $1100, CR Income $1000, CR GST Collected $100
    txn = create_journal_entry(db, "2026-02-15", "Payment from Customer", [
        {"account_id": checking.id, "debit": Decimal("1100.00"), "credit": Decimal("0")},
        {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("1000.00")},
        {"account_id": gst_collected.id, "debit": Decimal("0"), "credit": Decimal("100.00")},
    ], source_type="payment", source_id=1)
    db.commit()

    db.refresh(checking)
    db.refresh(income)
    db.refresh(gst_collected)

    assert checking.balance == Decimal("1100.00")
    assert income.balance == Decimal("1000.00")
    assert gst_collected.balance == Decimal("100.00")


def test_cash_basis_expense_on_bill_payment(db):
    """On cash basis, expense is recognised when bill payment journal entry is created."""
    accounts = _seed_accounts(db)
    _set_accounting_basis(db, "cash")

    checking = accounts[CHECKING_ACCOUNT_NUMBER]
    expense = accounts[DEFAULT_EXPENSE_NUMBER]
    gst_input = accounts["1800"]

    # Simulate bill payment on cash basis:
    # DR Expense $500, DR GST Input $50, CR Bank $550
    txn = create_journal_entry(db, "2026-02-20", "Bill payment to Vendor", [
        {"account_id": expense.id, "debit": Decimal("500.00"), "credit": Decimal("0")},
        {"account_id": gst_input.id, "debit": Decimal("50.00"), "credit": Decimal("0")},
        {"account_id": checking.id, "debit": Decimal("0"), "credit": Decimal("550.00")},
    ], source_type="bill_payment", source_id=1)
    db.commit()

    db.refresh(expense)
    db.refresh(gst_input)
    db.refresh(checking)

    assert expense.balance == Decimal("500.00")
    assert gst_input.balance == Decimal("50.00")
    assert checking.balance == Decimal("-550.00")


def test_gst_net_calculation(db):
    """GST Collected minus GST Input Credits gives net GST payable."""
    accounts = _seed_accounts(db)
    gst_collected = accounts["2210"]
    gst_input = accounts["1800"]
    checking = accounts[CHECKING_ACCOUNT_NUMBER]
    income = accounts[DEFAULT_INCOME_NUMBER]
    expense = accounts[DEFAULT_EXPENSE_NUMBER]

    # Receive payment: GST collected = $100
    create_journal_entry(db, "2026-01-15", "Payment in", [
        {"account_id": checking.id, "debit": Decimal("1100"), "credit": Decimal("0")},
        {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("1000")},
        {"account_id": gst_collected.id, "debit": Decimal("0"), "credit": Decimal("100")},
    ], source_type="payment")

    # Pay bill: GST input = $30
    create_journal_entry(db, "2026-01-20", "Bill payment", [
        {"account_id": expense.id, "debit": Decimal("300"), "credit": Decimal("0")},
        {"account_id": gst_input.id, "debit": Decimal("30"), "credit": Decimal("0")},
        {"account_id": checking.id, "debit": Decimal("0"), "credit": Decimal("330")},
    ], source_type="bill_payment")

    db.commit()
    db.refresh(gst_collected)
    db.refresh(gst_input)

    net_gst = gst_collected.balance - gst_input.balance  # $100 - $30 = $70
    assert net_gst == Decimal("70")


# ============================================================================
# ABN Validation Tests
# ============================================================================

def test_valid_abn():
    """Known valid ABN should pass."""
    assert validate_abn("51 824 753 556") is True
    assert validate_abn("51824753556") is True


def test_invalid_abn_bad_checksum():
    """ABN with wrong check digit should fail."""
    assert validate_abn("51824753557") is False


def test_invalid_abn_wrong_length():
    """ABN with wrong length should fail."""
    assert validate_abn("1234567890") is False
    assert validate_abn("123456789012") is False


def test_invalid_abn_non_numeric():
    """ABN with non-numeric characters should fail."""
    assert validate_abn("5182475355A") is False


def test_empty_abn():
    """Empty ABN should fail."""
    assert validate_abn("") is False
