"""
Thread routes — conversation aggregation, message history, follow-up and stale intelligence.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session, current_app

from app.extensions import db
from app.models import User
from app.services.thread_service import (
    get_threads_for_user,
    get_thread_detail,
    get_stale_threads,
)
from app.services.follow_up_service import (
    get_follow_up_recommendations,
)
from app.services.personalization_service import record_user_feedback_signal

threads_bp = Blueprint("threads", __name__, url_prefix="/api/threads")


def _require_auth():
    """Verify session authentication and return User or 401 response."""
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@threads_bp.route("", methods=["GET"])
def list_threads():
    """List conversation threads with pagination, status filters, and search query."""
    user, err = _require_auth()
    if err:
        return err

    try:
        status_filter = request.args.get("status")
        query_str = request.args.get("q")
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 20, type=int), 100)

        data = get_threads_for_user(
            user_id=user.id,
            status_filter=status_filter,
            query_str=query_str,
            page=page,
            per_page=per_page,
        )
        return jsonify(data), 200
    except Exception as exc:
        current_app.logger.error("Error listing threads for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to list threads."}), 500


@threads_bp.route("/<thread_id>", methods=["GET"])
def thread_detail(thread_id: str):
    """Retrieve full chronological conversation thread with individual messages."""
    user, err = _require_auth()
    if err:
        return err

    try:
        thread_data = get_thread_detail(user_id=user.id, thread_id=thread_id)
        if not thread_data:
            return jsonify({"error": "Thread not found."}), 404
        return jsonify({"thread": thread_data}), 200
    except Exception as exc:
        current_app.logger.error("Error retrieving thread %s for %s: %s", thread_id, user.id, exc)
        return jsonify({"error": "Failed to retrieve thread details."}), 500


@threads_bp.route("/follow-ups", methods=["GET"])
def follow_ups():
    """Retrieve actionable follow-up recommendations (advisory only)."""
    user, err = _require_auth()
    if err:
        return err

    try:
        recs = get_follow_up_recommendations(user.id)
        return jsonify({
            "follow_ups": recs,
            "count": len(recs),
        }), 200
    except Exception as exc:
        current_app.logger.error("Error retrieving follow-ups for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to retrieve follow-up recommendations."}), 500


@threads_bp.route("/stale", methods=["GET"])
def stale_threads():
    """Retrieve stale conversations (no activity for >= 7 days with unresolved action)."""
    user, err = _require_auth()
    if err:
        return err

    try:
        stale_list = get_stale_threads(user.id, days_threshold=7)
        return jsonify({
            "stale_threads": stale_list,
            "count": len(stale_list),
        }), 200
    except Exception as exc:
        current_app.logger.error("Error retrieving stale threads for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to retrieve stale conversations."}), 500


@threads_bp.route("/<thread_id>/dismiss-follow-up", methods=["POST"])
def dismiss_follow_up(thread_id: str):
    """Dismiss a follow-up recommendation for this thread."""
    user, err = _require_auth()
    if err:
        return err

    try:
        record_user_feedback_signal(
            user_id=user.id,
            signal_type="dismiss_follow_up",
            target_type="thread",
            target_value=thread_id,
            weight=0.0,
        )
        return jsonify({
            "success": True,
            "message": f"Follow-up for thread {thread_id} dismissed."
        }), 200
    except Exception as exc:
        current_app.logger.error("Error dismissing follow-up for %s: %s", thread_id, exc)
        return jsonify({"error": "Failed to dismiss follow-up."}), 500
