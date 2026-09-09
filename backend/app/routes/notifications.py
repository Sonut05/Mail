"""
Notification routes — List, unread-count, read, read-all, and dismiss.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.models.notification import Notification
from app.services.notification_service import (
    get_user_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    dismiss_notification,
)

notifications_bp = Blueprint("notifications", __name__, url_prefix="/api/notifications")


def _require_auth():
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@notifications_bp.route("", methods=["GET"])
def list_notifications():
    """GET /api/notifications — List paginated notifications."""
    user, err = _require_auth()
    if err:
        return err

    unread_only = request.args.get("unread", "false").lower() == "true"
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters."}), 400

    result = get_user_notifications(user.id, page=page, page_size=page_size, unread_only=unread_only)
    return jsonify(result), 200


@notifications_bp.route("/unread-count", methods=["GET"])
def get_unread_count():
    """GET /api/notifications/unread-count — Fast unread notification counter."""
    user, err = _require_auth()
    if err:
        return err

    from app.models.notification import Notification
    count = Notification.query.filter(
        Notification.user_id == user.id,
        Notification.read_at.is_(None),
        Notification.dismissed_at.is_(None)
    ).count()

    return jsonify({"unread_count": count}), 200


@notifications_bp.route("/<notif_id>/read", methods=["POST"])
def mark_read(notif_id: str):
    """POST /api/notifications/<id>/read — Mark notification read."""
    user, err = _require_auth()
    if err:
        return err

    try:
        notif = mark_notification_read(user.id, notif_id)
        return jsonify({"success": True, "notification": notif.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@notifications_bp.route("/read-all", methods=["POST"])
def mark_all_read():
    """POST /api/notifications/read-all — Mark all notifications read."""
    user, err = _require_auth()
    if err:
        return err

    updated = mark_all_notifications_read(user.id)
    return jsonify({"success": True, "marked_count": updated}), 200


@notifications_bp.route("/<notif_id>/dismiss", methods=["POST"])
def dismiss(notif_id: str):
    """POST /api/notifications/<id>/dismiss — Dismiss notification."""
    user, err = _require_auth()
    if err:
        return err

    try:
        notif = dismiss_notification(user.id, notif_id)
        return jsonify({"success": True, "notification": notif.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@notifications_bp.route("/<notif_id>", methods=["GET"])
def get_notification_endpoint(notif_id: str):
    """GET /api/notifications/<id> — Retrieve a single notification with ownership check."""
    user, err = _require_auth()
    if err:
        return err

    notif = Notification.query.filter_by(id=notif_id).first()
    if not notif:
        return jsonify({"error": "Notification not found."}), 404
    if notif.user_id != user.id:
        return jsonify({"error": "Access denied."}), 403

    return jsonify({"success": True, "notification": notif.to_dict()}), 200


@notifications_bp.route("/<notif_id>", methods=["DELETE"])
def delete_notification_endpoint(notif_id: str):
    """DELETE /api/notifications/<id> — Delete a single notification with ownership check."""
    user, err = _require_auth()
    if err:
        return err

    notif = Notification.query.filter_by(id=notif_id).first()
    if not notif:
        return jsonify({"error": "Notification not found."}), 404
    if notif.user_id != user.id:
        return jsonify({"error": "Access denied."}), 403

    db.session.delete(notif)
    db.session.commit()
    return jsonify({"success": True}), 200
