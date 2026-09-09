"""
Dashboard routes — aggregated statistics and productivity widgets for the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, session, current_app
from sqlalchemy import func, and_, or_, case

from app.extensions import db
from app.models import User, EmailMessage, Task, CalendarEvent, AIAnalysisJob
from app.services.thread_service import get_stale_threads, get_threads_for_user
from app.services.follow_up_service import get_follow_up_recommendations
from app.services.contact_service import get_all_contacts_for_user

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


def _require_auth():
    """Return (user, None) or (None, error_response)."""
    user_id = session.get("user_id")
    if not user_id:
        return None, (jsonify({"error": "Authentication required."}), 401)
    user = db.session.get(User, user_id)
    if not user:
        return None, (jsonify({"error": "User not found."}), 401)
    return user, None


@dashboard_bp.route("/stats", methods=["GET"])
def stats():
    """Return aggregated email, task, calendar, and AI statistics for the dashboard.

    All counts and queries are strictly isolated to the authenticated user.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        # ── 1. Consolidated Email Fetch & In-Memory Computation ──
        from sqlalchemy.orm import defer
        user_emails = (
            EmailMessage.query.filter_by(user_id=user.id)
            .options(defer(EmailMessage.body_text), defer(EmailMessage.body_html))
            .order_by(EmailMessage.received_at.desc())
            .all()
        )

        total_emails = len(user_emails)
        by_category = {}
        by_priority = {}
        by_sentiment = {}
        pending_reviews = 0
        auto_replies_sent = 0
        ai_analyzed = 0
        ai_pending = 0
        ai_action_required = 0
        waiting_for_count = 0
        p_low = 0
        p_medium = 0
        p_high = 0
        p_urgent = 0
        unread_count = 0
        high_priority_count = 0
        upcoming_deadline_emails_count = 0
        action_emails = []

        for em in user_emails:
            cat = em.category or "Uncategorized"
            by_category[cat] = by_category.get(cat, 0) + 1

            pri = em.priority or "Unset"
            by_priority[pri] = by_priority.get(pri, 0) + 1

            sent = em.sentiment or "Unknown"
            by_sentiment[sent] = by_sentiment.get(sent, 0) + 1

            if em.needs_human_review:
                pending_reviews += 1
            if em.auto_reply_sent:
                auto_replies_sent += 1

            if em.ai_status == "completed":
                ai_analyzed += 1
            elif em.ai_status == "pending" or em.ai_status is None:
                ai_pending += 1

            if em.ai_action_required:
                ai_action_required += 1
                action_emails.append(em)

            if em.ai_waiting_for:
                waiting_for_count += 1

            score = em.ai_importance_score
            p_level = (em.ai_priority or "").lower()
            if (score is not None and score <= 30) or (score is None and p_level == "low"):
                p_low += 1
            elif (score is not None and 30 < score <= 60) or (score is None and p_level == "medium"):
                p_medium += 1
            elif (score is not None and 60 < score <= 80) or (score is None and p_level == "high"):
                p_high += 1
            elif (score is not None and score > 80) or (score is None and p_level == "urgent"):
                p_urgent += 1

            if (em.labels and "unread" in em.labels.lower()) or em.needs_human_review:
                unread_count += 1

            if (score is not None and score >= 61) or p_level in ("high", "urgent"):
                high_priority_count += 1

            if em.ai_deadline:
                dl = em.ai_deadline if em.ai_deadline.tzinfo else em.ai_deadline.replace(tzinfo=timezone.utc)
                if dl >= now_utc:
                    upcoming_deadline_emails_count += 1

        priority_distribution = {
            "low": p_low,
            "medium": p_medium,
            "high": p_high,
            "urgent": p_urgent,
        }

        # ── 2. Task Statistics & Deadlines (Single consolidated DB query) ──
        user_tasks = Task.query.filter_by(user_id=user.id).all()
        t_total = len(user_tasks)
        t_pending = 0
        t_in_progress = 0
        t_completed = 0
        t_cancelled = 0
        t_overdue = 0
        t_due_today = 0
        upcoming_tasks = []
        overdue_tasks_for_reminders = []
        task_email_ids = set()

        for t in user_tasks:
            if t.email_id:
                task_email_ids.add(t.email_id)
            st = (t.status or "").lower()
            if st == "pending":
                t_pending += 1
            elif st == "in_progress":
                t_in_progress += 1
            elif st == "completed":
                t_completed += 1
            elif st == "cancelled":
                t_cancelled += 1

            if t.due_date and st not in ("completed", "cancelled"):
                dt = t.due_date if t.due_date.tzinfo else t.due_date.replace(tzinfo=timezone.utc)
                if dt < now_utc:
                    t_overdue += 1
                    overdue_tasks_for_reminders.append(t)
                if dt >= today_start and dt < today_end:
                    t_due_today += 1
                if dt >= today_start:
                    upcoming_tasks.append(t)

        def _as_utc(dt):
            if dt is None:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        upcoming_tasks.sort(key=lambda t: _as_utc(t.due_date) or datetime.max.replace(tzinfo=timezone.utc))
        upcoming_deadlines_data = [t.to_dict() for t in upcoming_tasks[:10]]
        overdue_tasks_for_reminders.sort(key=lambda t: _as_utc(t.due_date) or datetime.min.replace(tzinfo=timezone.utc))
        overdue_tasks_for_reminders = overdue_tasks_for_reminders[:5]

        # ── 3. Calendar Statistics (Bounded single query) ──
        all_cal_events = (
            CalendarEvent.query.filter(
                CalendarEvent.user_id == user.id,
                CalendarEvent.start_date_time >= today_start,
            )
            .order_by(CalendarEvent.start_date_time.asc())
            .all()
        )
        today_events = [e for e in all_cal_events if _as_utc(e.start_date_time) < today_end]
        upcoming_events = [e for e in all_cal_events if _as_utc(e.start_date_time) >= today_end]
        upcoming_events_count = len(upcoming_events)

        # ── 4. Smart Reminders (Derived on-the-fly, NO autonomous DB writes) ──
        untracked_action_emails = [
            em for em in user_emails
            if em.ai_action_required and em.id not in task_email_ids
        ][:5]

        smart_reminders = []
        for em in untracked_action_emails:
            smart_reminders.append({
                "type": "untracked_action_email",
                "title": f"Action required on: {em.subject or '(No Subject)'}",
                "email_id": em.id,
                "sender": em.from_address,
                "received_at": em.received_at.isoformat() if em.received_at else None,
                "importance_score": em.ai_importance_score,
                "deadline": em.ai_deadline.isoformat() if em.ai_deadline else None,
            })

        for t in overdue_tasks_for_reminders:
            smart_reminders.append({
                "type": "overdue_task",
                "title": f"Overdue task: {t.title}",
                "task_id": t.id,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
            })

        # ── 5. Dashboard 2.0 Extended Sections ──
        from app.services.personalization_service import get_or_create_user_preferences
        pref = get_or_create_user_preferences(user.id)
        all_threads_data = get_threads_for_user(
            user.id, all_msgs=user_emails, per_page=100, user_email=user.email
        )
        all_threads = all_threads_data.get("threads", [])
        stale_threads_list = [t for t in all_threads if t.get("status") == "STALE"]
        waiting_threads = [t for t in all_threads if t.get("status") == "WAITING_FOR_OTHER"]
        follow_ups_list = get_follow_up_recommendations(
            user.id, waiting_threads=waiting_threads, emails=user_emails, pref=pref
        )
        all_contacts = get_all_contacts_for_user(
            user.id, emails=user_emails, user_email=user.email, pref=pref
        )

        inbox_health = {
            "total_unread": unread_count,
            "high_priority": high_priority_count,
            "needs_action": ai_action_required,
            "waiting_for_reply": waiting_for_count,
            "stale_threads": len(stale_threads_list),
            "upcoming_deadlines": upcoming_deadline_emails_count,
        }

        action_center = {
            "tasks_due_soon": upcoming_deadlines_data[:5],
            "emails_requiring_response": [em.to_dict() for em in untracked_action_emails[:5]],
            "follow_ups": follow_ups_list[:5],
            "upcoming_events": [e.to_dict() for e in upcoming_events[:5]],
        }

        sorted_by_activity = sorted(all_contacts, key=lambda c: c.get("last_contact") or "", reverse=True)
        sorted_by_importance = sorted(all_contacts, key=lambda c: c.get("importance_score", 0), reverse=True)
        awaiting_response_contacts = [c for c in all_contacts if c.get("open_actions_count", 0) > 0]

        people = {
            "most_active_contacts": sorted_by_activity[:5],
            "important_contacts": sorted_by_importance[:5],
            "awaiting_response_contacts": awaiting_response_contacts[:5],
            "total_contacts": len(all_contacts),
        }

        # ── 6. AI Queue Activity (Consolidated query) ──
        job_stats = (
            db.session.query(
                func.count(case((AIAnalysisJob.status == AIAnalysisJob.STATUS_PENDING, 1))).label("queued"),
                func.count(case((AIAnalysisJob.status == AIAnalysisJob.STATUS_PROCESSING, 1))).label("processing"),
                func.count(case((AIAnalysisJob.status == AIAnalysisJob.STATUS_COMPLETED, 1))).label("completed"),
                func.count(case((AIAnalysisJob.status == AIAnalysisJob.STATUS_FAILED, 1))).label("failed"),
            )
            .filter(AIAnalysisJob.user_id == user.id)
            .one()
        )

        completed_jobs = int(job_stats.completed or 0)
        queued_jobs = int(job_stats.queued or 0)
        processing_jobs = int(job_stats.processing or 0)
        failed_jobs = int(job_stats.failed or 0)

        ai_activity = {
            "analyzed": completed_jobs or ai_analyzed,
            "pending": queued_jobs + processing_jobs,
            "failed": failed_jobs,
            "queued": queued_jobs,
        }

        return jsonify({
            "total_emails": total_emails,
            "by_category": by_category,
            "by_priority": by_priority,
            "by_sentiment": by_sentiment,
            "pending_reviews": pending_reviews,
            "auto_replies_sent": auto_replies_sent,
            "tasks": {
                "total": t_total,
                "pending": t_pending,
                "in_progress": t_in_progress,
                "completed": t_completed,
                "cancelled": t_cancelled,
                "overdue": t_overdue,
                "due_today": t_due_today,
                "upcoming_deadlines": upcoming_deadlines_data,
            },
            "calendar": {
                "today_events_count": len(today_events),
                "upcoming_events_count": len(upcoming_events),
                "today_events": [e.to_dict() for e in today_events],
                "upcoming_events": [e.to_dict() for e in upcoming_events[:10]],
            },
            "ai": {
                "analyzed": ai_analyzed,
                "pending": ai_pending,
                "action_required": ai_action_required,
                "waiting_for_count": waiting_for_count,
            },
            "priority_distribution": priority_distribution,
            "smart_reminders": smart_reminders,
            "inbox_health": inbox_health,
            "action_center": action_center,
            "people": people,
            "ai_activity": ai_activity,
        }), 200

    except Exception as exc:
        current_app.logger.error("Error computing dashboard stats: %s", exc)
        return jsonify({"error": "Failed to compute statistics."}), 500
