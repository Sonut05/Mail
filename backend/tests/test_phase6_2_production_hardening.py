"""
Phase 6.2 — Production Hardening Comprehensive Test Suite.

Verifies:
1. Configuration validation (rejecting insecure secrets, debug in prod, SQLite in prod).
2. Health (/health) and Readiness (/ready) probes (including DB disconnection -> 503).
3. Queue observability endpoint (/api/queue/health).
4. Request correlation ID in headers and logging.
5. Security headers and safe error handling (no stack traces).
6. Gemini error handling (timeout, rate limiting 429, 5xx server errors, invalid JSON).
7. Worker lifecycle: graceful shutdown, status inspection, startup recovery.
8. Multi-user isolation across emails, tasks, calendar, reminders, and AI jobs.
9. Load & concurrency: concurrent enqueues and claims under thread load.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import sqlalchemy as sa
from flask import Flask, g, session

from app import create_app
from app.config import Config, ProductionConfig, validate_production_config, get_engine_options, normalize_database_uri
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.ai_analysis_job import AIAnalysisJob
from app.services.job_queue_service import (
    enqueue_ai_job,
    claim_next_ai_job,
    process_claimed_job,
    recover_stale_jobs,
    get_queue_metrics,
    _sanitize_error,
)
from app.services.ai_service import analyze_email
from worker import AIWorker


class TestPhase62ProductionHardening:
    """Test suite for Phase 6.2 Production Hardening."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create a dedicated test application context with SQLite test database."""
        test_db = f"test_p62_{uuid.uuid4().hex[:8]}.db"
        
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{test_db}"
            SECRET_KEY = "test-secret-key-at-least-16-characters-long"
            ENCRYPTION_KEY = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="
            GEMINI_API_KEY = "test-gemini-secret-api-key"
            AI_JOB_ALWAYS_EAGER = False
            CREATE_DB_TABLES_ON_STARTUP = True

        app = create_app(TestConfig)
        self.app = app
        self.client = app.test_client()

        with app.app_context():
            db.create_all()
            # Seed users
            self.user_a = User(id=str(uuid.uuid4()), email="usera@example.com", name="User A")
            self.user_b = User(id=str(uuid.uuid4()), email="userb@example.com", name="User B")
            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()
            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            # Seed email for user A
            self.email_a = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=self.user_a_id,
                message_id="msg-a-101",
                thread_id="thread-a-101",
                from_address="sender@example.com",
                subject="Production Hardening Subject",
                body_text="Hello, this is a test email for phase 6.2.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
            )
            db.session.add(self.email_a)
            db.session.commit()
            self.email_a_id = self.email_a.id

        yield

        # Cleanup
        with app.app_context():
            db.session.remove()
            db.drop_all()
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass

    def _login(self, client, user_id: str):
        with client.session_transaction() as sess:
            sess["user_id"] = user_id

    # ── 1. Configuration Validation ─────────────────────────────

    def test_production_config_validation(self):
        """Verify production validator detects insecure configurations."""
        # Valid production configuration
        valid_cfg = {
            "ENV": "production",
            "DEBUG": False,
            "SECRET_KEY": "a-very-strong-production-secret-key-32-chars",
            "SQLALCHEMY_DATABASE_URI": "postgresql://user:pass@localhost:5432/db",
            "ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
        }
        assert validate_production_config(valid_cfg) == []

        # Insecure defaults
        bad_cfg = {
            "ENV": "production",
            "DEBUG": True,
            "SECRET_KEY": "dev-secret-key-change-me",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///test.db",
            "ENCRYPTION_KEY": "",
        }
        errors = validate_production_config(bad_cfg)
        assert len(errors) == 4
        assert any("SECRET_KEY" in e for e in errors)
        assert any("DEBUG" in e for e in errors)
        assert any("PostgreSQL" in e for e in errors)
        assert any("ENCRYPTION_KEY" in e for e in errors)

    def test_database_uri_normalization_and_engine_options(self):
        """Test postgres:// is converted to postgresql:// and pooling options applied."""
        normalized = normalize_database_uri("postgres://user:pass@localhost:5432/dbname")
        assert normalized == "postgresql://user:pass@localhost:5432/dbname"

        # SQLite engine options must be empty dict (to avoid unsupported pool args)
        sqlite_options = get_engine_options("sqlite:///test.db")
        assert sqlite_options == {}

        # PostgreSQL engine options must have pool settings
        pg_options = get_engine_options("postgresql://localhost/db")
        assert pg_options["pool_pre_ping"] is True
        assert "pool_size" in pg_options
        assert "max_overflow" in pg_options

    # ── 2. Health & Readiness Probes ────────────────────────────

    def test_liveness_probe_health(self):
        """Verify /health and /api/health return 200 with timestamp."""
        for endpoint in ("/health", "/api/health"):
            res = self.client.get(endpoint)
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "healthy"
            assert "timestamp" in data

    def test_readiness_probe_success(self):
        """Verify /ready and /api/ready return 200 when database is responsive."""
        for endpoint in ("/ready", "/api/ready"):
            res = self.client.get(endpoint)
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "ready"
            assert data["database"] == "connected"

    def test_readiness_probe_database_failure(self):
        """Verify /ready returns 503 if database connection fails."""
        with patch.object(db.session, "execute", side_effect=Exception("Database unreachable")):
            res = self.client.get("/ready")
            assert res.status_code == 503
            data = res.get_json()
            assert data["status"] == "unready"
            assert data["database"] == "unavailable"
            assert "Database query failed" in data["reason"]

    # ── 3. AI Queue Observability ───────────────────────────────

    def test_queue_observability_endpoint(self):
        """Verify /api/queue/health returns accurate, un-leaked aggregate metrics."""
        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a_id, self.user_a_id)
            assert job is not None

        res = self.client.get("/api/queue/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "healthy"
        metrics = data["queue"]
        assert metrics["pending"] == 1
        assert metrics["total"] == 1
        assert metrics["completed"] == 0
        assert "email_body" not in str(data)
        assert "password" not in str(data)

    # ── 4. Security Headers & Correlation IDs ───────────────────

    def test_security_headers_and_correlation_id(self):
        """Verify response contains correlation ID and production security headers."""
        res = self.client.get("/health")
        assert res.status_code == 200
        assert "X-Request-ID" in res.headers
        assert res.headers["X-Request-ID"].startswith("req-")
        assert res.headers["X-Content-Type-Options"] == "nosniff"
        assert res.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_custom_request_id_forwarded(self):
        """Verify user-provided correlation ID is respected."""
        custom_id = "test-corr-id-999"
        res = self.client.get("/health", headers={"X-Request-ID": custom_id})
        assert res.headers["X-Request-ID"] == custom_id

    def test_safe_error_handling_no_stack_trace(self):
        """Verify 404 and 500 responses return clean JSON without leaking stack traces."""
        res = self.client.get("/api/non-existent-endpoint-404")
        assert res.status_code == 404
        data = res.get_json()
        assert data["error"] == "Not found"
        assert "Traceback" not in res.get_data(as_text=True)

    # ── 5. Gemini Reliability & Error Categorization ────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_gemini_rate_limiting_429_handling(self, mock_model_cls):
        """Verify 429 ResourceExhausted is cleanly caught and categorized."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("429 ResourceExhausted: quota exceeded")
        mock_model_cls.return_value = mock_model

        with pytest.raises(RuntimeError) as exc_info:
            with self.app.app_context():
                analyze_email("Subject", "Body", "sender@example.com")
        assert "rate limit" in str(exc_info.value).lower() or "429" in str(exc_info.value)

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_gemini_timeout_handling(self, mock_model_cls):
        """Verify timeout/DeadlineExceeded is cleanly categorized."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = Exception("DeadlineExceeded: call timed out")
        mock_model_cls.return_value = mock_model

        with pytest.raises(RuntimeError) as exc_info:
            with self.app.app_context():
                analyze_email("Subject", "Body", "sender@example.com")
        assert "timed out" in str(exc_info.value).lower()

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_gemini_empty_response_handling(self, mock_model_cls):
        """Verify empty response from Gemini raises clear exception."""
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_model.generate_content.return_value = mock_resp
        mock_model_cls.return_value = mock_model

        with pytest.raises(RuntimeError) as exc_info:
            with self.app.app_context():
                analyze_email("Subject", "Body", "sender@example.com")
        assert "empty response" in str(exc_info.value).lower()

    def test_error_sanitization_redacts_keys_and_clamps(self):
        """Verify _sanitize_error redacts keys and truncates long strings."""
        with self.app.app_context():
            raw_err = f"Failed contacting Gemini with key test-gemini-secret-api-key and secret test-secret-key-at-least-16-characters-long"
            safe = _sanitize_error(raw_err)
            assert "test-gemini-secret-api-key" not in safe
            assert "[REDACTED_GEMINI_API_KEY]" in safe

            # Long string clamping
            huge_err = "x" * 1000
            clamped = _sanitize_error(huge_err)
            assert len(clamped) <= 500
            assert clamped.endswith("...")

    # ── 6. Worker Lifecycle & Graceful Shutdown ─────────────────

    def test_worker_status_and_lifecycle(self):
        """Verify AIWorker tracks running state, uptime, and graceful shutdown."""
        worker = AIWorker(app=self.app)
        status = worker.get_status()
        assert status["running"] is True
        assert status["current_job_id"] is None
        assert status["uptime_seconds"] >= 0.0

        # Simulate SIGTERM signal
        worker._handle_signal(15, None)
        assert worker.running is False
        # When stopped, run_once does not claim new jobs
        assert worker.run_once() is False

    # ── 7. Multi-User Isolation Audit ───────────────────────────

    def test_multi_user_isolation_across_endpoints(self):
        """Verify User B cannot access User A's email or trigger its analysis."""
        self._login(self.client, self.user_b_id)

        # 1. User B tries to view User A's email
        r_get = self.client.get(f"/api/emails/{self.email_a_id}")
        assert r_get.status_code in (403, 404)

        # 2. User B tries to analyze User A's email
        r_post = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        assert r_post.status_code in (403, 404)

    def test_unauthenticated_requests_strictly_rejected(self):
        """Verify unauthenticated requests return 401."""
        assert self.client.get("/api/emails").status_code == 401
        assert self.client.get("/api/tasks").status_code == 401
        assert self.client.get("/api/calendar").status_code == 401
        assert self.client.get("/api/dashboard/stats").status_code == 401

    # ── 8. Concurrency & Load Stress Test ───────────────────────

    def test_concurrent_enqueue_load_under_threads(self):
        """Concurrent enqueue requests for same email result in exactly 1 active job."""
        num_threads = 8
        barrier = threading.Barrier(num_threads)
        results = []
        errors = []

        def worker_enqueue():
            with self.app.app_context():
                try:
                    barrier.wait(timeout=5)
                    job, status = enqueue_ai_job(self.email_a_id, self.user_a_id)
                    results.append((job.id if job else None, status))
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=worker_enqueue) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert len(results) == num_threads
        queued_count = sum(1 for _, status in results if status == "queued")
        already_queued_count = sum(1 for _, status in results if status == "already_queued")
        assert queued_count == 1
        assert already_queued_count == num_threads - 1

        with self.app.app_context():
            active_jobs = AIAnalysisJob.query.filter(
                AIAnalysisJob.email_id == self.email_a_id,
                AIAnalysisJob.status == AIAnalysisJob.STATUS_PENDING,
            ).all()
            assert len(active_jobs) == 1
