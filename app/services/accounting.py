# ============================================================================
# Decompiled from qbw32.exe!CQBJournalEngine::PostTransaction()
# Offset: 0x00128400
# This is the heart of the double-entry system. Every financial event
# (invoice, payment, bank transaction) creates a balanced journal entry
# through this service. The original validated sum(debits) == sum(credits)
# with a tolerance of 0.004 (BCD rounding). We use exact Decimal math.
# ============================================================================

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.transactions import Transaction, TransactionLine
from app.models.accounts import Account

# ---------------------------------------------------------------------------
# Account number constants — replaces hardcoded magic numbers across codebase
# ---------------------------------------------------------------------------
AR_ACCOUNT_NUMBER = "1100"       # Accounts Receivable
UNDEPOSITED_FUNDS_NUMBER = "1200"  # Undeposited Funds
AP_ACCOUNT_NUMBER = "2000"       # Accounts Payable
SALES_TAX_NUMBER = "2200"        # Sales Tax Payable
DEFAULT_INCOME_NUMBER = "4000"   # Service Income
LATE_FEE_INCOME_NUMBER = "4800"  # Late Fee Income
DEFAULT_EXPENSE_NUMBER = "6000"  # Miscellaneous Expense
CHECKING_ACCOUNT_NUMBER = "1000" # Checking Account
CC_PAYABLE_NUMBER = "2100"       # Credit Card Payable
GST_COLLECTED_NUMBER = "2210"    # GST Collected (liability)
GST_PAYABLE_NUMBER = "2220"      # GST Payable (liability)
GST_INPUT_CREDITS_NUMBER = "1800"  # GST Input Tax Credits (asset)


def create_journal_entry(
    db: Session,
    txn_date: date,
    description: str,
    lines: list[dict],
    source_type: str = None,
    source_id: int = None,
    reference: str = None,
) -> Transaction:
    """Create a balanced journal entry.

    lines: [{"account_id": int, "debit": Decimal, "credit": Decimal}, ...]
    Each line must have debit > 0 OR credit > 0, not both.
    Total debits must equal total credits.
    """
    # Validate individual lines before summing
    for i, l in enumerate(lines):
        debit = Decimal(str(l.get("debit", 0)))
        credit = Decimal(str(l.get("credit", 0)))
        if debit < 0 or credit < 0:
            raise ValueError(f"Line {i+1}: debit and credit must be non-negative")
        if debit > 0 and credit > 0:
            raise ValueError(f"Line {i+1}: a line cannot have both debit and credit")

    total_debit = sum(Decimal(str(l.get("debit", 0))) for l in lines)
    total_credit = sum(Decimal(str(l.get("credit", 0))) for l in lines)

    if total_debit != total_credit:
        raise ValueError(f"Journal entry not balanced: debits={total_debit}, credits={total_credit}")

    txn = Transaction(
        date=txn_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
        reference=reference,
    )
    db.add(txn)
    db.flush()

    for line_data in lines:
        debit = Decimal(str(line_data.get("debit", 0)))
        credit = Decimal(str(line_data.get("credit", 0)))
        if debit == 0 and credit == 0:
            continue

        txn_line = TransactionLine(
            transaction_id=txn.id,
            account_id=line_data["account_id"],
            debit=debit,
            credit=credit,
            description=line_data.get("description", ""),
        )
        db.add(txn_line)

        # Update account balance
        account = db.query(Account).filter(Account.id == line_data["account_id"]).first()
        if account:
            if account.account_type.value in ("asset", "expense", "cogs"):
                account.balance += debit - credit
            else:
                account.balance += credit - debit

    return txn


def _get_account_id(db: Session, account_number: str) -> int | None:
    """Get account ID by account number."""
    acct = db.query(Account).filter(Account.account_number == account_number).first()
    return acct.id if acct else None


def get_ar_account_id(db: Session) -> int | None:
    return _get_account_id(db, AR_ACCOUNT_NUMBER)


def get_default_income_account_id(db: Session) -> int | None:
    return _get_account_id(db, DEFAULT_INCOME_NUMBER)


def get_sales_tax_account_id(db: Session) -> int | None:
    return _get_account_id(db, SALES_TAX_NUMBER)


def get_undeposited_funds_id(db: Session) -> int | None:
    return _get_account_id(db, UNDEPOSITED_FUNDS_NUMBER)


def get_ap_account_id(db: Session) -> int | None:
    return _get_account_id(db, AP_ACCOUNT_NUMBER)


def get_late_fee_account_id(db: Session) -> int | None:
    return _get_account_id(db, LATE_FEE_INCOME_NUMBER)


def get_expense_account_id(db: Session) -> int | None:
    return _get_account_id(db, DEFAULT_EXPENSE_NUMBER)


def get_cc_payable_account_id(db: Session) -> int | None:
    return _get_account_id(db, CC_PAYABLE_NUMBER)


def get_checking_account_id(db: Session) -> int | None:
    return _get_account_id(db, CHECKING_ACCOUNT_NUMBER)


def get_gst_collected_account_id(db: Session) -> int | None:
    return _get_account_id(db, GST_COLLECTED_NUMBER)


def get_gst_input_credits_account_id(db: Session) -> int | None:
    return _get_account_id(db, GST_INPUT_CREDITS_NUMBER)


def get_accounting_basis(db: Session) -> str:
    """Return 'cash' or 'accrual' from settings. Uses DEFAULT_SETTINGS fallback."""
    from app.models.settings import Settings, DEFAULT_SETTINGS
    row = db.query(Settings).filter(Settings.key == "accounting_basis").first()
    if row and row.value in ("cash", "accrual"):
        return row.value
    return DEFAULT_SETTINGS.get("accounting_basis", "accrual")
