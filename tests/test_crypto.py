# ============================================================================
# Encryption Tests — Fernet encrypt/decrypt roundtrip, key validation
# ============================================================================

import os
import pytest
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip():
    """Encrypted value should decrypt back to original."""
    # Generate a real key for this test
    key = Fernet.generate_key().decode()
    os.environ["ENCRYPTION_KEY"] = key

    # Reimport to pick up new key
    import importlib
    from app.services import crypto_service
    importlib.reload(crypto_service)

    original = "sk_live_abc123_stripe_secret"
    encrypted = crypto_service.encrypt_value(original)

    assert encrypted != original
    assert encrypted.startswith("enc::")

    decrypted = crypto_service.decrypt_value(encrypted)
    assert decrypted == original

    # Cleanup
    os.environ["ENCRYPTION_KEY"] = ""
    importlib.reload(crypto_service)


def test_no_key_returns_plaintext():
    """Without encryption key, values pass through unchanged."""
    os.environ["ENCRYPTION_KEY"] = ""

    import importlib
    from app.services import crypto_service
    importlib.reload(crypto_service)

    original = "plaintext_secret"
    result = crypto_service.encrypt_value(original)
    assert result == original  # No encryption applied

    os.environ["ENCRYPTION_KEY"] = ""
    importlib.reload(crypto_service)


def test_empty_value_unchanged():
    """Empty string should not be encrypted."""
    from app.services.crypto_service import encrypt_value, decrypt_value

    assert encrypt_value("") == ""
    assert decrypt_value("") == ""


def test_non_encrypted_value_passthrough():
    """Non-prefixed values should pass through decrypt unchanged."""
    from app.services.crypto_service import decrypt_value

    assert decrypt_value("plain_value") == "plain_value"


def test_sensitive_key_detection():
    """Sensitive keys should be correctly identified."""
    from app.services.crypto_service import is_sensitive_key

    assert is_sensitive_key("stripe_secret_key") is True
    assert is_sensitive_key("smtp_password") is True
    assert is_sensitive_key("qbo_access_token") is True
    assert is_sensitive_key("company_name") is False
    assert is_sensitive_key("invoice_prefix") is False
