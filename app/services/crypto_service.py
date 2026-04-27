# ============================================================================
# Crypto Service — Fernet symmetric encryption for sensitive settings
# ============================================================================

import os
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Master key loaded from environment. If not set, encryption is disabled
# and values are stored/read as plaintext (backwards compatible).
_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# Sensitive setting keys that should be encrypted at rest
SENSITIVE_KEYS = frozenset({
    "stripe_secret_key",
    "stripe_webhook_secret",
    "qbo_client_secret",
    "qbo_access_token",
    "qbo_refresh_token",
    "smtp_password",
})

_PREFIX = "enc::"  # Marker prefix so we know a value is encrypted


def _get_fernet() -> Fernet | None:
    if not _ENCRYPTION_KEY:
        return None
    try:
        return Fernet(_ENCRYPTION_KEY.encode())
    except Exception:
        logger.warning("Invalid ENCRYPTION_KEY — encryption disabled")
        return None


def encrypt_value(value: str) -> str:
    """Encrypt a plaintext value. Returns prefixed ciphertext or original if no key."""
    if not value:
        return value
    f = _get_fernet()
    if f is None:
        return value
    encrypted = f.encrypt(value.encode()).decode()
    return f"{_PREFIX}{encrypted}"


def decrypt_value(value: str) -> str:
    """Decrypt a value if it has the encryption prefix. Returns plaintext."""
    if not value or not value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        logger.warning("Encrypted value found but ENCRYPTION_KEY not set — returning empty")
        return ""
    try:
        ciphertext = value[len(_PREFIX):]
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt value — key may have changed")
        return ""


def is_sensitive_key(key: str) -> bool:
    """Check if a settings key should be encrypted."""
    return key in SENSITIVE_KEYS
