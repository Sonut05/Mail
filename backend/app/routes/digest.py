"""
Digest routes — Morning personal productivity briefing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.services.digest_service import generate_daily_digest
from app.utils.auth import login_required, validate_session

digest_bp = Blueprint("digest", __name__, url_prefix="/api/digest")


def _require_auth():
    return validate_session()


@digest_bp.route("", methods=["GET"])
@login_required
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
