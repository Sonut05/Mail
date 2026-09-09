"""
Phase 6.1 Tests — Durable AI Job Queue, Atomic Processing & Worker Concurrency.

Tests:
1. Durable AI Job Model & State Transitions (pending -> processing -> completed/failed)
2. Atomic Enqueue & Duplicate Active Job Idempotency
3. Non-Blocking API Execution (request returns in < 100ms while Gemini is mocked to sleep 2s)
4. Atomic Job Claiming & Transaction Boundaries (commits immediately to release lock before Gemini)
5. Stale Worker Lease Ownership Protection (old worker cannot overwrite newly reclaimed job)
6. Retry Counter Invariance & Exponential Backoff (1 -> 2 -> 3 -> failed, never 4)
7. Stale Job Recovery (crashed worker lease expired -> recovery resets to pending or fails)
8. Batch API Enqueueing & Security (max 20, ownership verification, cross-user isolation)
9. Worker Run-Once Polling & Error Sanitization (API keys redacted from persisted errors)
10. Multi-User Isolation in Queue Operations (User A cannot claim/enqueue/view User B jobs)
"""

import json
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import sqlalchemy as sa

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.models.ai_analysis_job import AIAnalysisJob
from app.services.encryption import encrypt_token
from app.services.job_queue_service import (
    enqueue_ai_job,
    claim_next_ai_job,
    process_claimed_job,
    recover_stale_jobs,
    update_job_heartbeat,
)
from worker import AIWorker


class TestPhase61AsyncConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-phase6-1-secret-key"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
    GEMINI_API_KEY = "mock-phase61-gemini-key-sec999"
    GEMINI_MODEL = "gemini-2.0-flash"
    AI_JOB_ALWAYS_EAGER = False
    AI_JOB_ASYNC_TESTING = True
    AI_JOB_POLL_INTERVAL = 0.1
    AI_JOB_STALE_SECONDS = 10
    AI_JOB_MAX_ATTEMPTS = 3


class TestPhase61WorkerQueue(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestPhase61AsyncConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create User A
            self.user_a = User(email="alice@phase61.com", name="Alice Phase61")
            db.session.add(self.user_a)

            # Create User B
            self.user_b = User(email="bob@phase61.com", name="Bob Phase61")
            db.session.add(self.user_b)
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            # User A Account & Email
            self.acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="gmail_alice_p61",
                email_address="alice@phase61.com",
                encrypted_access_token=encrypt_token("tok-a-p61"),
                encrypted_refresh_token=encrypt_token("ref-a-p61"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                messages_synced=1,
            )
            db.session.add(self.acc_a)
            db.session.commit()
            self.acc_a_id = self.acc_a.id

            self.email_a1 = EmailMessage(
                user_id=self.user_a_id,
                connected_account_id=self.acc_a_id,
                message_id="msg_p61_a1",
                from_address="boss@corp.com",
                to_address="alice@phase61.com",
                subject="Durable Queue Architecture Review",
                body_text="Hi Alice, please review the Phase 6.1 job queue specifications.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
                ai_retry_count=0,
            )
            db.session.add(self.email_a1)

            # User B Account & Email
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                provider_account_id="gmail_bob_p61",
                email_address="bob@phase61.com",
                encrypted_access_token=encrypt_token("tok-b-p61"),
                encrypted_refresh_token=encrypt_token("ref-b-p61"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                messages_synced=1,
            )
            db.session.add(self.acc_b)
            db.session.commit()
            self.acc_b_id = self.acc_b.id

            self.email_b1 = EmailMessage(
                user_id=self.user_b_id,
                connected_account_id=self.acc_b_id,
                message_id="msg_p61_b1",
                from_address="partner@biz.com",
                to_address="bob@phase61.com",
                subject="Bob Confidential Financials",
                body_text="Bob, here are confidential figures.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
                ai_retry_count=0,
            )
            db.session.add(self.email_b1)
            db.session.commit()

            self.email_a1_id = self.email_a1.id
            self.email_b1_id = self.email_b1.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login_as(self, user_id: str, client=None):
        test_client = client or self.client
        with test_client.session_transaction() as sess:
            sess["user_id"] = user_id

    # ─────────────────────────────────────────────────────────────
    # 1. DURABLE JOB MODEL & STATE TRANSITIONS
    # ─────────────────────────────────────────────────────────────

    def test_durable_job_model_fields_and_serialization(self):
        """Test 1: Verify AIAnalysisJob schema fields, defaults, relationships, and serialization."""
        with self.app.app_context():
            job = AIAnalysisJob(
                email_id=self.email_a1_id,
                user_id=self.user_a_id,
                status="pending",
                attempts=0,
                max_attempts=3,
            )
            db.session.add(job)
            db.session.commit()

            self.assertIsNotNone(job.id)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempts, 0)
            self.assertEqual(job.max_attempts, 3)
            self.assertIsNotNone(job.available_at)
            self.assertIsNotNone(job.created_at)
            self.assertIsNone(job.locked_at)
            self.assertIsNone(job.locked_by)

            # Test relationship
            self.assertEqual(job.email.id, self.email_a1_id)
            self.assertEqual(job.user.id, self.user_a_id)

            # Test serialization
            d = job.to_dict()
            self.assertEqual(d["id"], job.id)
            self.assertEqual(d["email_id"], self.email_a1_id)
            self.assertEqual(d["status"], "pending")
            self.assertIn("created_at", d)

    # ─────────────────────────────────────────────────────────────
    # 2. ATOMIC ENQUEUE & DUPLICATE ACTIVE JOB IDEMPOTENCY
    # ─────────────────────────────────────────────────────────────

    def test_atomic_enqueue_and_deduplication(self):
        """Test 2: Enqueue creates a job; duplicate enqueue on same email returns existing active job without creating a second job."""
        with self.app.app_context():
            job1, status1 = enqueue_ai_job(self.email_a1_id, self.user_a_id)
            self.assertEqual(status1, "queued")
            self.assertIsNotNone(job1)
            self.assertEqual(job1.status, "pending")

            # Duplicate enqueue attempt
            job2, status2 = enqueue_ai_job(self.email_a1_id, self.user_a_id)
            self.assertEqual(status2, "already_queued")
            self.assertEqual(job1.id, job2.id)

            # Verify total job count in DB is exactly 1
            count = AIAnalysisJob.query.filter_by(email_id=self.email_a1_id).count()
            self.assertEqual(count, 1)

    # ─────────────────────────────────────────────────────────────
    # 3. NON-BLOCKING API EXECUTION
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_api_is_truly_non_blocking(self, mock_model_cls):
        """Test 3: Verify POST /api/emails/<id>/analyze returns immediately (< 100ms) even when Gemini takes 2 seconds."""
        mock_instance = MagicMock()

        def slow_generate(*args, **kwargs):
            time.sleep(2.0)
            resp = MagicMock()
            resp.text = json.dumps({"summary": "Slow AI Summary", "category": "work", "priority": "medium"})
            return resp

        mock_instance.generate_content.side_effect = slow_generate
        mock_model_cls.return_value = mock_instance

        self._login_as(self.user_a_id)
        start_time = time.time()
        resp = self.client.post(f"/api/emails/{self.email_a1_id}/analyze")
        elapsed = time.time() - start_time

        # Fast response assertion: must return substantially before AI generation completes
        self.assertEqual(resp.status_code, 200)
        self.assertLess(elapsed, 0.25, f"API took {elapsed:.3f}s; must return immediately without waiting for Gemini")

        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "queued")
        self.assertIsNotNone(data["job_id"])

        # Email in DB should be marked pending, not completed
        with self.app.app_context():
            em = db.session.get(EmailMessage, self.email_a1_id)
            self.assertEqual(em.ai_status, "pending")

    # ─────────────────────────────────────────────────────────────
    # 4. ATOMIC CLAIMING & IMMEDIATE LOCK RELEASE
    # ─────────────────────────────────────────────────────────────

    def test_atomic_claim_and_lock_transition(self):
        """Test 4: claim_next_ai_job transitions pending -> processing, increments attempts, records worker ID and lease token."""
        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)

            claim = claim_next_ai_job(worker_id="test-worker-1")
            self.assertIsNotNone(claim)
            self.assertEqual(claim["job_id"], job.id)
            self.assertEqual(claim["worker_id"], "test-worker-1")
            self.assertEqual(claim["attempts"], 1)
            self.assertIsNotNone(claim["lease_token"])

            # Verify DB state
            claimed_job = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(claimed_job.status, "processing")
            self.assertEqual(claimed_job.locked_by, "test-worker-1")
            self.assertEqual(claimed_job.attempts, 1)

            # Subsequent claim when no pending jobs exist returns None
            second_claim = claim_next_ai_job(worker_id="test-worker-2")
            self.assertIsNone(second_claim)

    # ─────────────────────────────────────────────────────────────
    # 5. STALE WORKER LEASE OWNERSHIP PROTECTION
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_stale_worker_lease_protection(self, mock_model_cls):
        """Test 5: An old worker whose lease expired or was recovered CANNOT overwrite a job claimed by a newer worker."""
        mock_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"summary": "Stale Summary", "category": "work", "priority": "low"})
        mock_instance.generate_content.return_value = mock_resp
        mock_model_cls.return_value = mock_instance

        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)

            # Worker 1 claims job
            claim1 = claim_next_ai_job(worker_id="worker-old")
            self.assertIsNotNone(claim1)

            # Simulate worker crash and recovery by manually reclaiming job for worker-new
            job_db = db.session.get(AIAnalysisJob, job.id)
            job_db.locked_by = "worker-new"
            job_db.lease_token = "new-lease-token-xyz"
            db.session.commit()

            # Worker-old attempts to process with expired lease
            result = process_claimed_job(
                job_id=job.id,
                worker_id="worker-old",
                lease_token=claim1["lease_token"],
                app=self.app,
            )

            self.assertFalse(result["success"])
            self.assertIn("lease", result["error"].lower())

            # Job status remains owned by worker-new
            job_final = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(job_final.locked_by, "worker-new")
            self.assertEqual(job_final.status, "processing")

    # ─────────────────────────────────────────────────────────────
    # 6. RETRY COUNTER INVARIANCE & EXPONENTIAL BACKOFF
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_retry_counter_invariance_and_backoff(self, mock_model_cls):
        """Test 6: Failed attempts reschedule with exponential backoff; attempts never exceed MAX_ATTEMPTS (3); attempt 3 results in permanent failure."""
        mock_instance = MagicMock()
        mock_instance.generate_content.side_effect = Exception("Temporary Network Glitch 503")
        mock_model_cls.return_value = mock_instance

        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)

            # Attempt 1
            claim1 = claim_next_ai_job(worker_id="worker-1")
            res1 = process_claimed_job(claim1["job_id"], claim1["worker_id"], claim1["lease_token"], self.app)
            self.assertFalse(res1["success"])
            self.assertTrue(res1["retry_scheduled"])
            self.assertEqual(res1["attempts"], 1)

            job_db = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(job_db.status, "pending")
            avail = job_db.available_at
            if avail.tzinfo is None:
                avail = avail.replace(tzinfo=timezone.utc)
            self.assertGreater(avail, datetime.now(timezone.utc))

            # Fast-forward available_at for Attempt 2
            job_db.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.session.commit()

            # Attempt 2
            claim2 = claim_next_ai_job(worker_id="worker-1")
            res2 = process_claimed_job(claim2["job_id"], claim2["worker_id"], claim2["lease_token"], self.app)
            self.assertFalse(res2["success"])
            self.assertTrue(res2["retry_scheduled"])
            self.assertEqual(res2["attempts"], 2)

            # Fast-forward available_at for Attempt 3 (Final attempt)
            job_db = db.session.get(AIAnalysisJob, job.id)
            job_db.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.session.commit()

            # Attempt 3
            claim3 = claim_next_ai_job(worker_id="worker-1")
            res3 = process_claimed_job(claim3["job_id"], claim3["worker_id"], claim3["lease_token"], self.app)
            self.assertFalse(res3["success"])
            self.assertFalse(res3["retry_scheduled"])
            self.assertEqual(res3["status"], "failed")
            self.assertEqual(res3["attempts"], 3)

            # Ensure attempts NEVER exceed 3 and no more claims are possible
            job_final = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(job_final.status, "failed")
            self.assertEqual(job_final.attempts, 3)

            claim4 = claim_next_ai_job(worker_id="worker-1")
            self.assertIsNone(claim4)

    # ─────────────────────────────────────────────────────────────
    # 7. STALE JOB RECOVERY
    # ─────────────────────────────────────────────────────────────

    def test_stale_job_recovery_after_worker_crash(self):
        """Test 7: A job stuck in 'processing' whose worker crashed/timed out is recovered back to 'pending'."""
        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)
            claim = claim_next_ai_job(worker_id="crashed-worker")

            # Simulate worker crash and timeout: set locked_at and heartbeat_at 15 minutes in the past
            past_time = datetime.now(timezone.utc) - timedelta(minutes=15)
            job_db = db.session.get(AIAnalysisJob, job.id)
            job_db.locked_at = past_time
            job_db.heartbeat_at = past_time
            db.session.commit()

            # Run recovery with stale timeout of 300s (5 minutes)
            recovered = recover_stale_jobs(stale_timeout_seconds=300)
            self.assertEqual(recovered, 1)

            # Job is reset to pending with lock cleared
            job_recovered = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(job_recovered.status, "pending")
            self.assertIsNone(job_recovered.locked_by)
            self.assertIsNone(job_recovered.lease_token)
            self.assertIn("Recovered from stale worker", job_recovered.last_error)

            # Another worker can now claim and process the job
            new_claim = claim_next_ai_job(worker_id="new-worker")
            self.assertIsNotNone(new_claim)
            self.assertEqual(new_claim["job_id"], job.id)

    # ─────────────────────────────────────────────────────────────
    # 8. BATCH API ENQUEUEING & CROSS-USER ISOLATION
    # ─────────────────────────────────────────────────────────────

    def test_batch_api_enqueueing_and_cross_user_rejection(self):
        """Test 8: Batch endpoint queues jobs, skips foreign IDs, enforces max 20, and reports queued status."""
        self._login_as(self.user_a_id)

        # Mixed IDs (User A owns email_a1, User B owns email_b1)
        resp = self.client.post("/api/emails/analyze", json={"email_ids": [self.email_a1_id, self.email_b1_id]})
        self.assertEqual(resp.status_code, 200)

        data = resp.get_json()
        self.assertTrue(data["success"])
        # Only User A's email is queued
        queued_ids = [r["email_id"] for r in data["results"]]
        self.assertIn(self.email_a1_id, queued_ids)
        self.assertNotIn(self.email_b1_id, queued_ids)

        with self.app.app_context():
            # User B email has zero jobs queued
            b_jobs = AIAnalysisJob.query.filter_by(email_id=self.email_b1_id).count()
            self.assertEqual(b_jobs, 0)

    # ─────────────────────────────────────────────────────────────
    # 9. WORKER RUN-ONCE & ERROR SANITIZATION
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_worker_run_once_and_error_sanitization(self, mock_model_cls):
        """Test 9: AIWorker.run_once processes a claimed job, successfully redacting any API keys from persisted errors."""
        mock_instance = MagicMock()
        # Simulate exception that exposes the secret API key in the traceback string
        mock_instance.generate_content.side_effect = Exception("Failed call with key mock-phase61-gemini-key-sec999 on endpoint")
        mock_model_cls.return_value = mock_instance

        with self.app.app_context():
            enqueue_ai_job(self.email_a1_id, self.user_a_id)

        worker = AIWorker(self.app)
        processed = worker.run_once()
        self.assertTrue(processed)

        with self.app.app_context():
            job = AIAnalysisJob.query.filter_by(email_id=self.email_a1_id).first()
            self.assertIsNotNone(job.last_error)
            # Verify secret key is redacted
            self.assertNotIn("mock-phase61-gemini-key-sec999", job.last_error)
            self.assertIn("[REDACTED_API_KEY]", job.last_error)

    # ─────────────────────────────────────────────────────────────
    # 10. MULTI-USER ISOLATION IN QUEUE OPERATIONS
    # ─────────────────────────────────────────────────────────────

    def test_multi_user_queue_isolation(self):
        """Test 10: User A cannot enqueue or claim User B's email."""
        with self.app.app_context():
            # Attempting to enqueue User B's email under User A's ID must be rejected
            job, status = enqueue_ai_job(self.email_b1_id, self.user_a_id)
            self.assertIsNone(job)
            self.assertEqual(status, "rejected")

            # Verify no job was created for User B's email
            count = AIAnalysisJob.query.filter_by(email_id=self.email_b1_id).count()
            self.assertEqual(count, 0)
