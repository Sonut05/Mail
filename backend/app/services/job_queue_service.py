"""
Job Queue Service — Durable PostgreSQL/SQLAlchemy Background AI Job Management.

Provides:
- Atomic enqueueing with database-level partial unique constraint protection
- Atomic claiming with SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL
- Stale worker lease protection and heartbeat management
- Concurrency-safe stale job recovery
- Exponential backoff retry logic strictly capped at MAX_ATTEMPTS (3)
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from flask import current_app

from app.extensions import db
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.email_message import EmailMessage
from app.services.ai_service import analyze_email_intelligence

logger = logging.getLogger("mailmild.worker")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [AIWorker] %(message)s")


def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-aware in UTC for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sanitize_error(error: Any) -> str:
    """Strip any credentials or internal tokens from error messages before persisting."""
    msg = str(error) if error else "Unknown error"
    # Redact any Gemini API key, encryption key, or secret key if present
    try:
        cfg = current_app.config
        for secret_name in ("GEMINI_API_KEY", "ENCRYPTION_KEY", "SECRET_KEY", "GOOGLE_CLIENT_SECRET"):
            secret_val = cfg.get(secret_name) or os.environ.get(secret_name)
            if secret_val and len(secret_val) >= 8 and secret_val in msg:
                msg = msg.replace(secret_val, f"[REDACTED_{secret_name}]")
    except RuntimeError:
        # Outside Flask application context
        for env_key in ("GEMINI_API_KEY", "ENCRYPTION_KEY", "SECRET_KEY", "GOOGLE_CLIENT_SECRET"):
            val = os.environ.get(env_key)
            if val and len(val) >= 8 and val in msg:
                msg = msg.replace(val, f"[REDACTED_{env_key}]")

    import re
    # Redact Google OAuth access tokens (ya29...)
    msg = re.sub(r"ya29\.[a-zA-Z0-9_\-]+", "[REDACTED_OAUTH_TOKEN]", msg)
    # Redact Bearer tokens
    msg = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED_TOKEN]", msg, flags=re.IGNORECASE)

    # Limit message length to avoid persisting unbounded email bodies in error column
    if len(msg) > 500:
        msg = msg[:497] + "..."
    return msg


def enqueue_ai_job(
    email_id: str,
    user_id: str,
    force: bool = False,
    max_attempts: int = 3,
) -> tuple[Optional[AIAnalysisJob], str]:
    """Enqueue an email for background AI analysis.

    Returns:
        (job, status_str) where status_str is one of:
        - "queued": New job successfully created
        - "already_queued": Active job (pending) already exists
        - "already_processing": Active job (processing) already exists
        - "already_completed": Email was already completed and force is False
        - "rejected": Ownership mismatch or invalid email
    """
    email_msg = db.session.get(EmailMessage, email_id)
    if not email_msg:
        return None, "rejected"

    # Strict multi-user ownership check
    if email_msg.user_id != user_id:
        return None, "rejected"

    # Privacy control: check if user has disabled AI analysis
    from app.models import UserPreference
    pref = UserPreference.query.filter_by(user_id=user_id).first()
    if pref and not pref.ai_analysis_enabled and not force:
        return None, "disabled"

    # Check for active job (pending or processing)
    active_job = (
        AIAnalysisJob.query.filter(
            AIAnalysisJob.email_id == email_id,
            AIAnalysisJob.status.in_([AIAnalysisJob.STATUS_PENDING, AIAnalysisJob.STATUS_PROCESSING]),
        )
        .order_by(AIAnalysisJob.created_at.desc())
        .first()
    )

    if active_job:
        if active_job.status == AIAnalysisJob.STATUS_PENDING:
            now = datetime.now(timezone.utc)
            avail = _to_utc(active_job.available_at)
            if avail and avail > now:
                active_job.available_at = now
                db.session.commit()
        status_name = "already_processing" if active_job.status == AIAnalysisJob.STATUS_PROCESSING else "already_queued"
        return active_job, status_name

    now = datetime.now(timezone.utc)
    job = AIAnalysisJob(
        id=str(uuid.uuid4()),
        email_id=email_id,
        user_id=user_id,
        status=AIAnalysisJob.STATUS_PENDING,
        attempts=0,
        max_attempts=max_attempts,
        available_at=now,
        created_at=now,
        updated_at=now,
    )

    try:
        db.session.add(job)
        if email_msg.ai_status != "completed" or force:
            email_msg.ai_status = "pending"
        db.session.commit()
        return job, "queued"
    except IntegrityError:
        # Database partial unique index (uq_active_ai_job_per_email) caught concurrent enqueue race
        db.session.rollback()
        concurrent_job = (
            AIAnalysisJob.query.filter(
                AIAnalysisJob.email_id == email_id,
                AIAnalysisJob.status.in_([AIAnalysisJob.STATUS_PENDING, AIAnalysisJob.STATUS_PROCESSING]),
            )
            .order_by(AIAnalysisJob.created_at.desc())
            .first()
        )
        return concurrent_job, "already_queued"


def claim_next_ai_job(worker_id: str, stale_timeout_seconds: int = 300) -> Optional[dict[str, Any]]:
    """Atomically claim the next eligible pending job.

    Uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL.
    Commits immediately after setting status to 'processing' and recording lock lease.
    Does NOT hold open the database transaction while processing AI.

    Returns a dict with claimed job metadata or None.
    """
    now = datetime.now(timezone.utc)
    bind = db.session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    query = (
        db.session.query(AIAnalysisJob)
        .filter(
            AIAnalysisJob.status == AIAnalysisJob.STATUS_PENDING,
            AIAnalysisJob.available_at <= now,
        )
        .order_by(AIAnalysisJob.available_at.asc())
    )

    if is_postgres:
        # Row-level lock with skip locked prevents any second worker from blocking or double-claiming
        query = query.with_for_update(skip_locked=True)

    job = query.first()
    if not job:
        db.session.rollback()
        return None

    # Generate a unique lease token to guarantee stale worker protection
    lease_token = str(uuid.uuid4())
    job.status = AIAnalysisJob.STATUS_PROCESSING
    job.locked_at = now
    job.locked_by = worker_id
    job.lease_token = lease_token
    job.heartbeat_at = now
    job.attempts = (job.attempts or 0) + 1
    job.updated_at = now

    # Synchronize email status
    email_msg = db.session.get(EmailMessage, job.email_id)
    if email_msg:
        email_msg.ai_status = "processing"

    job_id = job.id
    email_id = job.email_id
    user_id = job.user_id
    attempts = job.attempts
    max_attempts = job.max_attempts

    # Commit immediately to release row lock before long-running AI execution
    db.session.commit()

    return {
        "job_id": job_id,
        "email_id": email_id,
        "user_id": user_id,
        "worker_id": worker_id,
        "lease_token": lease_token,
        "attempts": attempts,
        "max_attempts": max_attempts,
    }


def process_claimed_job(
    job_id: str,
    worker_id: str,
    lease_token: Optional[str] = None,
    app: Any = None,
) -> dict[str, Any]:
    """Execute AI analysis for a claimed job outside the DB lock.

    Guarantees:
    - Lease validation prevents stale recovered workers from overwriting newer state.
    - AI execution occurs outside any open DB transaction.
    - Status updates and retries are committed atomically upon completion.
    """
    job = db.session.get(AIAnalysisJob, job_id)
    if not job:
        return {"success": False, "error": "Job not found"}

    # Lease ownership protection check
    if job.status != AIAnalysisJob.STATUS_PROCESSING or job.locked_by != worker_id:
        logger.warning(
            "Worker %s attempted to process job %s but does not hold active lock (status=%s, locked_by=%s)",
            worker_id, job_id, job.status, job.locked_by
        )
        return {"success": False, "error": "Worker does not hold lease"}

    if lease_token and job.lease_token and job.lease_token != lease_token:
        logger.warning(
            "Worker %s lease token %s expired for job %s (current lease: %s)",
            worker_id, lease_token, job_id, job.lease_token
        )
        return {"success": False, "error": "Lease token mismatch"}

    email_msg = db.session.get(EmailMessage, job.email_id)
    if not email_msg:
        job.status = AIAnalysisJob.STATUS_FAILED
        job.last_error = "Associated email message not found"
        db.session.commit()
        return {"success": False, "error": "Email not found"}

    # Execute Gemini intelligence analysis
    ai_result = analyze_email_intelligence(email_msg)

    # Re-verify lease before writing final results
    job = db.session.get(AIAnalysisJob, job_id)
    if not job or job.locked_by != worker_id or (lease_token and job.lease_token != lease_token):
        logger.warning("Lease lost during AI execution for job %s. Discarding output.", job_id)
        db.session.rollback()
        return {"success": False, "error": "Lease expired during processing"}

    now = datetime.now(timezone.utc)

    if ai_result.get("success"):
        job.status = AIAnalysisJob.STATUS_COMPLETED
        job.completed_at = now
        job.locked_at = None
        job.locked_by = None
        job.lease_token = None
        job.last_error = None
        job.updated_at = now

        email_msg.ai_status = "completed"
        db.session.commit()

        return {
            "success": True,
            "job_id": job.id,
            "email_id": email_msg.id,
            "status": "completed",
            "attempts": job.attempts,
        }
    else:
        raw_error = ai_result.get("error", "AI analysis execution failed")
        safe_error = _sanitize_error(raw_error)

        job.last_error = safe_error
        email_msg.ai_last_error = safe_error
        email_msg.ai_retry_count = min(job.max_attempts, job.attempts)

        if job.attempts < job.max_attempts:
            # Exponential backoff: attempt 1 -> 5s, attempt 2 -> 15s
            backoff_delay = 5 * (2 ** (job.attempts - 1))
            job.status = AIAnalysisJob.STATUS_PENDING
            job.available_at = now + timedelta(seconds=backoff_delay)
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.updated_at = now

            email_msg.ai_status = "failed"
            db.session.commit()

            return {
                "success": False,
                "job_id": job.id,
                "status": "pending",
                "retry_scheduled": True,
                "attempts": job.attempts,
                "backoff_seconds": backoff_delay,
                "error": safe_error,
            }
        else:
            # Max attempts reached -> permanent failure
            job.status = AIAnalysisJob.STATUS_FAILED
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.updated_at = now

            email_msg.ai_status = "failed"
            db.session.commit()

            return {
                "success": False,
                "job_id": job.id,
                "status": "failed",
                "retry_scheduled": False,
                "attempts": job.attempts,
                "error": safe_error,
            }


def recover_stale_jobs(stale_timeout_seconds: int = 300) -> int:
    """Identify jobs stuck in 'processing' whose worker has timed out or crashed.

    If attempts < max_attempts: re-queues as 'pending' for another worker.
    If attempts >= max_attempts: marks as 'failed'.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_timeout_seconds)

    bind = db.session.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    query = db.session.query(AIAnalysisJob).filter(
        AIAnalysisJob.status == AIAnalysisJob.STATUS_PROCESSING,
        sa.or_(
            sa.and_(AIAnalysisJob.heartbeat_at.isnot(None), AIAnalysisJob.heartbeat_at < cutoff),
            sa.and_(AIAnalysisJob.heartbeat_at.is_(None), AIAnalysisJob.locked_at < cutoff),
        ),
    )

    if is_postgres:
        query = query.with_for_update(skip_locked=True)

    stale_jobs = query.all()
    recovered_count = 0

    for job in stale_jobs:
        email = db.session.get(EmailMessage, job.email_id)
        if job.attempts < job.max_attempts:
            job.status = AIAnalysisJob.STATUS_PENDING
            job.available_at = now
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.last_error = f"Recovered from stale worker lease (timeout={stale_timeout_seconds}s)"
            job.updated_at = now
            if email:
                email.ai_status = "pending"
        else:
            job.status = AIAnalysisJob.STATUS_FAILED
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.last_error = f"Stale job exceeded maximum attempts ({job.max_attempts})"
            job.updated_at = now
            if email:
                email.ai_status = "failed"
        recovered_count += 1

    if recovered_count > 0:
        db.session.commit()

    return recovered_count


def update_job_heartbeat(job_id: str, worker_id: str, lease_token: Optional[str] = None) -> bool:
    """Update heartbeat timestamp while processing long tasks."""
    job = db.session.get(AIAnalysisJob, job_id)
    if not job or job.status != AIAnalysisJob.STATUS_PROCESSING or job.locked_by != worker_id:
        return False
    if lease_token and job.lease_token != lease_token:
        return False

    job.heartbeat_at = datetime.now(timezone.utc)
    db.session.commit()
    return True


def get_queue_metrics(stale_timeout_seconds: int = 300) -> dict[str, Any]:
    """Calculate aggregate, safe queue metrics from AIAnalysisJob model.

    Guarantees:
    - Never returns email bodies, user identifiers, or credentials.
    - Accurately tracks pending, processing, completed, failed, cancelled, retries, and stale jobs.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=stale_timeout_seconds)

    # Status counts
    counts = dict(
        db.session.query(AIAnalysisJob.status, sa.func.count(AIAnalysisJob.id))
        .group_by(AIAnalysisJob.status)
        .all()
    )

    pending_count = counts.get(AIAnalysisJob.STATUS_PENDING, 0)
    processing_count = counts.get(AIAnalysisJob.STATUS_PROCESSING, 0)
    completed_count = counts.get(AIAnalysisJob.STATUS_COMPLETED, 0)
    failed_count = counts.get(AIAnalysisJob.STATUS_FAILED, 0)
    cancelled_count = counts.get(AIAnalysisJob.STATUS_CANCELLED, 0)
    total_count = sum(counts.values())

    # Stale jobs count
    stale_count = (
        db.session.query(sa.func.count(AIAnalysisJob.id))
        .filter(
            AIAnalysisJob.status == AIAnalysisJob.STATUS_PROCESSING,
            sa.or_(
                sa.and_(AIAnalysisJob.heartbeat_at.isnot(None), AIAnalysisJob.heartbeat_at < cutoff),
                sa.and_(AIAnalysisJob.heartbeat_at.is_(None), AIAnalysisJob.locked_at < cutoff),
            ),
        )
        .scalar()
        or 0
    )

    # Oldest pending job age
    oldest_pending = (
        db.session.query(AIAnalysisJob.created_at)
        .filter(AIAnalysisJob.status == AIAnalysisJob.STATUS_PENDING)
        .order_by(AIAnalysisJob.created_at.asc())
        .first()
    )
    oldest_pending_age_seconds = None
    if oldest_pending and oldest_pending[0]:
        oldest_dt = _to_utc(oldest_pending[0])
        if oldest_dt:
            oldest_pending_age_seconds = max(0.0, (now - oldest_dt).total_seconds())

    # Total retry count (sum of attempts - 1 where attempts > 1)
    retries_result = (
        db.session.query(
            sa.func.sum(sa.case((AIAnalysisJob.attempts > 1, AIAnalysisJob.attempts - 1), else_=0))
        ).scalar()
        or 0
    )

    return {
        "pending": pending_count,
        "processing": processing_count,
        "completed": completed_count,
        "failed": failed_count,
        "cancelled": cancelled_count,
        "total": total_count,
        "stale_jobs": stale_count,
        "oldest_pending_age_seconds": oldest_pending_age_seconds,
        "total_retries": int(retries_result),
        "failure_count": failed_count,
    }

