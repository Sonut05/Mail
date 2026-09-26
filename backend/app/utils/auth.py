"""
Central authentication utilities and decorators.
Enforces authentication, session rotation, absolute session expiry, and idle timeout.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

from flask import current_app, g, jsonify, request, session

from app.extensions import db
from app.models.user import User

DEFAULT_ABSOLUTE_EXPIRY = 7 * 24 * 60 * 60  # 7 days
DEFAULT_IDLE_TIMEOUT = 24 * 60 * 60  # 24 hours


def rotate_session(user_id: str) -> None:
    """Clear session data and re-issue with fresh timestamps to prevent session fixation."""
    # Retain any specific keys needed across rotation if any, but clear everything else
    session.clear()
    now = time.time()
    session["user_id"] = user_id
    session["_auth_created_at"] = now
    session["_auth_last_active"] = now
    session.permanent = True


def validate_session() -> tuple[User | None, Any | None]:
    """Validate current session against presence, absolute expiry, and idle timeout.

    Returns:
        (user, None) if valid.
        (None, error_response) if invalid or expired.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)

    now = time.time()
    abs_expiry = current_app.config.get("SESSION_ABSOLUTE_EXPIRY_SECONDS", DEFAULT_ABSOLUTE_EXPIRY)
    idle_timeout = current_app.config.get("SESSION_IDLE_TIMEOUT_SECONDS", DEFAULT_IDLE_TIMEOUT)

    created_at = session.get("_auth_created_at")
    last_active = session.get("_auth_last_active")

    # If timestamps are missing in an existing session, initialize them now or expire
    if created_at is not None and (now - created_at) > abs_expiry:
        session.clear()
        return None, (jsonify({"error": "Session expired. Please log in again."}), 401)

    if last_active is not None and (now - last_active) > idle_timeout:
        session.clear()
        return None, (jsonify({"error": "Session timed out due to inactivity. Please log in again."}), 401)

    # Touch last active
    session["_auth_last_active"] = now
    if created_at is None:
        session["_auth_created_at"] = now

    user = db.session.get(User, user_id)
    if not user:
        session.clear()
        return None, (jsonify({"error": "User not found."}), 401)

    g.current_user = user
    g.user_id = user.id
    return user, None


def login_required(f: Callable) -> Callable:
    """Decorator to enforce authentication on Flask routes.

    Ensures session.get('user_id') exists, validates session lifetime,
    and attaches current user to Flask `g`.
    """
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        user, err = validate_session()
        if err:
            return err
        return f(*args, **kwargs)

    return decorated_function
