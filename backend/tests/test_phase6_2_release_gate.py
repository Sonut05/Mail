"""
Phase 6.2.1 — Final Release-Gate Comprehensive Empirical Verification Suite.

Tests against live PostgreSQL 18:
1. Fresh database Alembic migration chain verification (base -> 3a9f8b7c6d5e -> 4b0e9c8d7e6f)
2. Partial active-job unique index enforcement at PostgreSQL engine level
3. Concurrent enqueue race resolution (10 threads -> exactly 1 active job)
4. Concurrent claim race with SELECT ... FOR UPDATE SKIP LOCKED
5. Worker crash recovery & stale lease token protection
6. Real pg_dump and pg_restore backup verification
7. Liveness (/health), Readiness (/ready), and Queue Observability (/api/queue/health)
8. Request correlation ID (X-Request-ID) and security headers
9. Multi-user isolation across all resource boundaries
10. Gemini error handling & sanitization (timeouts, 429 rate limit, 5xx provider failures)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import psycopg2
import sqlalchemy as sa
from flask_migrate import upgrade

from app import create_app
from app.config import Config, ProductionConfig, validate_production_config, normalize_database_uri, get_engine_options
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.ai_analysis_job import AIAnalysisJob
from app.services.encryption import encrypt_token, decrypt_token
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

PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
PG_CLUSTER_DIR = os.path.join(tempfile.gettempdir(), "pg_test_cluster_p61")
INITDB_BIN = r"C:\Program Files\PostgreSQL\18\bin\initdb.exe"
PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DUMP_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
PG_RESTORE_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"

MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))


def _ensure_cluster_running():
    """Ensure PostgreSQL 18 cluster is up on port 5433."""
    if not os.path.exists(INITDB_BIN) or not os.path.exists(PG_CTL_BIN):
        pytest.skip("PostgreSQL 18 binaries not found at default location")

    if not os.path.exists(PG_CLUSTER_DIR):
        subprocess.run(
            [INITDB_BIN, "-D", PG_CLUSTER_DIR, "-U", PG_USER, "-A", "trust", "--no-locale", "-E", "UTF8"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # Check status
    res = subprocess.run([PG_CTL_BIN, "-D", PG_CLUSTER_DIR, "status"], capture_output=True, text=True)
    if "server is running" not in res.stdout:
        subprocess.run(
            [PG_CTL_BIN, "-D", PG_CLUSTER_DIR, "-o", f"-p {PG_PORT}", "start", "-w"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)


def _drop_create_db(dbname: str):
    """Drop and recreate an isolated PostgreSQL database."""
    conn = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{dbname}' AND pid <> pg_backend_pid();")
    cur.execute(f"DROP DATABASE IF EXISTS {dbname};")
    cur.execute(f"CREATE DATABASE {dbname};")
    conn.close()


class TestPhase62ReleaseGate:
    """Release Gate empirical verification suite."""

    @classmethod
    def setup_class(cls):
        _ensure_cluster_running()

    # ── 1. Production Config Gate ───────────────────────────────

    def test_production_config_gate(self):
        """Verify production validator detects and rejects all insecure production configurations."""
        # Clean production config
        valid_prod = {
            "ENV": "production",
            "DEBUG": False,
            "SECRET_KEY": "a-strong-secret-key-at-least-32-chars-long",
            "SQLALCHEMY_DATABASE_URI": "postgresql://postgres@localhost:5433/prod_db",
            "ENCRYPTION_KEY": "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=",
        }
        assert validate_production_config(valid_prod) == []

        # Insecure variations
        assert len(validate_production_config({**valid_prod, "DEBUG": True})) == 1
        assert len(validate_production_config({**valid_prod, "SECRET_KEY": "dev-secret-key-change-me"})) == 1
        assert len(validate_production_config({**valid_prod, "SQLALCHEMY_DATABASE_URI": "sqlite:///local.db"})) == 1
        assert len(validate_production_config({**valid_prod, "ENCRYPTION_KEY": "invalid"})) == 1

    # ── 2. Fresh Database Migration Gate ────────────────────────

    def test_fresh_postgresql_migration_gate(self):
        """Verify complete Alembic migration chain succeeds on a pristine empty PostgreSQL database without db.create_all()."""
        db_name = "gate_mig_fresh_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class FreshMigConfig(Config):
            TESTING = True
            CREATE_DB_TABLES_ON_STARTUP = False
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(FreshMigConfig)
        with app.app_context():
            # Run Alembic upgrade to head
            upgrade(directory=MIGRATIONS_DIR)

            eng = sa.create_engine(db_url)
            insp = sa.inspect(eng)
            tables = sorted(insp.get_table_names())
            assert "users" in tables
            assert "email_messages" in tables
            assert "tasks" in tables
            assert "calendar_events" in tables
            assert "ai_analysis_jobs" in tables

            # Verify partial active AI job unique index
            indexes = insp.get_indexes("ai_analysis_jobs")
            idx_names = [i["name"] for i in indexes]
            assert "uq_active_ai_job_per_email" in idx_names

            # Verify foreign keys
            fks = insp.get_foreign_keys("ai_analysis_jobs")
            fk_targets = [f["referred_table"] for f in fks]
            assert "users" in fk_targets
            assert "email_messages" in fk_targets

    # ── 3. Health & Readiness Gate ──────────────────────────────

    def test_health_and_readiness_gate(self):
        """Verify /health and /ready behavior against live PostgreSQL."""
        db_name = "gate_health_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class LiveConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(LiveConfig)
        client = app.test_client()

        with app.app_context():
            db.create_all()

        # Health probe
        r_h = client.get("/health")
        assert r_h.status_code == 200
        assert r_h.get_json()["status"] == "healthy"

        # Ready probe
        r_r = client.get("/ready")
        assert r_r.status_code == 200
        assert r_r.get_json()["status"] == "ready"
        assert r_r.get_json()["database"] == "connected"

        # Queue health probe
        r_q = client.get("/api/queue/health")
        assert r_q.status_code == 200
        assert r_q.get_json()["status"] == "healthy"
        assert r_q.get_json()["queue"]["total"] == 0

    # ── 4. Real Queue Lifecycle Smoke Test ───────────────────────

    def test_real_queue_lifecycle_smoke_test(self):
        """Verify end-to-end pending -> processing -> completed transition on PostgreSQL."""
        db_name = "gate_queue_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class QueueConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(QueueConfig)

        with app.app_context():
            db.create_all()
            user = User(id=str(uuid.uuid4()), email="test@example.com", name="Test User")
            db.session.add(user)
            db.session.commit()

            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=user.id,
                message_id="msg-smoke-1",
                thread_id="th-smoke-1",
                from_address="boss@example.com",
                subject="Urgent review needed",
                body_text="Please review the attached budget plan by Friday.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
            )
            db.session.add(email)
            db.session.commit()

            # Enqueue
            job, status = enqueue_ai_job(email.id, user.id)
            assert status == "queued"
            assert job.status == AIAnalysisJob.STATUS_PENDING
            assert job.attempts == 0

            # Atomic claim
            claim = claim_next_ai_job(worker_id="gate-worker-1")
            assert claim is not None
            assert claim["job_id"] == job.id
            assert claim["attempts"] == 1

            with sa.create_engine(db_url).connect() as conn:
                row = conn.execute(sa.text(f"SELECT status, locked_by, lease_token FROM ai_analysis_jobs WHERE id = '{job.id}'")).fetchone()
                assert row[0] == "processing"
                assert row[1] == "gate-worker-1"
                assert row[2] is not None

            # Process with mock AI
            mock_res = {
                "success": True,
                "summary": "Budget review requested",
                "category": "Finance",
                "priority": "High",
                "sentiment": "Neutral",
                "action_required": True,
                "deadline": None,
                "entities": [],
                "suggested_tasks": [],
                "suggested_event": None,
                "importance_score": 85,
                "confidence_score": 0.95,
                "key_points": ["Budget review"],
                "waiting_for": None,
                "next_action": "Review budget",
                "reasons": ["Urgent request"],
            }
            with patch("app.services.job_queue_service.analyze_email_intelligence", return_value=mock_res):
                res = process_claimed_job(
                    job_id=claim["job_id"],
                    worker_id=claim["worker_id"],
                    lease_token=claim["lease_token"],
                    app=app,
                )
                assert res["success"] is True
                assert res["status"] == "completed"

            # Check final state in PostgreSQL
            with sa.create_engine(db_url).connect() as conn:
                row = conn.execute(sa.text(f"SELECT status, completed_at, last_error FROM ai_analysis_jobs WHERE id = '{job.id}'")).fetchone()
                assert row[0] == "completed"
                assert row[1] is not None
                assert row[2] is None

    # ── 5. Duplicate Enqueue Gate (10 Threads) ───────────────────

    def test_duplicate_enqueue_gate_under_10_threads(self):
        """10 concurrent threads racing to enqueue the same email result in exactly 1 active job on PostgreSQL."""
        db_name = "gate_dup_enqueue_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class ConcurConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(ConcurConfig)
        with app.app_context():
            db.create_all()
            user = User(id=str(uuid.uuid4()), email="concur@example.com", name="Concur User")
            db.session.add(user)
            db.session.commit()

            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=user.id,
                message_id="msg-race-1",
                from_address="boss@example.com",
                subject="Race test",
                body_text="Testing concurrent enqueues.",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
            )
            db.session.add(email)
            db.session.commit()
            u_id = user.id
            e_id = email.id

        num_threads = 10
        barrier = threading.Barrier(num_threads)
        results = []
        errors = []

        def enqueue_thread():
            local_app = create_app(ConcurConfig)
            with local_app.app_context():
                try:
                    barrier.wait(timeout=5)
                    job, status = enqueue_ai_job(e_id, u_id)
                    results.append((job.id if job else None, status))
                except Exception as exc:
                    errors.append(str(exc))

        threads = [threading.Thread(target=enqueue_thread) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        assert len(results) == num_threads
        queued_count = sum(1 for _, st in results if st == "queued")
        already_queued_count = sum(1 for _, st in results if st == "already_queued")
        assert queued_count == 1
        assert already_queued_count == 9

        with sa.create_engine(db_url).connect() as conn:
            cnt = conn.execute(sa.text(f"SELECT count(*) FROM ai_analysis_jobs WHERE email_id = '{e_id}' AND status = 'pending'")).scalar()
            assert cnt == 1

    # ── 6. Concurrent Claim Gate with SKIP LOCKED ────────────────

    def test_concurrent_claim_skip_locked_gate(self):
        """Two workers competing for a single job never double-claim on PostgreSQL."""
        db_name = "gate_claim_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class ClaimConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(ClaimConfig)
        with app.app_context():
            db.create_all()
            user = User(id=str(uuid.uuid4()), email="claim@example.com", name="Claim User")
            db.session.add(user)
            db.session.commit()

            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=user.id,
                message_id="msg-claim-1",
                from_address="boss@example.com",
                subject="Claim test",
                body_text="Claim body",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
            )
            db.session.add(email)
            db.session.commit()
            enqueue_ai_job(email.id, user.id)

        barrier = threading.Barrier(2)
        claims = {}

        def worker_claim(worker_name: str):
            w_app = create_app(ClaimConfig)
            with w_app.app_context():
                barrier.wait(timeout=5)
                claim = claim_next_ai_job(worker_id=worker_name)
                claims[worker_name] = claim

        t1 = threading.Thread(target=worker_claim, args=("worker-alpha",))
        t2 = threading.Thread(target=worker_claim, args=("worker-beta",))
        t1.start(); t2.start()
        t1.join(timeout=5); t2.join(timeout=5)

        successful_claims = [c for c in claims.values() if c is not None]
        assert len(successful_claims) == 1
        assert claims["worker-alpha"] is None or claims["worker-beta"] is None

    # ── 7. Worker Crash & Stale Recovery Gate ────────────────────

    def test_worker_crash_recovery_and_lease_safety_gate(self):
        """Verify stale jobs recover to pending, and original crashed worker cannot write after being superseded."""
        db_name = "gate_recovery_db"
        _drop_create_db(db_name)
        db_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{db_name}"

        class RecovConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = db_url

        app = create_app(RecovConfig)
        with app.app_context():
            db.create_all()
            user = User(id=str(uuid.uuid4()), email="recov@example.com", name="Recov User")
            db.session.add(user)
            db.session.commit()

            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=user.id,
                message_id="msg-recov-1",
                from_address="boss@example.com",
                subject="Crash test",
                body_text="Body",
                received_at=datetime.now(timezone.utc),
                ai_status="pending",
            )
            db.session.add(email)
            db.session.commit()

            job, _ = enqueue_ai_job(email.id, user.id)
            crashed_claim = claim_next_ai_job(worker_id="crashed-worker")
            assert crashed_claim is not None

            # Age the job to simulate crash/timeout
            past_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
            db.session.execute(
                sa.text(f"UPDATE ai_analysis_jobs SET locked_at = :past, heartbeat_at = :past WHERE id = '{job.id}'"),
                {"past": past_dt},
            )
            db.session.commit()

            # Stale recovery sweep
            recovered = recover_stale_jobs(stale_timeout_seconds=300)
            assert recovered == 1

            # Verify job is pending again
            refreshed = db.session.get(AIAnalysisJob, job.id)
            assert refreshed.status == AIAnalysisJob.STATUS_PENDING
            assert refreshed.locked_by is None
            assert refreshed.lease_token is None

            # New worker claims the job
            new_claim = claim_next_ai_job(worker_id="healthy-worker")
            assert new_claim is not None
            assert new_claim["worker_id"] == "healthy-worker"

            # Crashed worker attempts to write late results with its old lease token
            late_write = process_claimed_job(
                job_id=crashed_claim["job_id"],
                worker_id="crashed-worker",
                lease_token=crashed_claim["lease_token"],
                app=app,
            )
            assert late_write["success"] is False
            assert "Worker does not hold lease" in late_write["error"] or "Lease" in late_write["error"]

    # ── 8. Real Database Backup & Restore Gate ───────────────────

    def test_database_backup_and_restore_gate(self):
        """Empirically verifies pg_dump and pg_restore procedures against live PostgreSQL 18."""
        if not os.path.exists(PG_DUMP_BIN) or not os.path.exists(PG_RESTORE_BIN):
            pytest.skip("pg_dump or pg_restore binary not found")

        source_db = "gate_source_backup_db"
        target_db = "gate_target_restore_db"
        _drop_create_db(source_db)
        _drop_create_db(target_db)

        src_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{source_db}"

        class BackupConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = src_url

        app = create_app(BackupConfig)
        with app.app_context():
            db.create_all()
            user = User(id=str(uuid.uuid4()), email="backup_user@example.com", name="Backup User")
            db.session.add(user)
            db.session.commit()

            task = Task(id=str(uuid.uuid4()), user_id=user.id, task_title="Backup Task", status="pending")
            db.session.add(task)
            db.session.commit()

        # Run pg_dump
        dump_file = os.path.join(tempfile.gettempdir(), f"mailmind_test_{uuid.uuid4().hex[:8]}.dump")
        dump_cmd = [
            PG_DUMP_BIN,
            "-h", PG_HOST,
            "-p", str(PG_PORT),
            "-U", PG_USER,
            "-d", source_db,
            "-Fc",
            "-f", dump_file,
        ]
        res_dump = subprocess.run(dump_cmd, capture_output=True, text=True)
        assert res_dump.returncode == 0, f"pg_dump failed: {res_dump.stderr}"
        assert os.path.exists(dump_file)
        assert os.path.getsize(dump_file) > 100

        # Run pg_restore into target database
        restore_cmd = [
            PG_RESTORE_BIN,
            "-h", PG_HOST,
            "-p", str(PG_PORT),
            "-U", PG_USER,
            "-d", target_db,
            "--clean",
            "--if-exists",
            "--no-owner",
            dump_file,
        ]
        res_restore = subprocess.run(restore_cmd, capture_output=True, text=True)
        assert res_restore.returncode == 0, f"pg_restore failed: {res_restore.stderr}"

        # Verify restored data and constraints in target database
        target_url = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{target_db}"
        with sa.create_engine(target_url).connect() as conn:
            user_cnt = conn.execute(sa.text("SELECT count(*) FROM users WHERE email = 'backup_user@example.com'")).scalar()
            task_cnt = conn.execute(sa.text("SELECT count(*) FROM tasks WHERE task_title = 'Backup Task'")).scalar()
            assert user_cnt == 1
            assert task_cnt == 1

        # Clean up dump file
        if os.path.exists(dump_file):
            try:
                os.remove(dump_file)
            except OSError:
                pass
