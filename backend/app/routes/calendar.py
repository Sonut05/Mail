"""
Calendar routes — list, create, update, and delete calendar events.
Includes conflict detection, end > start validation, and strict user isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request, session, current_app
from sqlalchemy import and_, or_

from app.extensions import db
from app.models import User, CalendarEvent, EmailMessage

calendar_bp = Blueprint("calendar", __name__, url_prefix="/api/calendar")


def _require_auth():
    """Return (user, None) or (None, error_response)."""
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


def _parse_dt(val) -> datetime | None:
    """Parse an ISO date/datetime string into a UTC-aware datetime."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _find_conflicts(user_id: str, start_dt: datetime, end_dt: datetime, exclude_id: str | None = None) -> list[CalendarEvent]:
    """Find overlapping events for the same user.

    Overlap condition:
        existing.start < new_end AND existing.end > new_start
    If existing.end is NULL, assume a 1-hour duration for conflict detection.
    """
    query = CalendarEvent.query.filter(CalendarEvent.user_id == user_id)
    if exclude_id:
        query = query.filter(CalendarEvent.id != exclude_id)

    candidates = query.all()
    conflicts = []
    for cand in candidates:
        c_start = cand.start_date_time
        if c_start.tzinfo is None:
            c_start = c_start.replace(tzinfo=timezone.utc)

        c_end = cand.end_date_time
        if c_end is None:
            c_end = c_start + timedelta(hours=1)
        elif c_end.tzinfo is None:
            c_end = c_end.replace(tzinfo=timezone.utc)

        # Check overlap
        if c_start < end_dt and c_end > start_dt:
            conflicts.append(cand)

    return conflicts


@calendar_bp.route("", methods=["GET"])
def list_events():
    """List all calendar events for the current authenticated user.

    Returns:
        200 with list of events ordered by start time.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        events = (
            CalendarEvent.query
            .filter(CalendarEvent.user_id == user.id)
            .order_by(CalendarEvent.start_date_time.asc())
            .all()
        )

        return jsonify({"events": [e.to_dict() for e in events]}), 200

    except Exception as exc:
        current_app.logger.error("Error listing calendar events: %s", exc)
        return jsonify({"error": "Failed to list calendar events."}), 500


@calendar_bp.route("/check-conflict", methods=["POST"])
def check_conflict_endpoint():
    """Check whether a proposed start/end time conflicts with existing calendar events.
    Canonical overlap logic: start < existing.end AND end > existing.start
    """
    user, err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    start_val = data.get("start") or data.get("start_date_time") or data.get("start_datetime")
    end_val = data.get("end") or data.get("end_date_time") or data.get("end_datetime")
    exclude_id = data.get("exclude_id")

    if not start_val:
        return jsonify({"error": "start date/time is required."}), 400

    start_dt = _parse_dt(start_val)
    if not start_dt:
        return jsonify({"status": "POSSIBLE_CONFLICT", "conflicts": []}), 200

    end_dt = _parse_dt(end_val) if end_val else (start_dt + timedelta(hours=1))
    if not end_dt:
        end_dt = start_dt + timedelta(hours=1)

    conflicts = _find_conflicts(user.id, start_dt, end_dt, exclude_id=exclude_id)
    status = "CONFLICT" if conflicts else "NO_CONFLICT"
    return jsonify({
        "status": status,
        "conflicts": [c.to_dict() for c in conflicts]
    }), 200


@calendar_bp.route("", methods=["POST"])
def create_event():
    """Create a calendar event (manual or linked to an email).

    JSON body:
        email_id: UUID of the source email (optional).
        title: Title of the event (required).
        description: Description (optional).
        start / start_date_time: ISO datetime string (required).
        end / end_date_time: ISO datetime string (optional, defaults to start + 1 hour).
        location: Location string (optional).
        meeting_link: Video call link (optional).
        timezone: Timezone string (default UTC).

    Returns:
        201 with created event and conflict info, or 400 validation error.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        email_id = data.get("email_id")
        title = data.get("title")
        start_val = data.get("start") or data.get("start_date_time")
        end_val = data.get("end") or data.get("end_date_time")

        if not title or not str(title).strip():
            return jsonify({"error": "Event title is required."}), 400

        # Verify email ownership if email_id is provided
        if email_id:
            email_msg = EmailMessage.query.filter_by(id=email_id).first()
            if not email_msg:
                return jsonify({"error": "Referenced email not found."}), 404

            if email_msg.user_id != user.id:
                if not (email_msg.connected_account and email_msg.connected_account.user_id == user.id):
                    return jsonify({"error": "Access denied. Email does not belong to you."}), 403

        if not start_val:
            return jsonify({"error": "Event start date/time is required."}), 400
        if not end_val:
            return jsonify({"error": "Event end date/time is required."}), 400

        start_dt = _parse_dt(start_val)
        if not start_dt:
            return jsonify({"error": "Invalid start date/time format."}), 400

        end_dt = _parse_dt(end_val)
        if not end_dt:
            return jsonify({"error": "Invalid end date/time format."}), 400

        # Validation: end > start
        if end_dt <= start_dt:
            return jsonify({"error": "Event end time must be after start time."}), 400

        # Conflict detection
        conflicts = _find_conflicts(user.id, start_dt, end_dt)
        has_conflict = len(conflicts) > 0

        event = CalendarEvent(
            user_id=user.id,
            email_id=email_id,
            title=str(title).strip(),
            description=data.get("description"),
            start_date_time=start_dt,
            end_date_time=end_dt,
            timezone=data.get("timezone") or "UTC",
            location=data.get("location"),
            meeting_link=data.get("meeting_link"),
            organizer=data.get("organizer") or user.email,
        )
        db.session.add(event)
        db.session.commit()

        return jsonify({
            "success": True,
            "event": event.to_dict(),
            "has_conflict": has_conflict,
            "conflicts": [c.to_dict() for c in conflicts],
            "message": "Calendar event created successfully.",
        }), 201

    except Exception as exc:
        current_app.logger.error("Error creating calendar event: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to create calendar event: {str(exc)}"}), 500


@calendar_bp.route("/<string:event_id>", methods=["GET"])
def get_event(event_id: str):
    """Get a single calendar event by ID along with its source email metadata."""
    user, err = _require_auth()
    if err:
        return err

    try:
        event = CalendarEvent.query.filter_by(id=event_id, user_id=user.id).first()
        if not event:
            return jsonify({"error": "Calendar event not found."}), 404

        data = event.to_dict()
        if event.email_id and event.email:
            data["source_email"] = {
                "id": event.email.id,
                "subject": event.email.subject,
                "from_address": event.email.from_address,
                "sender": event.email.from_address,
                "received_at": event.email.received_at.isoformat() if event.email.received_at else None,
            }
        else:
            data["source_email"] = None

        return jsonify({"event": data}), 200

    except Exception as exc:
        current_app.logger.error("Error fetching calendar event %s: %s", event_id, exc)
        return jsonify({"error": "Failed to fetch calendar event."}), 500


@calendar_bp.route("/<string:event_id>", methods=["PUT", "PATCH"])
def update_event(event_id: str):
    """Update a calendar event with conflict detection and end > start validation."""
    user, err = _require_auth()
    if err:
        return err

    try:
        event = CalendarEvent.query.filter_by(id=event_id, user_id=user.id).first()
        if not event:
            return jsonify({"error": "Calendar event not found."}), 404

        data = request.get_json(silent=True) or {}

        if "title" in data and str(data["title"]).strip():
            event.title = str(data["title"]).strip()

        if "description" in data:
            event.description = data["description"]

        if "location" in data:
            event.location = data["location"]

        if "meeting_link" in data:
            event.meeting_link = data["meeting_link"]

        if "timezone" in data:
            event.timezone = data["timezone"]

        start_val = data.get("start") or data.get("start_date_time")
        end_val = data.get("end") or data.get("end_date_time")

        target_start = event.start_date_time
        if start_val is not None:
            parsed_start = _parse_dt(start_val)
            if not parsed_start:
                return jsonify({"error": "Invalid start date/time format."}), 400
            target_start = parsed_start

        target_end = event.end_date_time
        if end_val is not None:
            parsed_end = _parse_dt(end_val)
            if not parsed_end:
                return jsonify({"error": "Invalid end date/time format."}), 400
            target_end = parsed_end

        if target_start and target_start.tzinfo is None:
            target_start = target_start.replace(tzinfo=timezone.utc)
        if target_end and target_end.tzinfo is None:
            target_end = target_end.replace(tzinfo=timezone.utc)

        # Validate times
        if target_start and target_end:
            if target_end <= target_start:
                return jsonify({"error": "Event end time must be after start time."}), 400
            event.start_date_time = target_start
            event.end_date_time = target_end
        elif target_start:
            event.start_date_time = target_start

        # Detect conflicts excluding self
        conflicts = []
        if event.start_date_time:
            eff_end = event.end_date_time or (event.start_date_time + timedelta(hours=1))
            eff_start = event.start_date_time
            if eff_start.tzinfo is None:
                eff_start = eff_start.replace(tzinfo=timezone.utc)
            if eff_end.tzinfo is None:
                eff_end = eff_end.replace(tzinfo=timezone.utc)
            conflicts = _find_conflicts(user.id, eff_start, eff_end, exclude_id=event.id)

        event.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            "success": True,
            "event": event.to_dict(),
            "has_conflict": len(conflicts) > 0,
            "conflicts": [c.to_dict() for c in conflicts],
        }), 200

    except Exception as exc:
        current_app.logger.error("Error updating calendar event %s: %s", event_id, exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to update calendar event: {str(exc)}"}), 500


@calendar_bp.route("/<string:event_id>", methods=["DELETE"])
def delete_event(event_id: str):
    """Delete a calendar event. Source email is never deleted."""
    user, err = _require_auth()
    if err:
        return err

    try:
        event = CalendarEvent.query.filter_by(id=event_id, user_id=user.id).first()
        if not event:
            return jsonify({"error": "Calendar event not found."}), 404

        db.session.delete(event)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Calendar event deleted successfully.",
        }), 200

    except Exception as exc:
        current_app.logger.error("Error deleting calendar event %s: %s", event_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to delete calendar event."}), 500
