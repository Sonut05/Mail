"""
Digest routes — Morning personal productivity briefing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.services.digest_service import generate_daily_digest

digest_bp = Blueprint("digest", __name__, url_prefix="/api/digest")


def _require_auth():
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@digest_bp.route("", methods=["GET"])
def get_digest():
    """GET /api/digest — Return structured daily productivity digest."""
    user, err = _require_auth()
    if err:
        return err

    date_str = request.args.get("date")
    tz = request.args.get("timezone", "UTC")

    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify({"error": "Invalid date format. Expected YYYY-MM-DD."}), 400

    digest_data = generate_daily_digest(user.id, target_date=target_date, user_timezone=tz)
    return jsonify({"success": True, "digest": digest_data}), 200
