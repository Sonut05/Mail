"""
Preferences routes — user email intelligence settings, feedback signals, and privacy controls.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session, current_app

from app.extensions import db
from app.models import User, EmailMessage, AIAnalysisJob
from app.services.personalization_service import (
    get_or_create_user_preferences,
    update_user_preferences,
    record_user_feedback_signal,
    get_user_signals_map,
)

preferences_bp = Blueprint("preferences", __name__, url_prefix="/api/preferences")


def _require_auth():
    """Verify session authentication and return User or 401 response."""
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@preferences_bp.route("", methods=["GET"])
def get_preferences():
    """Retrieve the current user's intelligence and personalization preferences."""
    user, err = _require_auth()
    if err:
        return err

    try:
        pref = get_or_create_user_preferences(user.id)
        signals = get_user_signals_map(user.id)
        data = pref.to_dict()
        data["signals_summary"] = signals
        return jsonify({"preferences": data}), 200
    except Exception as exc:
        current_app.logger.error("Error getting preferences for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to retrieve preferences."}), 500


@preferences_bp.route("", methods=["PUT"])
def update_preferences():
    """Update user preferences with strict type and boundary validation."""
    user, err = _require_auth()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        pref, val_err = update_user_preferences(user.id, data)
        if val_err:
            return jsonify({"error": val_err}), 400

        return jsonify({
            "message": "Preferences updated successfully.",
            "preferences": pref.to_dict(),
        }), 200
    except Exception as exc:
        current_app.logger.error("Error updating preferences for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to update preferences."}), 500


@preferences_bp.route("/signals", methods=["POST"])
def add_signal():
    """Record a user feedback signal (e.g., mark important, dismiss suggestion, category override)."""
    user, err = _require_auth()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        signal_type = data.get("signal_type")
        target_type = data.get("target_type")
        target_value = data.get("target_value")
        raw_weight = data.get("signal_weight", data.get("weight", 1.0))

        try:
            weight = float(raw_weight)
            if abs(weight) > 50:
                return jsonify({"error": "Signal weight must be between -50 and 50."}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid signal weight."}), 400

        # Auto-resolve from email_id if provided
        email_id = data.get("email_id")
        if email_id and (not target_type or not target_value):
            email_msg = EmailMessage.query.filter_by(id=email_id, user_id=user.id).first()
            if email_msg:
                target_type = target_type or "sender"
                target_value = target_value or email_msg.from_address

        if not signal_type or not target_type or not target_value:
            return jsonify({"error": "Missing required fields: signal_type, target_type, target_value."}), 400

        sig = record_user_feedback_signal(
            user_id=user.id,
            signal_type=str(signal_type),
            target_type=str(target_type),
            target_value=str(target_value),
            weight=float(weight),
        )

        return jsonify({
            "message": "Feedback signal recorded.",
            "signal": sig.to_dict(),
        }), 201
    except Exception as exc:
        current_app.logger.error("Error recording signal for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to record feedback signal."}), 500


@preferences_bp.route("/ai-data", methods=["DELETE"])
def clear_ai_data():
    """Controlled privacy mechanism: clears only AI-derived data for the current user.

    Does NOT delete raw email messages, user-confirmed tasks, or calendar events.
    Cancels pending AI jobs and sets all AI columns back to pristine null/default values.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        from app.services.personalization_service import clear_user_ai_data
        result = clear_user_ai_data(user.id)

        return jsonify({
            "success": True,
            "message": "AI analysis data cleared successfully for current user.",
            "emails_cleared": result["emails_cleared"],
            "jobs_removed": result["jobs_removed"],
        }), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Error clearing AI data for %s: %s", user.id, exc)
        return jsonify({"error": "Failed to clear AI data."}), 500
