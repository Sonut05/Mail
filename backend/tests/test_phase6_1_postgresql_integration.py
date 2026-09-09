"""
Phase 6.1 PostgreSQL Integration Tests — Live Database Concurrency & Production Safety.

Executes against a real PostgreSQL 18 database cluster:
1. Real Alembic Migration: Phase 5 -> Phase 6 -> Phase 6.1 -> Downgrade
2. Real Partial Unique Index Enforcement (UNIQUE(email_id) WHERE status IN ('pending', 'processing'))
3. Concurrent Enqueue Race (Multiple threads enqueuing same email -> exactly 1 active job)
4. Concurrent Claiming with Real SELECT ... FOR UPDATE SKIP LOCKED (No double claims)
5. Real Retry Exhaustion & Bounded Attempts (1 -> 2 -> 3 -> failed, never 4)
6. Real Stale Job Recovery on PostgreSQL
7. Real Multi-User Isolation on PostgreSQL
"""

import os
import time
import tempfile
import threading
import subprocess
import unittest
import psycopg2
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from flask_migrate import upgrade, downgrade, stamp

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
)


PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
PG_DB_NAME = "mailmild_pg_test_db"
PG_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB_NAME}"

INITDB_BIN = r"C:\Program Files\PostgreSQL\18\bin\initdb.exe"
PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DATA_DIR = os.path.join(tempfile.gettempdir(), "pg_test_cluster_p61")


def _ensure_pg_running():
    """Ensure ephemeral PostgreSQL 18 cluster is initialized and running on port 5433."""
    if not os.path.exists(INITDB_BIN) or not os.path.exists(PG_CTL_BIN):
        raise RuntimeError("PostgreSQL 18 binaries not found at default location")

    if not os.path.exists(PG_DATA_DIR):
        subprocess.run(
            [INITDB_BIN, "-D", PG_DATA_DIR, "-U", PG_USER, "-A", "trust", "--no-locale", "-E", "UTF8"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Start PostgreSQL on port 5433
    subprocess.run(
        [PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start", "-w"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def _stop_pg():
    """Stop the ephemeral PostgreSQL cluster."""
    if os.path.exists(PG_DATA_DIR):
        subprocess.run(
            [PG_CTL_BIN, "-D", PG_DATA_DIR, "stop", "-m", "fast"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _reset_pg_db(dbname: str = PG_DB_NAME):
    """Drop and recreate the test database on port 5433, terminating active pool connections."""
    conn = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{dbname}' AND pid <> pg_backend_pid();
    """)
    cur.execute(f"DROP DATABASE IF EXISTS {dbname};")
    cur.execute(f"CREATE DATABASE {dbname};")
    conn.close()


class TestPhase61PostgresConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = PG_URI
    SECRET_KEY = "test-phase6-1-pg-secret"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-pg-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-pg-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
    GEMINI_API_KEY = "mock-pg-gemini-key-sec888"
    GEMINI_MODEL = "gemini-2.0-flash"
    AI_JOB_ALWAYS_EAGER = False
    AI_JOB_ASYNC_TESTING = True
    AI_JOB_POLL_INTERVAL = 0.1
    AI_JOB_STALE_SECONDS = 10
    AI_JOB_MAX_ATTEMPTS = 3


class TestPhase61PostgreSQLIntegration(unittest.TestCase):
    """PostgreSQL integration test suite verifying production concurrency and migrations."""

    @classmethod
    def setUpClass(cls):
        try:
            _ensure_pg_running()
            _reset_pg_db()
        except Exception as exc:
            raise unittest.SkipTest(f"Live PostgreSQL 18 environment unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        try:
            _stop_pg()
        except Exception:
            pass

    def setUp(self):
        _reset_pg_db()
        self.app = create_app(TestPhase61PostgresConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create User A & User B
            self.user_a = User(email="alice@pg.com", name="Alice PG")
            self.user_b = User(email="bob@pg.com", name="Bob PG")
            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            self.acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="gmail_alice_pg",
                email_address="alice@pg.com",
                encrypted_access_token=encrypt_token("tok-a-pg"),
                encrypted_refresh_token=encrypt_token("ref-a-pg"),
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
                message_id="msg_pg_a1",
                from_address="boss@corp.com",
                to_address="alice@pg.com",
                subject="PostgreSQL Integration Task",
                body_text="Verify real FOR UPDATE SKIP LOCKED on PostgreSQL 18.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
                ai_retry_count=0,
            )
            self.email_a2 = EmailMessage(
                user_id=self.user_a_id,
                connected_account_id=self.acc_a_id,
                message_id="msg_pg_a2",
                from_address="client@biz.com",
                to_address="alice@pg.com",
                subject="Second PostgreSQL Task",
                body_text="Concurrent claim verification item 2.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
                ai_retry_count=0,
            )
            db.session.add_all([self.email_a1, self.email_a2])
            db.session.commit()

            self.email_a1_id = self.email_a1.id
            self.email_a2_id = self.email_a2.id

            # User B Account & Email
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                provider_account_id="gmail_bob_pg",
                email_address="bob@pg.com",
                encrypted_access_token=encrypt_token("tok-b-pg"),
                encrypted_refresh_token=encrypt_token("ref-b-pg"),
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
                message_id="msg_pg_b1",
                from_address="stranger@dark.com",
                to_address="bob@pg.com",
                subject="Bob Secret Email",
                body_text="Confidential information for Bob.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
                ai_retry_count=0,
            )
            db.session.add(self.email_b1)
            db.session.commit()
            self.email_b1_id = self.email_b1.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    # ─────────────────────────────────────────────────────────────
    # 1. REAL ALEMBIC MIGRATION ON POSTGRESQL (Phase 5 -> 6 -> 6.1)
    # ─────────────────────────────────────────────────────────────

    def test_real_alembic_migration_on_postgresql(self):
        """Test 1: Applies real Alembic migrations on PostgreSQL from baseline to Phase 6.1 and verifies columns & indexes."""
        _reset_pg_db("mailmild_mig_pg_db")

        mig_uri = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/mailmild_mig_pg_db"
        mig_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")

        class MigPGConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = mig_uri

        mig_app = create_app(MigPGConfig)

        with mig_app.app_context():
            try:
                # Step A: Stamp at 4b0e9c8d7e6f (created by app factory) and downgrade to Phase 5
                stamp(revision="4b0e9c8d7e6f", directory=mig_dir)
                downgrade(revision="28814bc4372b", directory=mig_dir)

                eng = mig_app.extensions["migrate"].db.engine
                insp_p5 = sa.inspect(eng)
                p5_cols = [c["name"] for c in insp_p5.get_columns("email_messages")]
                self.assertNotIn("ai_importance_score", p5_cols, "ai_importance_score should not exist in Phase 5 schema")
                self.assertNotIn("ai_analysis_jobs", insp_p5.get_table_names(), "ai_analysis_jobs should not exist in Phase 5 schema")

                # Step B: Upgrade to Phase 6 (3a9f8b7c6d5e)
                upgrade(revision="3a9f8b7c6d5e", directory=mig_dir)
                insp_p6 = sa.inspect(eng)
                p6_cols = [c["name"] for c in insp_p6.get_columns("email_messages")]
                self.assertIn("ai_importance_score", p6_cols)
                self.assertIn("ai_key_points", p6_cols)
                self.assertNotIn("ai_analysis_jobs", insp_p6.get_table_names(), "ai_analysis_jobs should not exist in Phase 6 schema")

                # Step C: Upgrade to Phase 6.1 (4b0e9c8d7e6f)
                upgrade(revision="4b0e9c8d7e6f", directory=mig_dir)
                insp_p61 = sa.inspect(eng)
                self.assertIn("ai_analysis_jobs", insp_p61.get_table_names())
                job_cols = [c["name"] for c in insp_p61.get_columns("ai_analysis_jobs")]
                self.assertIn("id", job_cols)
                self.assertIn("email_id", job_cols)
                self.assertIn("user_id", job_cols)
                self.assertIn("status", job_cols)
                self.assertIn("attempts", job_cols)
                self.assertIn("available_at", job_cols)
                self.assertIn("locked_at", job_cols)
                self.assertIn("lease_token", job_cols)

                indexes = [idx["name"] for idx in insp_p61.get_indexes("ai_analysis_jobs")]
                self.assertIn("uq_active_ai_job_per_email", indexes)

                # Step D: Downgrade back to Phase 6
                downgrade(revision="3a9f8b7c6d5e", directory=mig_dir)
                insp_down = sa.inspect(eng)
                self.assertNotIn("ai_analysis_jobs", insp_down.get_table_names())
            finally:
                db.engine.dispose()


    # ─────────────────────────────────────────────────────────────
    # 2. REAL PARTIAL UNIQUE INDEX ENFORCEMENT ON POSTGRESQL
    # ─────────────────────────────────────────────────────────────

    def test_partial_unique_index_enforcement_on_postgresql(self):
        """Test 2: PostgreSQL engine strictly rejects duplicate active jobs (pending/processing) for the same email with UniqueViolation."""
        with self.app.app_context():
            # First active job
            job1 = AIAnalysisJob(
                email_id=self.email_a1_id,
                user_id=self.user_a_id,
                status="pending",
                attempts=0,
            )
            db.session.add(job1)
            db.session.commit()

            # Second active job for the SAME email must be rejected by PostgreSQL engine
            job2 = AIAnalysisJob(
                email_id=self.email_a1_id,
                user_id=self.user_a_id,
                status="processing",
                attempts=0,
            )
            db.session.add(job2)
            with self.assertRaises(sa.exc.IntegrityError):
                db.session.commit()
            db.session.rollback()

            # But an inactive (completed or failed) job can coexist because index is PARTIAL
            job1_db = db.session.get(AIAnalysisJob, job1.id)
            job1_db.status = "completed"
            db.session.commit()

            # Now a new pending job can be created cleanly
            job3 = AIAnalysisJob(
                email_id=self.email_a1_id,
                user_id=self.user_a_id,
                status="pending",
                attempts=0,
            )
            db.session.add(job3)
            db.session.commit()
            self.assertIsNotNone(job3.id)

    # ─────────────────────────────────────────────────────────────
    # 3. CONCURRENT ENQUEUE RACE ON POSTGRESQL
    # ─────────────────────────────────────────────────────────────

    def test_concurrent_enqueue_race_on_postgresql(self):
        """Test 3: Multiple simultaneous threads attempting to enqueue the same email result in exactly 1 active job in PostgreSQL."""
        num_threads = 5
        barrier = threading.Barrier(num_threads)
        results = []
        errors = []

        def do_enqueue():
            barrier.wait()
            with self.app.app_context():
                try:
                    job, status = enqueue_ai_job(self.email_a1_id, self.user_a_id)
                    results.append((job.id if job else None, status))
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=do_enqueue) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Encountered unexpected errors during enqueue race: {errors}")
        self.assertEqual(len(results), num_threads)

        # Exactly 1 thread received 'queued', all others received 'already_queued'
        statuses = [s for _, s in results]
        self.assertEqual(statuses.count("queued"), 1)
        self.assertEqual(statuses.count("already_queued"), num_threads - 1)

        with self.app.app_context():
            # Total active jobs in PostgreSQL is exactly 1
            active_count = AIAnalysisJob.query.filter(
                AIAnalysisJob.email_id == self.email_a1_id,
                AIAnalysisJob.status.in_(["pending", "processing"]),
            ).count()
            self.assertEqual(active_count, 1)

    # ─────────────────────────────────────────────────────────────
    # 4. CONCURRENT CLAIMING WITH REAL 'FOR UPDATE SKIP LOCKED'
    # ─────────────────────────────────────────────────────────────

    def test_concurrent_claim_skip_locked_on_postgresql(self):
        """Test 4: Real SELECT ... FOR UPDATE SKIP LOCKED prevents any two workers from claiming the same job."""
        with self.app.app_context():
            job1, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)
            job2, _ = enqueue_ai_job(self.email_a2_id, self.user_a_id)

        barrier = threading.Barrier(2)
        claims = []
        errors = []

        def worker_claim(worker_name: str):
            barrier.wait()
            with self.app.app_context():
                try:
                    claim = claim_next_ai_job(worker_id=worker_name)
                    if claim:
                        claims.append(claim)
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=worker_claim, args=("worker-alpha",))
        t2 = threading.Thread(target=worker_claim, args=("worker-beta",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(claims), 2, "Both workers should successfully claim different jobs")

        claimed_job_ids = [c["job_id"] for c in claims]
        claimed_workers = [c["worker_id"] for c in claims]

        # Ensure NO double claim
        self.assertEqual(len(set(claimed_job_ids)), 2, "Workers claimed the same job! FOR UPDATE SKIP LOCKED failed!")
        self.assertIn("worker-alpha", claimed_workers)
        self.assertIn("worker-beta", claimed_workers)

        # When a third worker attempts to claim, it receives None (zero jobs remaining)
        with self.app.app_context():
            claim3 = claim_next_ai_job(worker_id="worker-gamma")
            self.assertIsNone(claim3)

    # ─────────────────────────────────────────────────────────────
    # 5. REAL RETRY EXHAUSTION ON POSTGRESQL
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_retry_exhaustion_on_postgresql(self, mock_model_cls):
        """Test 5: Retrying 3 times on PostgreSQL permanently marks job as 'failed' and caps attempts at 3."""
        mock_instance = MagicMock()
        mock_instance.generate_content.side_effect = Exception("PostgreSQL Downstream Service Error")
        mock_model_cls.return_value = mock_instance

        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)

            for attempt in range(1, 4):
                # Claim and process attempt
                claim = claim_next_ai_job(worker_id="pg-retry-worker")
                self.assertIsNotNone(claim, f"Worker failed to claim on attempt {attempt}")
                self.assertEqual(claim["attempts"], attempt)

                res = process_claimed_job(
                    claim["job_id"],
                    worker_id=claim["worker_id"],
                    lease_token=claim["lease_token"],
                    app=self.app,
                )
                self.assertFalse(res["success"])

                job_db = db.session.get(AIAnalysisJob, job.id)
                if attempt < 3:
                    self.assertEqual(job_db.status, "pending")
                    self.assertTrue(res["retry_scheduled"])
                    # Fast-forward available_at for next attempt
                    job_db.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                    db.session.commit()
                else:
                    self.assertEqual(job_db.status, "failed")
                    self.assertFalse(res["retry_scheduled"])

            # Final check: attempts must be exactly 3, and no further claims are possible
            final_job = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(final_job.status, "failed")
            self.assertEqual(final_job.attempts, 3)

            further_claim = claim_next_ai_job(worker_id="pg-retry-worker")
            self.assertIsNone(further_claim)

    # ─────────────────────────────────────────────────────────────
    # 6. REAL STALE RECOVERY ON POSTGRESQL
    # ─────────────────────────────────────────────────────────────

    def test_stale_recovery_on_postgresql(self):
        """Test 6: Recovers crashed worker lease on real PostgreSQL with FOR UPDATE SKIP LOCKED."""
        with self.app.app_context():
            job, _ = enqueue_ai_job(self.email_a1_id, self.user_a_id)
            claim = claim_next_ai_job(worker_id="crashed-pg-worker")

            # Simulate worker crash and timeout
            past = datetime.now(timezone.utc) - timedelta(minutes=10)
            job_db = db.session.get(AIAnalysisJob, job.id)
            job_db.locked_at = past
            job_db.heartbeat_at = past
            db.session.commit()

            # Execute recovery
            recovered = recover_stale_jobs(stale_timeout_seconds=300)
            self.assertEqual(recovered, 1)

            job_recovered = db.session.get(AIAnalysisJob, job.id)
            self.assertEqual(job_recovered.status, "pending")
            self.assertIsNone(job_recovered.locked_by)

            # Re-claim by another worker
            reclaim = claim_next_ai_job(worker_id="healed-pg-worker")
            self.assertIsNotNone(reclaim)
            self.assertEqual(reclaim["job_id"], job.id)

    # ─────────────────────────────────────────────────────────────
    # 7. REAL MULTI-USER ISOLATION ON POSTGRESQL
    # ─────────────────────────────────────────────────────────────

    def test_multi_user_isolation_on_postgresql(self):
        """Test 7: User A cannot enqueue or claim User B's emails in PostgreSQL."""
        with self.app.app_context():
            # Enqueue User B email with User A credentials must be rejected
            job, status = enqueue_ai_job(self.email_b1_id, self.user_a_id)
            self.assertIsNone(job)
            self.assertEqual(status, "rejected")

            # User B email has zero jobs in PostgreSQL
            count = AIAnalysisJob.query.filter_by(email_id=self.email_b1_id).count()
            self.assertEqual(count, 0)
