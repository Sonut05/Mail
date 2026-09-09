"""
Action Center routes — List, snooze, complete, dismiss, and bulk manage actions.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.models.action_item import ActionItem
from app.services.action_center_service import (
    get_action_center,
    sync_actions,
    snooze_action,
    dismiss_action,
    complete_action,
)
from app.services.bulk_action_service import execute_bulk_action

actions_bp = Blueprint("actions", __name__, url_prefix="/api/actions")


def _require_auth():
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@actions_bp.route("", methods=["GET"])
def list_actions():
    """GET /api/actions — List paginated Action Center items."""
    user, err = _require_auth()
    if err:
        return err

    # Perform on-demand sync if requested or on first page load
    auto_sync = request.args.get("sync", "true").lower() == "true"
    if auto_sync:
        sync_actions(user.id)

    action_type = request.args.get("type")
    priority = request.args.get("priority")
    status = request.args.get("status")
    include_snoozed = request.args.get("include_snoozed", "false").lower() == "true"

    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    except ValueError:
        return jsonify({"error": "Invalid pagination parameters."}), 400

    result = get_action_center(
        user_id=user.id,
        action_type=action_type,
        priority=priority,
        status=status,
        include_snoozed=include_snoozed,
        page=page,
        page_size=page_size
    )
    return jsonify(result), 200


@actions_bp.route("/<action_id>/snooze", methods=["POST"])
def snooze_action_endpoint(action_id: str):
    """POST /api/actions/<id>/snooze — Snooze an action item."""
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    duration = data.get("duration", "tomorrow")
    custom_date = data.get("custom_date")

    try:
        item = snooze_action(user.id, action_id, duration=duration, custom_date=custom_date)
        return jsonify({"success": True, "action": item.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@actions_bp.route("/<action_id>/dismiss", methods=["POST"])
def dismiss_action_endpoint(action_id: str):
    """POST /api/actions/<id>/dismiss — Dismiss an action item."""
    user, err = _require_auth()
    if err:
        return err

    try:
        item = dismiss_action(user.id, action_id)
        return jsonify({"success": True, "action": item.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@actions_bp.route("/<action_id>/complete", methods=["POST"])
def complete_action_endpoint(action_id: str):
    """POST /api/actions/<id>/complete — Mark an action item complete."""
    user, err = _require_auth()
    if err:
        return err

    try:
        item = complete_action(user.id, action_id)
        return jsonify({"success": True, "action": item.to_dict()}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@actions_bp.route("/bulk", methods=["POST"])
def bulk_action_endpoint():
    """POST /api/actions/bulk — Execute bulk action across selected items."""
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    item_ids = data.get("item_ids") or data.get("email_ids") or []
    item_type = data.get("item_type", "email")
    options = data.get("options") or {}

    if not action or not item_ids:
        return jsonify({"error": "action and item_ids are required."}), 400

    try:
        result = execute_bulk_action(
            user_id=user.id,
            action=action,
            item_ids=item_ids,
            item_type=item_type,
            options=options
        )
        return jsonify(result), 200
    except PermissionError as e:
        return jsonify({"error": str(e)}), 403
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@actions_bp.route("/<action_id>", methods=["GET"])
def get_action_endpoint(action_id: str):
    """GET /api/actions/<id> — Get a single action item with ownership check."""
    user, err = _require_auth()
    if err:
        return err

    item = ActionItem.query.filter_by(id=action_id).first()
    if not item:
        return jsonify({"error": "Action item not found."}), 404
    if item.user_id != user.id:
        return jsonify({"error": "Access denied."}), 403

    return jsonify({"success": True, "action": item.to_dict()}), 200


@actions_bp.route("/<action_id>", methods=["PATCH", "PUT"])
def update_action_endpoint(action_id: str):
    """PATCH /api/actions/<id> — Update action item priority/title with ownership check."""
    user, err = _require_auth()
    if err:
        return err

    item = ActionItem.query.filter_by(id=action_id).first()
    if not item:
        return jsonify({"error": "Action item not found."}), 404
    if item.user_id != user.id:
        return jsonify({"error": "Access denied."}), 403

    data = request.get_json(silent=True) or {}
    if "title" in data:
        item.title = str(data["title"])[:255]
    if "priority" in data:
        item.priority = str(data["priority"]).lower()

    db.session.commit()
    return jsonify({"success": True, "action": item.to_dict()}), 200


@actions_bp.route("/<action_id>", methods=["DELETE"])
def delete_action_endpoint(action_id: str):
    """DELETE /api/actions/<id> — Delete an action item with ownership check."""
    user, err = _require_auth()
    if err:
        return err

    item = ActionItem.query.filter_by(id=action_id).first()
    if not item:
        return jsonify({"error": "Action item not found."}), 404
    if item.user_id != user.id:
        return jsonify({"error": "Access denied."}), 403

    db.session.delete(item)
    db.session.commit()
    return jsonify({"success": True}), 200
