# ============================================================================
# Closing Date Enforcement — prevent modifications before closing date
# Feature 10: Configurable closing date with optional password override
# ============================================================================

from datetime import date

from fastapi import HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.models.settings import Settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_closing_date(db: Session) -> date | None:
    """Get the configured closing date, or None if not set."""
    row = db.query(Settings).filter(Settings.key == "closing_date").first()
    if row and row.value:
        try:
            return date.fromisoformat(row.value)
        except ValueError:
            return None
    return None


def hash_closing_password(password: str) -> str:
    """Hash a closing date password for storage."""
    return _pwd_context.hash(password)


def check_closing_date(db: Session, txn_date: date, password: str = None):
    """Raise HTTPException if txn_date is on or before the closing date.
    If a closing_date_password is set and the caller provides it, allow override."""
    closing = get_closing_date(db)
    if closing is None:
        return  # No closing date configured

    if txn_date <= closing:
        # Check if password override is available
        pw_row = db.query(Settings).filter(Settings.key == "closing_date_password").first()
        if pw_row and pw_row.value and password:
            # Support both bcrypt hashed and legacy plaintext passwords
            if pw_row.value.startswith("$2"):
                if _pwd_context.verify(password, pw_row.value):
                    return  # Bcrypt password override accepted
            elif password == pw_row.value:
                # Legacy plaintext — accept but migrate to bcrypt
                pw_row.value = _pwd_context.hash(password)
                db.commit()
                return
        raise HTTPException(
            status_code=403,
            detail=f"Transaction date {txn_date} is on or before the closing date ({closing}). "
                   f"Modifications to closed periods are not allowed."
        )
