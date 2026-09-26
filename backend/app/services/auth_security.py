"""
Authentication and password security service:
- Password strength validation (NIST SP 800-63B guidelines)
- Common breach / weak password dictionary checks
- Account lockout and failed attempt tracking
"""

from __future__ import annotations
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

# Maximum failed login attempts before lockout
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

# Common easily-guessed / breached passwords (all lowercase)
COMMON_WEAK_PASSWORDS = {
    "password123",
    "password1234",
    "1234567890",
    "123456789",
    "12345678",
    "admin12345",
    "welcome1234",
    "letmein1234",
    "iloveyou123",
    "qwerty12345",
    "administrator",
    "adminadmin1",
}

# Thread-safe in-memory store for tracking failed attempts and lockouts
# Structure: { normalized_email: {"attempts": int, "locked_until": datetime | None, "last_attempt": datetime} }
_lockout_store: dict[str, dict] = {}
_lockout_lock = threading.Lock()


def validate_password_strength(password: str, email: str = "") -> tuple[bool, Optional[str]]:
    """Validate password against NIST 800-63B and secure design guidelines.

    Returns:
        (True, None) if valid, or (False, error_message) if invalid.
    """
    if not password or len(password) < 10:
        return False, "Password must be at least 10 characters long."

    if len(password) > 128:
        return False, "Password cannot exceed 128 characters."

    normalized = password.lower().strip()
    if normalized in COMMON_WEAK_PASSWORDS:
        return False, "This password is too common and easily guessed. Please choose a stronger password."

    if password.isdigit():
        return False, "Password cannot consist entirely of numbers."

    if password.isalpha():
        return False, "Password must contain a mix of letters and numbers or symbols."

    if email and "@" in email:
        local_part = email.split("@")[0].lower()
        if len(local_part) >= 4 and local_part in normalized:
            return False, "Password cannot contain your email username."

    return True, None


def is_account_locked(email: str) -> tuple[bool, int]:
    """Check if an account is locked due to too many failed login attempts.

    Returns:
        (is_locked, remaining_seconds)
    """
    key = email.strip().lower()
    now = datetime.now(timezone.utc)
    with _lockout_lock:
        record = _lockout_store.get(key)
        if not record:
            return False, 0

        locked_until = record.get("locked_until")
        if locked_until:
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds())
                return True, max(1, remaining)
            else:
                # Lock has expired, reset attempts
                _lockout_store.pop(key, None)
                return False, 0

        return False, 0


def record_failed_login(email: str) -> tuple[bool, int]:
    """Record a failed login attempt for an email.

    Returns:
        (is_now_locked, remaining_attempts_or_lockout_seconds)
    """
    key = email.strip().lower()
    now = datetime.now(timezone.utc)
    with _lockout_lock:
        record = _lockout_store.setdefault(key, {
            "attempts": 0,
            "locked_until": None,
            "last_attempt": now,
        })
        record["attempts"] += 1
        record["last_attempt"] = now

        if record["attempts"] >= MAX_FAILED_ATTEMPTS:
            locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            record["locked_until"] = locked_until
            return True, LOCKOUT_DURATION_MINUTES * 60

        remaining = MAX_FAILED_ATTEMPTS - record["attempts"]
        return False, max(0, remaining)


def record_successful_login(email: str) -> None:
    """Clear failed attempts upon successful login."""
    key = email.strip().lower()
    with _lockout_lock:
        _lockout_store.pop(key, None)


def reset_lockout_state(email: Optional[str] = None) -> None:
    """Reset lockout state for a specific email or all emails (used in tests/admin)."""
    with _lockout_lock:
        if email:
            _lockout_store.pop(email.strip().lower(), None)
        else:
            _lockout_store.clear()
