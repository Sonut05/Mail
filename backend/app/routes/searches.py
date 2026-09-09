"""
Saved Search routes — CRUD management for user-scoped parameterized searches.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models.user import User
from app.models.saved_search import SavedSearch

searches_bp = Blueprint("searches", __name__, url_prefix="/api/searches")


def _require_auth():
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@searches_bp.route("", methods=["GET"])
def list_searches():
    """GET /api/searches — List all saved searches for the authenticated user."""
    user, err = _require_auth()
    if err:
        return err

    items = db.session.query(SavedSearch).filter_by(user_id=user.id).order_by(SavedSearch.name.asc()).all()
    return jsonify({"searches": [i.to_dict() for i in items]}), 200


@searches_bp.route("", methods=["POST"])
def create_saved_search():
    """POST /api/searches — Create a new saved search."""
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    query = str(data.get("query") or "").strip()

    if not name or not query:
        return jsonify({"error": "Both 'name' and 'query' are required."}), 400

    if len(name) > 100:
        return jsonify({"error": "'name' must not exceed 100 characters."}), 400
    if len(query) > 500:
        return jsonify({"error": "'query' must not exceed 500 characters."}), 400

    # Check for duplicate name for this user
    existing = db.session.query(SavedSearch).filter_by(user_id=user.id, name=name).first()
    if existing:
        return jsonify({"error": f"A saved search named '{name}' already exists."}), 400

    search_item = SavedSearch(user_id=user.id, name=name, query=query)
    db.session.add(search_item)
    db.session.commit()
    return jsonify({"success": True, "saved_search": search_item.to_dict(), "search": search_item.to_dict()}), 201


@searches_bp.route("/<search_id>", methods=["GET"])
def get_saved_search(search_id: str):
    """GET /api/searches/<id> — Retrieve specific saved search."""
    user, err = _require_auth()
    if err:
        return err

    item = db.session.query(SavedSearch).filter_by(id=search_id, user_id=user.id).first()
    if not item:
        return jsonify({"error": "Saved search not found."}), 404
    return jsonify({"saved_search": item.to_dict(), "search": item.to_dict()}), 200


@searches_bp.route("/<search_id>", methods=["PUT"])
def update_saved_search(search_id: str):
    """PUT /api/searches/<id> — Update saved search."""
    user, err = _require_auth()
    if err:
        return err

    item = db.session.query(SavedSearch).filter_by(id=search_id, user_id=user.id).first()
    if not item:
        return jsonify({"error": "Saved search not found."}), 404

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    query = str(data.get("query") or "").strip()

    if name:
        if len(name) > 100:
            return jsonify({"error": "'name' must not exceed 100 characters."}), 400
        # Check name collision
        collision = db.session.query(SavedSearch).filter(
            SavedSearch.user_id == user.id,
            SavedSearch.name == name,
            SavedSearch.id != search_id
        ).first()
        if collision:
            return jsonify({"error": f"A saved search named '{name}' already exists."}), 400
        item.name = name

    if query:
        if len(query) > 500:
            return jsonify({"error": "'query' must not exceed 500 characters."}), 400
        item.query = query

    db.session.commit()
    return jsonify({"success": True, "saved_search": item.to_dict(), "search": item.to_dict()}), 200


@searches_bp.route("/<search_id>", methods=["DELETE"])
def delete_saved_search(search_id: str):
    """DELETE /api/searches/<id> — Delete saved search."""
    user, err = _require_auth()
    if err:
        return err

    item = db.session.query(SavedSearch).filter_by(id=search_id, user_id=user.id).first()
    if not item:
        return jsonify({"error": "Saved search not found."}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({"success": True, "deleted_id": search_id}), 200
