"""
Task routes — list, create, update, complete, reopen, and delete tasks.
Supports manual and email-linked tasks with strict user isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request, session, current_app
from sqlalchemy import func, case, and_, or_

from app.extensions import db
from app.models import User, Task, EmailMessage

tasks_bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


def _require_auth():
    """Return (user, None) or (None, error_response)."""
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@tasks_bp.route("", methods=["GET"])
def list_tasks():
    """List all tasks for the current authenticated user.

    Query params:
        status: Filter by status (e.g. pending, in_progress, completed, cancelled).
        priority: Filter by priority (low, medium, high, urgent).
        overdue: If 'true', return overdue tasks only.
        due_today: If 'true', return tasks due today only.
        due_this_week: If 'true', return tasks due in the next 7 days.
        sort_by: due_date | priority | created_at (default: smart sort).

    Returns:
        200 with list of tasks.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        query = Task.query.filter(Task.user_id == user.id)

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        week_end = today_start + timedelta(days=7)

        # Status filter
        status = request.args.get("status")
        if status:
            query = query.filter(func.lower(Task.status) == status.strip().lower())

        # Priority filter
        priority = request.args.get("priority")
        if priority:
            query = query.filter(func.lower(Task.priority) == priority.strip().lower())

        # Overdue filter
        overdue_param = request.args.get("overdue")
        if overdue_param and overdue_param.lower() == "true":
            query = query.filter(
                Task.due_date.isnot(None),
                Task.due_date < now_utc,
                ~func.lower(Task.status).in_(["completed", "cancelled"]),
            )

        # Due today filter
        due_today_param = request.args.get("due_today")
        if due_today_param and due_today_param.lower() == "true":
            query = query.filter(
                Task.due_date >= today_start,
                Task.due_date < today_end,
            )

        # Due this week filter
        due_this_week = request.args.get("due_this_week")
        if due_this_week and due_this_week.lower() == "true":
            query = query.filter(
                Task.due_date >= today_start,
                Task.due_date < week_end,
            )

        # Sorting logic
        sort_by = request.args.get("sort_by")
        if sort_by == "due_date":
            query = query.order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        elif sort_by == "priority":
            priority_rank = case(
                (func.lower(Task.priority) == "urgent", 1),
                (func.lower(Task.priority) == "high", 2),
                (func.lower(Task.priority) == "medium", 3),
                (func.lower(Task.priority) == "low", 4),
                else_=5,
            )
            query = query.order_by(priority_rank, Task.due_date.asc().nullslast())
        elif sort_by == "created_at":
            query = query.order_by(Task.created_at.desc())
        else:
            # Smart default sorting:
            # 1. Overdue tasks first
            # 2. Urgent priority
            # 3. High priority
            # 4. Nearest due date
            # 5. Remaining tasks
            is_overdue = and_(
                Task.due_date.isnot(None),
                Task.due_date < now_utc,
                ~func.lower(Task.status).in_(["completed", "cancelled"]),
            )
            priority_num = case(
                (func.lower(Task.priority) == "urgent", 1),
                (func.lower(Task.priority) == "high", 2),
                (func.lower(Task.priority) == "medium", 3),
                (func.lower(Task.priority) == "low", 4),
                else_=5,
            )
            smart_bucket = case(
                (is_overdue, 0),
                (func.lower(Task.priority) == "urgent", 1),
                (func.lower(Task.priority) == "high", 2),
                (Task.due_date.isnot(None), 3),
                else_=4,
            )
            query = query.order_by(
                smart_bucket,
                Task.due_date.asc().nullslast(),
                priority_num,
                Task.created_at.desc(),
            )

        tasks = query.all()
        return jsonify({"tasks": [t.to_dict() for t in tasks]}), 200

    except Exception as exc:
        current_app.logger.error("Error listing tasks: %s", exc)
        return jsonify({"error": "Failed to list tasks."}), 500


@tasks_bp.route("", methods=["POST"])
def create_task():
    """Create a task (either manual or linked to an email).

    JSON body:
        email_id: UUID of the source email (optional).
        title / task_title: Title of the task (required).
        description: Task description (optional).
        due_date: ISO date/datetime string (optional).
        priority: Urgent | High | Medium | Low (default: Medium).
        status: pending | in_progress | completed | cancelled (default: pending).
        assignee: Assignee name or email (optional).

    Returns:
        201 with created task, or error.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        email_id = data.get("email_id")
        task_title = data.get("task_title") or data.get("title")

        if not task_title or not str(task_title).strip():
            return jsonify({"error": "Task title is required."}), 400

        normalized_title = str(task_title).strip()
        email_msg = None

        # If email_id provided, verify ownership
        if email_id:
            email_msg = EmailMessage.query.filter_by(id=email_id).first()
            if not email_msg:
                return jsonify({"error": "Referenced email not found."}), 404

            # Verify ownership: email must belong to current user
            if email_msg.user_id != user.id:
                if not (email_msg.connected_account and email_msg.connected_account.user_id == user.id):
                    return jsonify({"error": "Access denied. Email does not belong to you."}), 403

            # Duplicate protection for email-linked tasks:
            # Check if a task with the exact same title was already created for this email
            existing_dup = Task.query.filter(
                Task.email_id == email_id,
                Task.user_id == user.id,
                func.lower(Task.task_title) == normalized_title.lower(),
            ).first()
            if existing_dup:
                return jsonify({
                    "error": "A task with this title has already been created for this email.",
                    "task": existing_dup.to_dict(),
                    "is_duplicate": True,
                }), 409

        # Parse due date or inherit from email AI deadline
        due_val = data.get("due_date")
        due_dt = None
        if due_val:
            try:
                due_dt = datetime.fromisoformat(str(due_val).replace("Z", "+00:00"))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
            except Exception:
                return jsonify({"error": "Invalid due_date format."}), 400
        elif email_msg and email_msg.ai_deadline:
            # Inherit deadline from email AI deadline
            due_dt = email_msg.ai_deadline
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)

        # Status validation
        ALLOWED_TASK_STATUSES = ("pending", "in_progress", "completed", "cancelled")
        req_status = "pending"
        if "status" in data and data["status"] is not None:
            raw_status = data["status"]
            if raw_status not in ALLOWED_TASK_STATUSES:
                return jsonify({"error": f"Invalid status: '{raw_status}'. Allowed values: pending, in_progress, completed, cancelled."}), 400
            req_status = raw_status

        # Priority validation
        ALLOWED_TASK_PRIORITIES = ("low", "medium", "high", "urgent")
        task_priority = "Medium"
        if "priority" in data and data["priority"] is not None:
            raw_p = str(data["priority"]).strip()
            if raw_p.lower() not in ALLOWED_TASK_PRIORITIES:
                return jsonify({"error": f"Invalid priority: '{raw_p}'. Allowed values: Low, Medium, High, Urgent."}), 400
            task_priority = raw_p.capitalize()

        completed_at = datetime.now(timezone.utc) if req_status == "completed" else None

        task = Task(
            user_id=user.id,
            email_id=email_id,
            task_title=normalized_title,
            description=data.get("description"),
            due_date=due_dt,
            priority=task_priority,
            status=req_status,
            assignee=data.get("assignee") or user.email,
            completed_at=completed_at,
        )
        db.session.add(task)
        db.session.commit()

        return jsonify({
            "success": True,
            "task": task.to_dict(),
            "message": "Task created successfully.",
        }), 201

    except Exception as exc:
        current_app.logger.error("Error creating task: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to create task: {str(exc)}"}), 500


@tasks_bp.route("/<string:task_id>", methods=["GET"])
def get_task(task_id: str):
    """Get a task by ID along with its source email metadata."""
    user, err = _require_auth()
    if err:
        return err

    try:
        task = Task.query.filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({"error": "Task not found."}), 404

        task_data = task.to_dict()
        if task.email_id and task.email:
            task_data["source_email"] = {
                "id": task.email.id,
                "subject": task.email.subject,
                "from_address": task.email.from_address,
                "sender": task.email.from_address,
                "received_at": task.email.received_at.isoformat() if task.email.received_at else None,
            }
        else:
            task_data["source_email"] = None

        return jsonify({"task": task_data}), 200

    except Exception as exc:
        current_app.logger.error("Error fetching task %s: %s", task_id, exc)
        return jsonify({"error": "Failed to fetch task."}), 500


@tasks_bp.route("/<string:task_id>", methods=["PUT", "PATCH"])
def update_task(task_id: str):
    """Update a task's title, description, due_date, priority, or status."""
    user, err = _require_auth()
    if err:
        return err

    try:
        task = Task.query.filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({"error": "Task not found."}), 404

        data = request.get_json(silent=True) or {}

        if "title" in data or "task_title" in data:
            new_title = data.get("title") or data.get("task_title")
            if new_title and str(new_title).strip():
                task.task_title = str(new_title).strip()

        if "description" in data:
            task.description = data["description"]

        if "priority" in data and data["priority"] is not None:
            raw_p = str(data["priority"]).strip()
            if raw_p.lower() not in ("low", "medium", "high", "urgent"):
                return jsonify({"error": f"Invalid priority: '{raw_p}'. Allowed values: Low, Medium, High, Urgent."}), 400
            task.priority = raw_p.capitalize()

        if "assignee" in data:
            task.assignee = data["assignee"]

        if "due_date" in data:
            due_val = data.get("due_date")
            if due_val:
                try:
                    due_dt = datetime.fromisoformat(str(due_val).replace("Z", "+00:00"))
                    if due_dt.tzinfo is None:
                        due_dt = due_dt.replace(tzinfo=timezone.utc)
                    task.due_date = due_dt
                except Exception:
                    return jsonify({"error": "Invalid due_date format."}), 400
            else:
                task.due_date = None

        if "status" in data and data["status"] is not None:
            raw_s = data["status"]
            if raw_s not in ("pending", "in_progress", "completed", "cancelled"):
                return jsonify({"error": f"Invalid status: '{raw_s}'. Allowed values: pending, in_progress, completed, cancelled."}), 400
            old_status = (task.status or "").lower()
            task.status = raw_s
            if raw_s == "completed" and old_status != "completed":
                task.completed_at = datetime.now(timezone.utc)
            elif raw_s != "completed" and old_status == "completed":
                task.completed_at = None

        task.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"task": task.to_dict()}), 200

    except Exception as exc:
        current_app.logger.error("Error updating task %s: %s", task_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to update task."}), 500


@tasks_bp.route("/<string:task_id>/complete", methods=["POST"])
def complete_task(task_id: str):
    """Mark a task as completed."""
    user, err = _require_auth()
    if err:
        return err

    try:
        task = Task.query.filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({"error": "Task not found."}), 404

        task.status = "completed"
        task.completed_at = datetime.now(timezone.utc)
        task.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            "success": True,
            "task": task.to_dict(),
            "message": "Task marked as completed.",
        }), 200

    except Exception as exc:
        current_app.logger.error("Error completing task %s: %s", task_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to complete task."}), 500


@tasks_bp.route("/<string:task_id>/reopen", methods=["POST"])
def reopen_task(task_id: str):
    """Reopen a completed task, setting status back to in_progress."""
    user, err = _require_auth()
    if err:
        return err

    try:
        task = Task.query.filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({"error": "Task not found."}), 404

        task.status = "in_progress"
        task.completed_at = None
        task.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            "success": True,
            "task": task.to_dict(),
            "message": "Task reopened successfully.",
        }), 200

    except Exception as exc:
        current_app.logger.error("Error reopening task %s: %s", task_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to reopen task."}), 500


@tasks_bp.route("/<string:task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    """Delete a task. Never deletes the source email."""
    user, err = _require_auth()
    if err:
        return err

    try:
        task = Task.query.filter_by(id=task_id, user_id=user.id).first()
        if not task:
            return jsonify({"error": "Task not found."}), 404

        db.session.delete(task)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Task deleted successfully.",
        }), 200

    except Exception as exc:
        current_app.logger.error("Error deleting task %s: %s", task_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to delete task."}), 500
