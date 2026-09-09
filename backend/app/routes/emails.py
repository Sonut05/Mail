"""
Email routes — CRUD, sync from Gmail, approve / discard replies.
"""

from __future__ import annotations

import email.utils
from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import Blueprint, jsonify, request, session, current_app
from sqlalchemy import or_, and_, func

from app.extensions import db
from app.models import User, EmailMessage, Entity, Task, CalendarEvent, Reminder, AIAnalysisJob
from app.services.encryption import decrypt_token
from app.services.gmail_service import (
    get_gmail_service,
    list_recent_emails,
    fetch_email,
    send_reply,
)
from app.services.ai_service import (
    analyze_email,
    analyze_email_intelligence,
    MAX_RETRIES,
    start_background_email_analysis,
)
from app.services.job_queue_service import (
    enqueue_ai_job,
    claim_next_ai_job,
    process_claimed_job,
)

emails_bp = Blueprint("emails", __name__, url_prefix="/api/emails")


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _get_current_user() -> Optional[User]:
    """Retrieve the authenticated user from the session."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def _require_auth():
    """Return (user, None) or (None, error_response)."""
    user = _get_current_user()
    if not user:
        return None, (jsonify({"error": "Authentication required."}), 401)
    return user, None


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

@emails_bp.route("", methods=["GET"])
def list_emails():
    """List all processed emails for the current user.

    Query params (all optional):
        category: Filter by category.
        priority: Filter by priority.
        needs_human_review: Filter by review status ("true" / "false").
        page: Page number (default 1).
        per_page: Items per page (default 20).

    Returns:
        200 with paginated list of emails.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        query = EmailMessage.query.filter_by(user_id=user.id)

        # Apply optional filters
        category = request.args.get("category")
        if category:
            query = query.filter(EmailMessage.category == category)

        priority = request.args.get("priority")
        if priority:
            query = query.filter(EmailMessage.priority == priority)

        needs_review = request.args.get("needs_human_review")
        if needs_review is not None:
            query = query.filter(
                EmailMessage.needs_human_review == (needs_review.lower() == "true")
            )

        # Ordering & pagination
        query = query.order_by(EmailMessage.received_at.desc())
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            "emails": [e.to_dict() for e in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
            "per_page": pagination.per_page,
        }), 200

    except Exception as exc:
        current_app.logger.error("Error listing emails: %s", exc)
        return jsonify({"error": "Failed to list emails."}), 500


@emails_bp.route("/smart-inbox", methods=["GET"])
def get_smart_inbox():
    """Derive personalized Smart Inbox views for the authenticated user with explainable ranking.

    Sections:
    - needs_action: ai_action_required == True
    - due_soon: valid deadline within next 48 hours
    - urgent: ai_importance_score >= 81 OR ai_priority == 'urgent'
    - waiting_for: validated waiting_for object exists
    - important_people: emails from designated important senders or high engagement
    - recently_important: high personalized score received within last 72 hours
    - low_priority: promotional, newsletters, or low importance
    - newsletters: newsletter or promotion category
    - fyi: low/no-action informational messages
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        from app.services.personalization_service import (
            get_or_create_user_preferences,
            get_user_signals_map,
            calculate_personalized_score,
        )

        pref = get_or_create_user_preferences(user.id)
        signals_map = get_user_signals_map(user.id)

        now = datetime.now(timezone.utc)
        in_48h = now + timedelta(hours=48)
        past_72h = now - timedelta(hours=72)

        base_query = EmailMessage.query.filter(EmailMessage.user_id == user.id)

        selected_view = request.args.get("view", "all").lower().strip()
        limit = min(request.args.get("limit", 50, type=int), 100)

        # Pre-filter queries
        needs_action_q = base_query.filter(EmailMessage.ai_action_required == True)
        due_soon_q = base_query.filter(
            EmailMessage.ai_deadline.isnot(None),
            EmailMessage.ai_deadline <= in_48h,
            EmailMessage.ai_deadline >= now - timedelta(days=2)
        )
        urgent_q = base_query.filter(
            or_(
                EmailMessage.ai_importance_score >= 81,
                EmailMessage.ai_priority == "urgent"
            )
        )
        waiting_for_q = base_query.filter(
            EmailMessage.ai_waiting_for.isnot(None),
            EmailMessage.ai_waiting_for != ""
        )
        newsletters_q = base_query.filter(
            or_(
                EmailMessage.ai_category.in_(["newsletter", "promotion"]),
                EmailMessage.category.in_(["newsletter", "promotion", "spam"])
            )
        )
        fyi_q = base_query.filter(
            EmailMessage.ai_action_required == False,
            or_(
                EmailMessage.ai_priority.in_(["low", "medium"]),
                EmailMessage.ai_priority.is_(None)
            ),
            or_(
                EmailMessage.ai_category.is_(None),
                ~EmailMessage.ai_category.in_(["newsletter", "promotion"])
            )
        )

        important_senders_list = pref.get_important_senders_list()
        if important_senders_list:
            sender_conds = [EmailMessage.from_address.ilike(f"%{s}%") for s in important_senders_list]
            important_people_q = base_query.filter(or_(*sender_conds))
        else:
            important_people_q = base_query.filter(EmailMessage.ai_importance_score >= 75)

        recently_important_q = base_query.filter(
            EmailMessage.received_at >= past_72h,
            or_(
                EmailMessage.ai_importance_score >= 65,
                EmailMessage.ai_priority.in_(["high", "urgent"]),
                EmailMessage.ai_action_required == True
            )
        )

        low_priority_q = base_query.filter(
            or_(
                EmailMessage.ai_importance_score <= 35,
                EmailMessage.ai_category.in_(["newsletter", "promotion", "spam"]),
                EmailMessage.category.in_(["newsletter", "promotion", "spam"])
            )
        )

        counts = {
            "needs_action": needs_action_q.count(),
            "due_soon": due_soon_q.count(),
            "urgent": urgent_q.count(),
            "waiting_for": waiting_for_q.count(),
            "important_people": important_people_q.count(),
            "recently_important": recently_important_q.count(),
            "low_priority": low_priority_q.count(),
            "newsletters": newsletters_q.count(),
            "fyi": fyi_q.count(),
            "total": base_query.count(),
        }

        def _enrich_email(em: EmailMessage) -> dict:
            score, reasons = calculate_personalized_score(em, pref, signals_map, now=now)
            d = em.to_dict()
            d["personalized_score"] = score
            d["personalized_reasons"] = reasons
            return d

        mapping = {
            "needs_action": needs_action_q,
            "due_soon": due_soon_q,
            "urgent": urgent_q,
            "waiting_for": waiting_for_q,
            "important_people": important_people_q,
            "recently_important": recently_important_q,
            "low_priority": low_priority_q,
            "newsletters": newsletters_q,
            "fyi": fyi_q,
        }

        if selected_view in mapping:
            raw_items = mapping[selected_view].order_by(EmailMessage.received_at.desc()).limit(limit).all()
            enriched = [_enrich_email(e) for e in raw_items]
            # Rank view items by personalized_score descending
            enriched.sort(key=lambda x: x.get("personalized_score", 0), reverse=True)
            return jsonify({
                "view": selected_view,
                "count": len(enriched),
                "total": counts.get(selected_view, len(enriched)),
                "emails": enriched,
                "counts": counts,
            }), 200

        # "all" view: return all categorized views enriched
        return jsonify({
            "counts": counts,
            "views": {
                "needs_action": [_enrich_email(e) for e in needs_action_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "due_soon": [_enrich_email(e) for e in due_soon_q.order_by(EmailMessage.ai_deadline.asc()).limit(limit).all()],
                "urgent": [_enrich_email(e) for e in urgent_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "waiting_for": [_enrich_email(e) for e in waiting_for_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "important_people": [_enrich_email(e) for e in important_people_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "recently_important": [_enrich_email(e) for e in recently_important_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "low_priority": [_enrich_email(e) for e in low_priority_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "newsletters": [_enrich_email(e) for e in newsletters_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
                "fyi": [_enrich_email(e) for e in fyi_q.order_by(EmailMessage.received_at.desc()).limit(limit).all()],
            }
        }), 200

    except Exception as exc:
        current_app.logger.error("Error generating Smart Inbox: %s", exc)
        return jsonify({"error": "Failed to fetch Smart Inbox."}), 500


@emails_bp.route("/search", methods=["GET"])
def search_emails():
    """Advanced search across emails with AST query parsing and parameterized filtering.

    Supports combinations of:
    - q: free text search and syntax: from:john priority:high after:2026-09-01 action:true has:attachment
    - explicit query params: sender, recipient, subject, category, priority, action_required, date_from, date_to
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        from app.services.search_service import execute_advanced_search

        q = request.args.get("q", "").strip()
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 20, type=int), 100)

        explicit_filters = {
            "sender": request.args.get("sender"),
            "recipient": request.args.get("recipient"),
            "subject": request.args.get("subject"),
            "category": request.args.get("category"),
            "priority": request.args.get("priority"),
            "action": request.args.get("action_required"),
            "date_from": request.args.get("date_from"),
            "date_to": request.args.get("date_to"),
            "has": request.args.get("has"),
            "importance": request.args.get("importance"),
            "status": request.args.get("status"),
        }

        result = execute_advanced_search(
            user_id=user.id,
            query_str=q,
            explicit_filters=explicit_filters,
            page=page,
            per_page=per_page,
        )
        return jsonify(result), 200

    except Exception as exc:
        current_app.logger.error("Error searching emails for %s: %s", user.id, exc)
        return jsonify({"error": "Search failed."}), 500

    except Exception as exc:
        current_app.logger.error("Error searching emails: %s", exc)
        return jsonify({"error": "Search failed."}), 500


@emails_bp.route("/contacts/insights", methods=["GET"])
def get_contact_insights():
    """Derive contact intelligence from user's email metadata without Google Contacts permissions."""
    user, err = _require_auth()
    if err:
        return err

    try:
        emails = (
            EmailMessage.query.filter(EmailMessage.user_id == user.id)
            .order_by(EmailMessage.received_at.desc())
            .all()
        )

        contacts_map = {}

        for em in emails:
            raw_sender = em.from_address or ""
            if not raw_sender:
                continue

            parsed_name, parsed_email = email.utils.parseaddr(raw_sender)
            contact_key = parsed_email.lower().strip() if parsed_email else raw_sender.lower().strip()
            display_name = parsed_name or contact_key

            if contact_key not in contacts_map:
                contacts_map[contact_key] = {
                    "email": contact_key,
                    "name": display_name,
                    "total_emails": 0,
                    "action_required_count": 0,
                    "waiting_for_count": 0,
                    "last_activity": em.received_at.isoformat() if em.received_at else None,
                }

            contacts_map[contact_key]["total_emails"] += 1
            if em.ai_action_required:
                contacts_map[contact_key]["action_required_count"] += 1
            if em.ai_waiting_for:
                contacts_map[contact_key]["waiting_for_count"] += 1

        insights_list = sorted(
            contacts_map.values(),
            key=lambda c: c["total_emails"],
            reverse=True
        )

        return jsonify({
            "contacts": insights_list,
            "total_contacts": len(insights_list),
        }), 200

    except Exception as exc:
        current_app.logger.error("Error deriving contact insights: %s", exc)
        return jsonify({"error": "Failed to derive contact insights."}), 500


@emails_bp.route("/analyze", methods=["POST"])
def analyze_emails_batch():
    """Batch analyze emails for the authenticated user.

    Body options:
        email_ids: list of email IDs (max 20)
        limit: int, default 20 (max 20)
        force: bool, if True re-analyzes completed emails

    Returns:
        200 with summary of batch analysis.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        data = request.get_json(silent=True) or {}
        email_ids = data.get("email_ids")
        force = bool(data.get("force", False))

        max_batch = 20
        if email_ids is not None:
            if not isinstance(email_ids, list):
                email_ids = []
            elif len(email_ids) > max_batch:
                return jsonify({"error": f"Maximum batch size is {max_batch} emails per request."}), 400

        if data.get("limit") is not None:
            try:
                if int(data.get("limit")) > max_batch:
                    return jsonify({"error": f"Maximum batch size is {max_batch} emails per request."}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid limit parameter."}), 400

        emails_to_process = []

        if email_ids and isinstance(email_ids, list):
            # De-duplicate while preserving order
            seen_ids = set()
            unique_ids = []
            for eid in email_ids:
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    unique_ids.append(eid)
            target_ids = unique_ids[:max_batch]
            query = EmailMessage.query.filter(
                EmailMessage.id.in_(target_ids),
                EmailMessage.user_id == user.id
            )
            if not force:
                query = query.filter(EmailMessage.ai_status != "completed")
            emails_to_process = query.all()
        else:
            limit = min(int(data.get("limit", 20)), max_batch)
            query = EmailMessage.query.filter(
                EmailMessage.user_id == user.id
            )
            if not force:
                query = query.filter(EmailMessage.ai_status != "completed")
            emails_to_process = query.order_by(EmailMessage.received_at.desc()).limit(limit).all()

        is_eager = current_app.config.get("AI_JOB_ALWAYS_EAGER", False) or (
            current_app.config.get("TESTING") and not current_app.config.get("AI_JOB_ASYNC_TESTING")
        )

        results = []
        queued_count = 0
        completed_count = 0
        failed_count = 0

        for email in emails_to_process:
            job, enqueue_status = enqueue_ai_job(email.id, user.id, force=force)
            if enqueue_status in ("queued", "already_queued"):
                queued_count += 1

            if is_eager:
                claim = claim_next_ai_job(worker_id="eager-batch-worker")
                if claim:
                    res = process_claimed_job(
                        claim["job_id"],
                        worker_id=claim["worker_id"],
                        lease_token=claim["lease_token"],
                        app=current_app._get_current_object(),
                    )
                    db.session.refresh(email)
                    if email.ai_status == "completed":
                        completed_count += 1
                        results.append({
                            "email_id": email.id,
                            "success": True,
                            "ai_status": "completed",
                            "summary": email.ai_summary,
                            "category": email.ai_category,
                            "priority": email.ai_priority,
                            "importance_score": email.ai_importance_score,
                        })
                    else:
                        failed_count += 1
                        results.append({
                            "email_id": email.id,
                            "success": False,
                            "ai_status": "failed",
                            "error": email.ai_last_error or "AI analysis failed",
                        })
            else:
                results.append({
                    "email_id": email.id,
                    "job_id": job.id if job else None,
                    "status": enqueue_status,
                    "ai_status": email.ai_status,
                })

        total_requested = len(email_ids) if (email_ids and isinstance(email_ids, list)) else len(emails_to_process)
        skipped_count = max(0, total_requested - len(emails_to_process)) if not force else 0

        return jsonify({
            "success": True,
            "requested": total_requested,
            "processed": len(results),
            "analyzed_count": len(results),
            "queued_count": queued_count,
            "completed": completed_count if is_eager else 0,
            "successful_count": completed_count if is_eager else queued_count,
            "failed": failed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "results": results,
        }), 200

    except Exception as exc:
        current_app.logger.error("Error in batch email analysis: %s", exc)
        return jsonify({"error": f"Batch analysis failed: {str(exc)}"}), 500



@emails_bp.route("/<string:email_id>", methods=["GET"])
def get_email(email_id: str):
    """Get a single email with all related entities, tasks, events, and reminders."""
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(
            id=email_id, user_id=user.id
        ).first()

        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        return jsonify({"email": email_msg.to_dict(include_relations=True)}), 200

    except Exception as exc:
        current_app.logger.error("Error fetching email %s: %s", email_id, exc)
        return jsonify({"error": "Failed to fetch email."}), 500


@emails_bp.route("/<string:email_id>/retry", methods=["POST"])
def retry_single_email_analysis(email_id: str):
    """Retry AI analysis for an email up to MAX_RETRIES (3)."""
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(id=email_id).first()
        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        if email_msg.user_id != user.id:
            if not (email_msg.connected_account and email_msg.connected_account.user_id == user.id):
                return jsonify({"error": "Access denied. You do not own this email."}), 403

        if (email_msg.ai_retry_count or 0) >= MAX_RETRIES:
            return jsonify({
                "error": f"Maximum AI retries ({MAX_RETRIES}) reached. Cannot retry further.",
                "retry_count": email_msg.ai_retry_count,
                "ai_status": email_msg.ai_status,
                "email_id": email_id
            }), 400

        if email_msg.ai_status == "processing":
            return jsonify({
                "error": "Analysis already in progress for this email.",
                "ai_status": "processing",
                "email_id": email_id
            }), 409

        result = analyze_email_intelligence(email_msg, is_retry=True)
        if not result.get("success"):
            return jsonify({
                "success": False,
                "email_id": email_msg.id,
                "ai_status": email_msg.ai_status,
                "retry_count": email_msg.ai_retry_count,
                "error": result.get("error", "AI analysis retry failed."),
                "email": email_msg.to_dict(include_relations=True),
            }), 502

        return jsonify({
            "success": True,
            "email_id": email_msg.id,
            "ai_status": email_msg.ai_status,
            "retry_count": email_msg.ai_retry_count,
            "summary": email_msg.ai_summary,
            "category": email_msg.ai_category,
            "priority": email_msg.ai_priority,
            "sentiment": email_msg.ai_sentiment,
            "action_required": email_msg.ai_action_required,
            "deadline": email_msg.ai_deadline.isoformat() if email_msg.ai_deadline else None,
            "importance_score": email_msg.ai_importance_score,
            "email": email_msg.to_dict(include_relations=True),
        }), 200

    except RuntimeError as r_err:
        return jsonify({"error": str(r_err)}), 400
    except Exception as exc:
        current_app.logger.error("Error retrying email %s: %s", email_id, exc)
        return jsonify({"error": "Failed to retry email analysis."}), 500


@emails_bp.route("/<string:email_id>/analyze", methods=["POST"])
def analyze_single_email(email_id: str):
    """Analyze a single email with AI and store intelligence results.

    In production: enqueues to durable AIAnalysisJob table and returns immediately.
    In eager testing mode: claims and processes synchronously.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(id=email_id).first()
        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        # Strict user isolation check
        if email_msg.user_id != user.id:
            if not (email_msg.connected_account and email_msg.connected_account.user_id == user.id):
                return jsonify({"error": "Access denied. You do not own this email."}), 403

        # Check retry limit
        if (email_msg.ai_retry_count or 0) >= MAX_RETRIES and email_msg.ai_status == "failed":
            return jsonify({
                "error": f"Maximum AI retries ({MAX_RETRIES}) reached. Cannot re-analyze.",
                "retry_count": email_msg.ai_retry_count,
                "ai_status": email_msg.ai_status,
                "email_id": email_id
            }), 400

        # Concurrency protection
        if email_msg.ai_status == "processing":
            return jsonify({
                "error": "Analysis already in progress for this email.",
                "ai_status": "processing",
                "email_id": email_id
            }), 409

        data = request.get_json(silent=True) or {}
        force = bool(data.get("force", False))

        job, enqueue_status = enqueue_ai_job(email_msg.id, user.id, force=force)
        if enqueue_status == "already_processing":
            return jsonify({
                "error": "Analysis already in progress for this email.",
                "ai_status": "processing",
                "email_id": email_id
            }), 409

        # Check if synchronous eager processing is requested (test compatibility)
        is_eager = current_app.config.get("AI_JOB_ALWAYS_EAGER", False) or (
            current_app.config.get("TESTING") and not current_app.config.get("AI_JOB_ASYNC_TESTING")
        )

        if is_eager:
            claim = claim_next_ai_job(worker_id="eager-worker")
            if claim:
                process_claimed_job(
                    claim["job_id"],
                    worker_id=claim["worker_id"],
                    lease_token=claim["lease_token"],
                    app=current_app._get_current_object(),
                )
            db.session.refresh(email_msg)
            if email_msg.ai_status == "failed":
                return jsonify({
                    "success": False,
                    "email_id": email_msg.id,
                    "ai_status": email_msg.ai_status,
                    "retry_count": email_msg.ai_retry_count,
                    "error": email_msg.ai_last_error or "AI analysis failed.",
                    "email": email_msg.to_dict(include_relations=True),
                }), 502

            tasks_list = []
            if email_msg.ai_suggested_tasks:
                try:
                    import json
                    tasks_list = json.loads(email_msg.ai_suggested_tasks)
                except Exception:
                    pass
            event_obj = None
            if email_msg.ai_suggested_event:
                try:
                    import json
                    event_obj = json.loads(email_msg.ai_suggested_event)
                except Exception:
                    pass
            key_points_list = []
            if email_msg.ai_key_points:
                try:
                    import json
                    key_points_list = json.loads(email_msg.ai_key_points)
                except Exception:
                    pass
            waiting_for_obj = None
            if email_msg.ai_waiting_for:
                try:
                    import json
                    waiting_for_obj = json.loads(email_msg.ai_waiting_for)
                except Exception:
                    pass
            reasons_list = []
            if email_msg.ai_reasons:
                try:
                    import json
                    reasons_list = json.loads(email_msg.ai_reasons)
                except Exception:
                    pass

            return jsonify({
                "success": True,
                "email_id": email_msg.id,
                "job_id": job.id if job else None,
                "ai_status": email_msg.ai_status,
                "summary": email_msg.ai_summary,
                "category": email_msg.ai_category,
                "priority": email_msg.ai_priority,
                "sentiment": email_msg.ai_sentiment,
                "action_required": email_msg.ai_action_required,
                "deadline": email_msg.ai_deadline.isoformat() if email_msg.ai_deadline else None,
                "suggested_tasks": tasks_list,
                "suggested_event": event_obj,
                "entities": [e.to_dict() for e in email_msg.entities] if email_msg.entities else [],
                "importance_score": email_msg.ai_importance_score,
                "confidence_score": email_msg.ai_confidence_score,
                "key_points": key_points_list,
                "waiting_for": waiting_for_obj,
                "next_action": email_msg.ai_next_action,
                "reasons": reasons_list,
                "email": email_msg.to_dict(include_relations=True),
            }), 200

        # Production asynchronous / non-blocking response
        return jsonify({
            "success": True,
            "status": "queued" if enqueue_status == "queued" else "already_queued",
            "job_id": job.id if job else None,
            "email_id": email_msg.id,
            "ai_status": email_msg.ai_status,
            "message": "AI analysis queued for background processing."
        }), 200

    except RuntimeError as r_err:
        return jsonify({"error": str(r_err)}), 400
    except Exception as exc:
        current_app.logger.error("Error analyzing email %s: %s", email_id, exc)
        return jsonify({
            "success": False,
            "email_id": email_id,
            "ai_status": "failed",
            "error": str(exc),
        }), 500



@emails_bp.route("/<string:email_id>/approve", methods=["POST"])
def approve_reply(email_id: str):
    """Approve and send the AI-drafted reply for an email.

    Args:
        email_id: UUID of the email whose draft reply should be sent.

    Returns:
        200 with the sent message ID, or an error.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(
            id=email_id, user_id=user.id
        ).first()

        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        if not email_msg.reply_draft:
            return jsonify({"error": "No draft reply to approve."}), 400

        if email_msg.auto_reply_sent:
            return jsonify({"error": "Reply has already been sent."}), 400

        # Build Gmail service
        access_token = decrypt_token(user.encrypted_access_token)
        service = get_gmail_service(access_token)

        sent_id = send_reply(
            service=service,
            to=email_msg.from_address,
            subject=email_msg.subject or "",
            body=email_msg.reply_draft,
            thread_id=email_msg.thread_id or "",
            message_id=email_msg.message_id,
        )

        email_msg.auto_reply_sent = True
        email_msg.sent_reply_id = sent_id
        email_msg.needs_human_review = False
        email_msg.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({
            "message": "Reply sent successfully.",
            "sent_reply_id": sent_id,
        }), 200

    except Exception as exc:
        current_app.logger.error("Error approving reply for %s: %s", email_id, exc)
        db.session.rollback()
        return jsonify({"error": f"Failed to send reply: {str(exc)}"}), 500


@emails_bp.route("/<string:email_id>/discard", methods=["POST"])
def discard_reply(email_id: str):
    """Discard the AI-drafted reply.

    Args:
        email_id: UUID of the email.

    Returns:
        200 on success, or an error.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(
            id=email_id, user_id=user.id
        ).first()

        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        email_msg.reply_draft = None
        email_msg.auto_reply_required = False
        email_msg.needs_human_review = False
        email_msg.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"message": "Draft reply discarded."}), 200

    except Exception as exc:
        current_app.logger.error("Error discarding reply for %s: %s", email_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to discard reply."}), 500


@emails_bp.route("/<string:email_id>/read", methods=["POST"])
def mark_email_read(email_id: str):
    """Mark an email as read (reviewed)."""
    user, err = _require_auth()
    if err:
        return err

    try:
        email_msg = EmailMessage.query.filter_by(
            id=email_id, user_id=user.id
        ).first()

        if not email_msg:
            return jsonify({"error": "Email not found."}), 404

        email_msg.needs_human_review = False
        email_msg.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return jsonify({"message": "Email marked as read."}), 200

    except Exception as exc:
        current_app.logger.error("Error marking email as read %s: %s", email_id, exc)
        db.session.rollback()
        return jsonify({"error": "Failed to mark email as read."}), 500


@emails_bp.route("/sync", methods=["POST"])
def sync_emails():
    """Manually trigger an email sync from Gmail.

    Fetches recent emails, analyses each with Gemini, and stores results.

    Returns:
        200 with count of newly processed emails.
    """
    user, err = _require_auth()
    if err:
        return err

    try:
        access_token = decrypt_token(user.encrypted_access_token)
        
        # Simulated sync for mock testing sessions
        if access_token == "mock-access-token":
            # Wipe stale mock data to guarantee clean state
            user_emails = EmailMessage.query.filter_by(user_id=user.id).all()
            user_email_ids = [e.id for e in user_emails]
            if user_email_ids:
                Task.query.filter(Task.email_id.in_(user_email_ids)).delete(synchronize_session=False)
                CalendarEvent.query.filter(CalendarEvent.email_id.in_(user_email_ids)).delete(synchronize_session=False)
            EmailMessage.query.filter_by(user_id=user.id).delete(synchronize_session=False)
            db.session.commit()

            mock_data = [
                {
                    "message_id": "mock_msg_1",
                    "subject": "Google Campus Recruitment 2026 Registration",
                    "from_address": "campus-recruitment@google.com",
                    "to_address": user.email,
                    "body_text": (
                        "Hello Candidate,\n\nThank you for your interest in software engineering roles at Google! "
                        "We have opened registration for the Google Campus Recruitment 2026 cohort. "
                        "To proceed with your application, please complete the registration form using our Recopilot autopilot interface. "
                        "Please fill in your graduation year, expected salary, and submit your resume.\n\n"
                        "Access the registration form here: https://forms.gle/google-campus-recruitment-2026\n\n"
                        "Best regards,\nGoogle University Relations"
                    ),
                    "category": "Recruitment",
                    "priority": "High",
                    "sentiment": "Positive",
                    "summary": "Invitation to register for Google Campus Recruitment 2026. Needs candidate profile inputs.",
                    "auto_reply_required": False,
                    "needs_human_review": True,
                    "confidence": 0.95,
                    "spam_score": 1,
                    "tasks": [
                        {"title": "Fill out Google Campus Registration form", "priority": "high", "due_date": "2026-07-20"}
                    ]
                },
                {
                    "message_id": "mock_msg_2",
                    "subject": "Urgent: Project MailMind AI Design Review",
                    "from_address": "s.jenkins@innovatetech.com",
                    "to_address": user.email,
                    "body_text": (
                        "Hi Developer,\n\nWe need to review the frontend styling components for the MailMind project "
                        "before the sprint planning meeting. Can we set up a quick 15-minute call today at 3:00 PM UTC?\n\n"
                        "Let me know if that works for you.\n\nSarah Jenkins\nDesign Lead"
                    ),
                    "category": "Meeting",
                    "priority": "High",
                    "sentiment": "Neutral",
                    "summary": "Sarah Jenkins requests a design review call today at 3:00 PM UTC for Project MailMind AI.",
                    "auto_reply_required": True,
                    "reply_draft": "Hi Sarah, yes, 3:00 PM UTC works perfectly for the MailMind design review call. Talk then!",
                    "needs_human_review": True,
                    "confidence": 0.88,
                    "spam_score": 0,
                    "tasks": [
                        {"title": "Review Sarah's styling feedback", "priority": "medium", "due_date": "2026-07-15"}
                    ],
                    "calendar_event": {
                        "title": "Project MailMind AI Design Review",
                        "start_time": "2026-07-14T15:00:00Z",
                        "end_time": "2026-07-14T15:30:00Z",
                        "location": "Google Meet",
                        "description": "Quick review of frontend styling components before sprint planning."
                    }
                },
                {
                    "message_id": "mock_msg_3",
                    "subject": "Invoices and Billing Updates Q2",
                    "from_address": "finance@innovatetech.com",
                    "to_address": user.email,
                    "body_text": (
                        "Hello team,\n\nPlease find attached the invoices and billing summary for Q2 operations. "
                        "All departments must submit their receipts by Friday.\n\nRegards,\nFinance Team"
                    ),
                    "category": "Finance",
                    "priority": "Medium",
                    "sentiment": "Neutral",
                    "summary": "Q2 invoice and billing summary updates. Receipts must be submitted by Friday.",
                    "auto_reply_required": False,
                    "needs_human_review": False,
                    "confidence": 0.90,
                    "spam_score": 0,
                    "tasks": [
                        {"title": "Submit Q2 department receipts", "priority": "medium", "due_date": "2026-07-18"}
                    ]
                }
            ]

            new_count = 0
            for item in mock_data:
                # Add EmailMessage
                email_msg = EmailMessage(
                    user_id=user.id,
                    message_id=item["message_id"],
                    subject=item["subject"],
                    body_text=item["body_text"],
                    from_address=item["from_address"],
                    to_address=item["to_address"],
                    received_at=datetime.now(timezone.utc),
                    category=item["category"],
                    priority=item["priority"],
                    sentiment=item["sentiment"],
                    summary=item["summary"],
                    auto_reply_required=item["auto_reply_required"],
                    needs_human_review=item["needs_human_review"],
                    confidence=item["confidence"],
                    spam_score=item["spam_score"],
                    reply_draft=item.get("reply_draft")
                )
                db.session.add(email_msg)
                db.session.flush()
                
                # Add Tasks
                for t in item.get("tasks", []):
                    due_val = t.get("due_date")
                    try:
                        due_dt = datetime.fromisoformat(due_val.replace("Z", "+00:00")) if "T" in str(due_val) else datetime.strptime(due_val, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    except Exception:
                        due_dt = datetime.now(timezone.utc)
                    task = Task(
                        email_id=email_msg.id,
                        task_title=t["title"],
                        priority=t["priority"],
                        status="pending",
                        due_date=due_dt
                    )
                    db.session.add(task)
                
                # Add CalendarEvent
                if "calendar_event" in item:
                    ce = item["calendar_event"]
                    start_val = ce.get("start_time", "")
                    end_val = ce.get("end_time", "")
                    try:
                        start_dt = datetime.fromisoformat(start_val.replace("Z", "+00:00"))
                    except Exception:
                        start_dt = datetime.now(timezone.utc)
                    try:
                        end_dt = datetime.fromisoformat(end_val.replace("Z", "+00:00"))
                    except Exception:
                        end_dt = None
                    evt = CalendarEvent(
                        email_id=email_msg.id,
                        title=ce["title"],
                        start_date_time=start_dt,
                        end_date_time=end_dt,
                        location=ce["location"],
                        description=ce["description"]
                    )
                    db.session.add(evt)

                new_count += 1
            
            db.session.commit()
            return jsonify({"new_count": new_count, "message": f"Successfully generated {new_count} mock emails."}), 200

        service = get_gmail_service(access_token)
        max_results = request.args.get("max_results", 10, type=int)
        message_stubs = list_recent_emails(service, max_results=max_results)

        new_count = 0
        errors = []

        for stub in message_stubs:
            gmail_id = stub["id"]

            existing_msg = EmailMessage.query.filter_by(message_id=gmail_id).first()
            is_stale_fallback = (
                existing_msg and (
                    not existing_msg.summary or 
                    "AI analysis temporarily unavailable" in existing_msg.summary or 
                    "AI summary failed to load" in existing_msg.summary
                )
            )

            if existing_msg and not is_stale_fallback:
                continue
            try:
                raw = fetch_email(service, gmail_id)
                now_iso = datetime.now(timezone.utc).isoformat()

                try:
                    analysis = analyze_email(
                        subject=raw["subject"],
                        body=raw["body_text"],
                        sender=raw["from_address"],
                        current_datetime=now_iso,
                    )
                except Exception as ai_exc:
                    current_app.logger.warning(
                        "Gemini analysis failed for message %s (using smart local fallback): %s", gmail_id, ai_exc
                    )
                    content_lower = f"{raw.get('subject', '')} {raw.get('body_text', '')}".lower()
                    
                    category = "General"
                    priority = "Medium"
                    sentiment = "Neutral"
                    summary = raw.get("body_text", "")[:120].strip() + "..." if raw.get("body_text") else "No summary available."
                    auto_reply_required = False
                    needs_human_review = True
                    confidence = 0.7
                    
                    if any(kw in content_lower for kw in ["urgent", "asap", "deadline", "immediate", "action required", "important"]):
                        priority = "High"
                    
                    if any(kw in content_lower for kw in ["invoice", "bill", "finance", "receipt", "payment", "subscription"]):
                        category = "Finance"
                        if "due" in content_lower or "pay" in content_lower or "invoice" in content_lower:
                            priority = "High"
                        summary = f"Billing & Finance: payment updates for {raw.get('subject', 'Invoice')}"
                    elif any(kw in content_lower for kw in ["meeting", "call", "zoom", "invite", "schedule", "calendar", "meet"]):
                        category = "Meeting"
                        priority = "High"
                        summary = f"Scheduling & Meetings: invitation for {raw.get('subject', 'Call')}"
                    elif any(kw in content_lower for kw in ["recruitment", "job", "apply", "resume", "position", "hiring", "candidate"]):
                        category = "Recruitment"
                        priority = "High"
                        summary = f"Recruitment: Candidate application or registration request for {raw.get('subject', 'Job')}"
                    elif any(kw in content_lower for kw in ["error", "fail", "broken", "issue", "bug", "support", "help"]):
                        category = "Support"
                        summary = f"Support Inquiry: User reports issue with {raw.get('subject', 'Product')}"

                    # Local fallback tasks and calendar event extraction (Strict explicit date/deadline filtering)
                    tasks_list = []
                    calendar_evt = None
                    import re
                    from datetime import timedelta

                    raw_subject = raw.get("subject", "")
                    raw_body = raw.get("body_text", "")
                    full_content = f"{raw_subject} {raw_body}"
                    content_lower_full = full_content.lower()

                    # Explicit date & deadline keywords
                    date_keywords = [
                        "deadline", "last date", "due date", "due by", "expires", "expiry", 
                        "scheduled for", "meeting on", "meeting at", "call at", "call on", 
                        "interview on", "webinar on", "event on", "submission date", "schedule"
                    ]

                    has_explicit_date_keyword = any(kw in content_lower_full for kw in date_keywords)

                    if has_explicit_date_keyword:
                        # Extract explicit date patterns (e.g. 15th Aug 2026, 2026-08-15, Aug 15, 15/08/2026)
                        date_match = re.search(
                            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?|\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                            full_content, re.IGNORECASE
                        )

                        # Extract explicit time patterns (e.g. 5:00 PM, 10:30am, 14:00)
                        time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)', full_content)

                        event_dt = None
                        if date_match:
                            raw_date = date_match.group(1)
                            clean_date = re.sub(r'(st|nd|rd|th)', '', raw_date, flags=re.IGNORECASE).strip()
                            for fmt in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%b %d", "%B %d", "%Y-%m-%d", "%d/%m/%Y"):
                                try:
                                    dt = datetime.strptime(clean_date, fmt)
                                    if dt.year == 1900:
                                        dt = dt.replace(year=datetime.now(timezone.utc).year)
                                    event_dt = dt.replace(tzinfo=timezone.utc)
                                    break
                                except ValueError:
                                    pass

                        if not event_dt:
                            event_dt = datetime.now(timezone.utc) + timedelta(days=1)

                        if any(k in content_lower_full for k in ["deadline", "last date", "due date", "due by", "expiry"]):
                            event_title = f"Last Date: {raw_subject}"
                            event_desc = f"Important Deadline extracted from email.\nSubject: {raw_subject}"
                        elif "interview" in content_lower_full:
                            event_title = f"Interview: {raw_subject}"
                            event_desc = f"Interview schedule extracted from email.\nSubject: {raw_subject}"
                        else:
                            event_title = f"Meeting: {raw_subject}"
                            event_desc = f"Meeting schedule extracted from email.\nSubject: {raw_subject}"

                        # Extract exact meeting URL from body text
                        meeting_url_match = re.search(
                            r'https?://(?:meet\.google\.com/[a-z0-9-]+|[a-z0-9-]+\.zoom\.us/j/[^\s<>"]+|teams\.microsoft\.com/l/meetup-join/[^\s<>"]+|[a-z0-9-]+\.webex\.com/[^\s<>"]+)',
                            full_content, re.IGNORECASE
                        )
                        meeting_url = meeting_url_match.group(0) if meeting_url_match else None
                        if not meeting_url:
                            # Generic URL matching fallback if explicit meeting keywords are present
                            generic_url_match = re.search(r'https?://[^\s<>"]+', full_content)
                            if generic_url_match and any(w in content_lower_full for w in ["join", "meeting", "zoom", "teams", "conference"]):
                                meeting_url = generic_url_match.group(0)

                        calendar_evt = {
                            "title": event_title,
                            "description": event_desc,
                            "start_date_time": event_dt.isoformat(),
                            "end_date_time": (event_dt + timedelta(hours=1)).isoformat(),
                            "location": "Google Meet / Online" if meeting_url else "Email Notification",
                            "meeting_link": meeting_url,
                            "organizer": raw.get("from_address", "System Notification"),
                            "attendees": f"{raw.get('from_address')}, {user.email}"
                        }

                    # Create tasks for actionable recruitment/finance/urgent items
                    if category == "Recruitment":
                        due_date = datetime.now(timezone.utc) + timedelta(days=3)
                        tasks_list.append({
                            "task_title": f"Follow up on application: {raw_subject}",
                            "description": "Complete registration form or resume review.",
                            "due_date": due_date.date().isoformat(),
                            "priority": "High",
                            "assignee": user.email
                        })
                    elif category == "Finance":
                        due_date = datetime.now(timezone.utc) + timedelta(days=5)
                        tasks_list.append({
                            "task_title": f"Process invoice/receipt: {raw_subject}",
                            "description": "Verify billing details and file receipt.",
                            "due_date": due_date.date().isoformat(),
                            "priority": "Medium",
                            "assignee": user.email
                        })
                    elif priority == "High":
                        due_date = datetime.now(timezone.utc) + timedelta(days=2)
                        tasks_list.append({
                            "task_title": f"Urgent action: {raw_subject}",
                            "description": "Urgent item extracted from email body text.",
                            "due_date": due_date.date().isoformat(),
                            "priority": "High",
                            "assignee": user.email
                        })

                    analysis = {
                        "category": category,
                        "priority": priority,
                        "sentiment": sentiment,
                        "summary": summary,
                        "auto_reply_required": auto_reply_required,
                        "needs_human_review": needs_human_review,
                        "confidence": confidence,
                        "spam_score": 0,
                        "reply_draft": None,
                        "entities": [],
                        "tasks": tasks_list,
                        "calendar_event": calendar_evt,
                        "reminders": []
                    }

                if existing_msg:
                    email_msg = existing_msg
                    email_msg.subject = raw["subject"]
                    email_msg.body_text = raw["body_text"]
                    email_msg.category = analysis.get("category")
                    email_msg.priority = analysis.get("priority")
                    email_msg.sentiment = analysis.get("sentiment")
                    email_msg.summary = analysis.get("summary")
                    email_msg.auto_reply_required = analysis.get("auto_reply_required", False)
                    email_msg.needs_human_review = analysis.get("needs_human_review", False)
                    email_msg.confidence = analysis.get("confidence")
                    email_msg.spam_score = analysis.get("spam_score")
                    email_msg.reply_draft = analysis.get("reply_draft")
                    email_msg.updated_at = datetime.now(timezone.utc)
                else:
                    email_msg = EmailMessage(
                        user_id=user.id,
                        message_id=raw["message_id"],
                        thread_id=raw["thread_id"],
                        subject=raw["subject"],
                        body_text=raw["body_text"],
                        from_address=raw["from_address"],
                        to_address=raw["to_address"],
                        received_at=raw["received_at"],
                        category=analysis.get("category"),
                        priority=analysis.get("priority"),
                        sentiment=analysis.get("sentiment"),
                        summary=analysis.get("summary"),
                        auto_reply_required=analysis.get("auto_reply_required", False),
                        needs_human_review=analysis.get("needs_human_review", False),
                        confidence=analysis.get("confidence"),
                        spam_score=analysis.get("spam_score"),
                        reply_draft=analysis.get("reply_draft"),
                    )
                    db.session.add(email_msg)
                    db.session.flush()

                # Entities
                for ent in analysis.get("entities", []):
                    db.session.add(Entity(
                        email_id=email_msg.id,
                        type=ent.get("type", "Unknown"),
                        value=ent.get("value", ""),
                    ))

                # Tasks
                for task_data in analysis.get("tasks", []):
                    due = task_data.get("due_date")
                    due_dt = datetime.fromisoformat(due) if due else None
                    db.session.add(Task(
                        email_id=email_msg.id,
                        task_title=task_data.get("task_title", "Untitled Task"),
                        description=task_data.get("description"),
                        due_date=due_dt,
                        priority=task_data.get("priority", "Medium"),
                        assignee=task_data.get("assignee"),
                    ))

                # Calendar event
                cal = analysis.get("calendar_event")
                if cal and isinstance(cal, dict) and cal.get("title"):
                    start = cal.get("start_date_time")
                    start_dt = datetime.fromisoformat(start) if start else datetime.now(timezone.utc)
                    end = cal.get("end_date_time")
                    end_dt = datetime.fromisoformat(end) if end else None
                    attendees_val = cal.get("attendees")
                    if isinstance(attendees_val, (list, dict)):
                        import json
                        attendees_val = json.dumps(attendees_val)

                    db.session.add(CalendarEvent(
                        email_id=email_msg.id,
                        title=cal.get("title", "Untitled Event"),
                        description=cal.get("description"),
                        start_date_time=start_dt,
                        end_date_time=end_dt,
                        timezone=cal.get("timezone", "UTC"),
                        location=cal.get("location"),
                        meeting_link=cal.get("meeting_link"),
                        organizer=cal.get("organizer"),
                        attendees=attendees_val,
                    ))

                # Reminders
                for rem in analysis.get("reminders", []):
                    evt = rem.get("event_date_time")
                    evt_dt = datetime.fromisoformat(evt) if evt else datetime.now(timezone.utc)
                    rdt = rem.get("reminder_date_time")
                    rdt_dt = datetime.fromisoformat(rdt) if rdt else evt_dt
                    db.session.add(Reminder(
                        email_id=email_msg.id,
                        title=rem.get("title", "Reminder"),
                        description=rem.get("description"),
                        reminder_type=rem.get("reminder_type", "Custom"),
                        event_date_time=evt_dt,
                        reminder_date_time=rdt_dt,
                        priority=rem.get("priority", "Medium"),
                    ))

                db.session.commit()
                new_count += 1

            except Exception as inner_exc:
                current_app.logger.warning(
                    "Failed to process message %s: %s", gmail_id, inner_exc
                )
                db.session.rollback()
                errors.append({"message_id": gmail_id, "error": str(inner_exc)})

        return jsonify({
            "message": f"Sync complete. {new_count} new email(s) processed.",
            "new_count": new_count,
            "errors": errors,
        }), 200

    except Exception as exc:
        current_app.logger.error("Email sync error: %s", exc)
        db.session.rollback()
        return jsonify({"error": f"Sync failed: {str(exc)}"}), 500


@emails_bp.route("/generate-reply", methods=["POST"])
def generate_reply_standalone():
    """Generate a reply to an email body without a connected mailbox."""
    try:
        data = request.get_json() or {}
        email_body = data.get("email_body", "").strip()
        tone = data.get("tone", "Professional").strip()
        custom_instructions = data.get("custom_instructions", "").strip()

        if not email_body:
            return jsonify({"error": "Email body is required."}), 400

        from app.services.ai_service import generate_standalone_reply
        reply_draft = generate_standalone_reply(
            email_body=email_body,
            tone=tone,
            custom_instructions=custom_instructions if custom_instructions else None
        )

        return jsonify({"reply_draft": reply_draft}), 200

    except Exception as exc:
        current_app.logger.error("Standalone reply generation failed: %s", exc)
        return jsonify({"error": f"Failed to generate reply: {str(exc)}"}), 500
