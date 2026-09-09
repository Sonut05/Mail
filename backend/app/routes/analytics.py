"""
Analytics routes — Productivity trends and volume time-series.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.services.analytics_service import get_productivity_analytics

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


def _require_auth():
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@analytics_bp.route("/productivity", methods=["GET"])
def productivity_metrics():
    """GET /api/analytics/productivity?period=7d|30d|90d"""
    user, err = _require_auth()
    if err:
        return err

    period = request.args.get("period", "30d")
    try:
        data = get_productivity_analytics(user.id, period=period)
        return jsonify({"success": True, "analytics": data, **data}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
