"""
Analytics Service — Computes time-series productivity metrics over 7d, 30d, 90d periods.
Strictly user-scoped and aggregated efficiently via SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, case

from app.extensions import db
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.ai_analysis_job import AIAnalysisJob


VALID_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


def get_productivity_analytics(user_id: str, period: str = "30d") -> dict[str, Any]:
    """Calculate structured productivity time-series and summary totals for user."""
    p_key = (period or "30d").lower()
    if p_key not in VALID_PERIODS:
        raise ValueError(f"Invalid period '{period}'. Must be one of: 7d, 30d, 90d.")

    days = VALID_PERIODS[p_key]
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # 1. Email volume trend
    # Group by received_at date
    emails_query = db.session.query(
        func.date(EmailMessage.received_at).label("day"),
        func.count(EmailMessage.id).label("total_emails"),
        func.sum(case((EmailMessage.ai_action_required.is_(True), 1), else_=0)).label("action_emails")
    ).filter(
        EmailMessage.user_id == user_id,
        EmailMessage.received_at >= start_date
    ).group_by(func.date(EmailMessage.received_at)).order_by(func.date(EmailMessage.received_at).asc()).all()

    email_volume = [
        {
            "date": str(row.day),
            "total_emails": int(row.total_emails or 0),
            "action_emails": int(row.action_emails or 0)
        }
        for row in emails_query
    ]

    # 2. Task metrics
    total_tasks_created = Task.query.filter(
        Task.user_id == user_id,
        Task.created_at >= start_date
    ).count()

    total_tasks_completed = Task.query.filter(
        Task.user_id == user_id,
        Task.status == "completed",
        Task.updated_at >= start_date
    ).count()

    # 3. Action items metrics
    total_actions_completed = ActionItem.query.filter(
        ActionItem.user_id == user_id,
        ActionItem.status == ActionStatus.COMPLETED.value,
        ActionItem.completed_at >= start_date
    ).count()

    total_actions_snoozed = ActionItem.query.filter(
        ActionItem.user_id == user_id,
        ActionItem.status == ActionStatus.SNOOZED.value
    ).count()

    # 4. AI jobs volume
    ai_volume = AIAnalysisJob.query.filter(
        AIAnalysisJob.user_id == user_id,
        AIAnalysisJob.created_at >= start_date
    ).count()

    return {
        "period": p_key,
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": now.isoformat(),
        "summary": {
            "emails_received": sum(item["total_emails"] for item in email_volume),
            "emails_sent": 0,
            "action_emails": sum(item["action_emails"] for item in email_volume),
            "tasks_created": total_tasks_created,
            "tasks_completed": total_tasks_completed,
            "completion_rate_pct": round((total_tasks_completed / total_tasks_created * 100), 1) if total_tasks_created > 0 else 0.0,
            "actions_completed": total_actions_completed,
            "actions_snoozed": total_actions_snoozed,
            "ai_analyses_run": ai_volume,
        },
        "email_volume": email_volume,
        "trends": email_volume,
    }
