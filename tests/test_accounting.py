# ============================================================================
# Accounting Tests — double-entry bookkeeping, balance updates, Decimal math
# ============================================================================

from decimal import Decimal

import pytest

from app.models.accounts import Account, AccountType
from app.services.accounting import create_journal_entry


def _seed_accounts(db):
    """Create basic accounts for testing."""
    accounts = [
        Account(account_number="1000", name="Checking", account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number="1100", name="Accounts Receivable", account_type=AccountType.ASSET, balance=Decimal("0")),
        Account(account_number="2000", name="Accounts Payable", account_type=AccountType.LIABILITY, balance=Decimal("0")),
        Account(account_number="4000", name="Service Income", account_type=AccountType.INCOME, balance=Decimal("0")),
        Account(account_number="6000", name="Expense", account_type=AccountType.EXPENSE, balance=Decimal("0")),
    ]
    for a in accounts:
        db.add(a)
    db.commit()
    return {a.account_number: a for a in accounts}


def test_balanced_journal_entry(db):
    """Balanced journal entry should succeed."""
    accounts = _seed_accounts(db)
    ar = accounts["1100"]
    income = accounts["4000"]

    txn = create_journal_entry(db, "2026-01-15", "Test invoice", [
        {"account_id": ar.id, "debit": Decimal("1000.00"), "credit": Decimal("0")},
        {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("1000.00")},
    ], source_type="test")
    db.commit()

    assert txn is not None
    assert txn.id is not None


def test_unbalanced_raises(db):
    """Unbalanced journal entry should raise ValueError."""
    accounts = _seed_accounts(db)
    ar = accounts["1100"]
    income = accounts["4000"]

    with pytest.raises(ValueError, match="not balanced"):
        create_journal_entry(db, "2026-01-15", "Bad entry", [
            {"account_id": ar.id, "debit": Decimal("1000.00"), "credit": Decimal("0")},
            {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("500.00")},
        ])


def test_both_debit_and_credit_raises(db):
    """Line with both debit and credit should raise ValueError."""
    accounts = _seed_accounts(db)
    ar = accounts["1100"]

    with pytest.raises(ValueError, match="cannot have both"):
        create_journal_entry(db, "2026-01-15", "Bad line", [
            {"account_id": ar.id, "debit": Decimal("100"), "credit": Decimal("100")},
        ])


def test_asset_balance_increases_on_debit(db):
    """Debiting an asset account should increase its balance."""
    accounts = _seed_accounts(db)
    checking = accounts["1000"]
    income = accounts["4000"]

    create_journal_entry(db, "2026-01-15", "Payment received", [
        {"account_id": checking.id, "debit": Decimal("500.00"), "credit": Decimal("0")},
        {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("500.00")},
    ])
    db.commit()

    db.refresh(checking)
    db.refresh(income)
    assert checking.balance == Decimal("500.00")
    assert income.balance == Decimal("500.00")


def test_liability_balance_increases_on_credit(db):
    """Crediting a liability account should increase its balance."""
    accounts = _seed_accounts(db)
    expense = accounts["6000"]
    ap = accounts["2000"]

    create_journal_entry(db, "2026-01-15", "Bill received", [
        {"account_id": expense.id, "debit": Decimal("250.00"), "credit": Decimal("0")},
        {"account_id": ap.id, "debit": Decimal("0"), "credit": Decimal("250.00")},
    ])
    db.commit()

    db.refresh(expense)
    db.refresh(ap)
    assert expense.balance == Decimal("250.00")
    assert ap.balance == Decimal("250.00")


def test_decimal_precision(db):
    """Verify exact Decimal math — no float rounding errors."""
    accounts = _seed_accounts(db)
    checking = accounts["1000"]
    income = accounts["4000"]

    # $33.33 * 3 = $99.99 exactly (not 99.99000000000001)
    for _ in range(3):
        create_journal_entry(db, "2026-01-15", "Small payment", [
            {"account_id": checking.id, "debit": Decimal("33.33"), "credit": Decimal("0")},
            {"account_id": income.id, "debit": Decimal("0"), "credit": Decimal("33.33")},
        ])
    db.commit()

    db.refresh(checking)
    assert checking.balance == Decimal("99.99")


def test_negative_amount_raises(db):
    """Negative debit or credit should raise ValueError."""
    accounts = _seed_accounts(db)
    checking = accounts["1000"]

    with pytest.raises(ValueError, match="non-negative"):
        create_journal_entry(db, "2026-01-15", "Bad amount", [
            {"account_id": checking.id, "debit": Decimal("-100"), "credit": Decimal("0")},
        ])
