# ============================================================================
# Decompiled from qbw32.exe!CPreferencesDialog  Offset: 0x0023F800
# Original: tabbed dialog (IDD_PREFERENCES) with 12 tabs. We condensed
# everything into a single key-value store because nobody needs 12 tabs.
# ============================================================================

import logging

from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models.users import User
from app.models.settings import Settings, DEFAULT_SETTINGS
from app.services.crypto_service import encrypt_value, decrypt_value, is_sensitive_key

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _get_all(db: Session) -> dict:
    rows = db.query(Settings).all()
    result = dict(DEFAULT_SETTINGS)
    for row in rows:
        value = row.value
        if is_sensitive_key(row.key):
            value = decrypt_value(value)
        result[row.key] = value
    return result


def _set(db: Session, key: str, value: str):
    # Closing date password: bcrypt-hash instead of Fernet-encrypt
    if key == "closing_date_password" and value:
        from app.services.closing_date import hash_closing_password
        value = hash_closing_password(value)
    elif is_sensitive_key(key) and value:
        value = encrypt_value(value)
    row = db.query(Settings).filter(Settings.key == key).first()
    if row:
        row.value = value
    else:
        row = Settings(key=key, value=value)
        db.add(row)


@router.get("")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_all(db)


def validate_abn(abn: str) -> bool:
    """Validate an Australian Business Number (11-digit check digit algorithm).
    See: https://abr.business.gov.au/Help/AbnFormat
    """
    digits = abn.replace(" ", "")
    if len(digits) != 11 or not digits.isdigit():
        return False
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    nums = [int(d) for d in digits]
    nums[0] -= 1  # subtract 1 from first digit
    total = sum(w * n for w, n in zip(weights, nums))
    return total % 89 == 0


@router.put("")
def update_settings(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Validate ABN if provided
    if "abn" in data and data["abn"]:
        from fastapi import HTTPException
        abn_val = str(data["abn"]).strip()
        if not validate_abn(abn_val):
            raise HTTPException(status_code=400, detail="Invalid ABN — must be 11 digits with valid check digit")
        data["abn"] = abn_val.replace(" ", "")

    for key, value in data.items():
        if key in DEFAULT_SETTINGS:
            _set(db, key, str(value) if value is not None else "")
    db.commit()
    return _get_all(db)


@router.post("/test-email")
def test_email(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Feature 8: Send a test email to verify SMTP settings."""
    settings = _get_all(db)
    if not settings.get("smtp_host"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="SMTP not configured")
    try:
        from app.services.email_service import send_email
        send_email(
            to_email=settings.get("smtp_from_email") or settings.get("smtp_user", ""),
            subject="Slowbooks Pro 2026 — Test Email",
            html_body="<p>This is a test email from Slowbooks Pro 2026. SMTP is configured correctly.</p>",
            settings=settings,
        )
        return {"status": "sent"}
    except Exception as e:
        logger.exception("Test email failed")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Failed to send test email")
