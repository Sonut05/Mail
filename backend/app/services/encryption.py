"""
AES-256 encryption helpers for OAuth token storage.

Uses Fernet (symmetric encryption built on AES-128-CBC with HMAC-SHA256)
from the ``cryptography`` library. A single ENCRYPTION_KEY env var is used.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key.

    Raises:
        ValueError: If ENCRYPTION_KEY is not set.
    """
    key = current_app.config.get("ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "ENCRYPTION_KEY is not configured. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext token string and return the ciphertext as a UTF-8 string.

    Args:
        plaintext: The OAuth token to encrypt.

    Returns:
        The encrypted token as a base64-encoded string.
    """
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a previously encrypted token.

    Args:
        ciphertext: The encrypted token string.

    Returns:
        The original plaintext token.

    Raises:
        InvalidToken: If the ciphertext is corrupt or the key is wrong.
    """
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt token — key may have changed.")
