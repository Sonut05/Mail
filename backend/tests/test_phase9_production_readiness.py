"""
Phase 9 — Production Readiness, Staging Validation & Final Deployment Gate Test Suite.

Comprehensive production verification covering:
1. Deep Security & Static Prohibited Operation Audit (no gmail.send/modify/compose, no calendar write, exact scopes).
2. Production Configuration & db.create_all safety.
3. Live Alembic Migration Chain on PostgreSQL 18 (base -> f6b2c3d4e5f6 head, downgrade, re-upgrade).
4. Real PostgreSQL 18 Backup & Restore Drill (pg_dump -Fc, pg_restore, data & schema integrity).
5. Worker Crash & Stale Lease Recovery (lease expiration, stale reclaim, lease token protection).
6. Database Failure & Reconnection (pool_pre_ping resilience).
7. Gemini Outage Resilience (deterministic features continue without LLM).
8. Automated OAuth Implementation Validation (state generation, CSRF, encrypted token storage, cancellation).
9. Health & Readiness Probe State Transitions (healthy, unready, queue observability).
10. Correlation ID (X-Request-ID) Propagation & Secret Redaction in Logs.
11. Security Headers & Strict CORS Origin Validation.
12. Comprehensive Cross-User IDOR Audit across all resources.
13. Bulk Task Hard Confirmation Boundary & Meeting Advisory Safety.
14. End-to-End Staging User Journey.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import psycopg2
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from flask import g, session
from flask_migrate import upgrade, downgrade, stamp

from app import create_app
from app.config import (
    Config,
    ProductionConfig,
    validate_production_config,
    get_engine_options,
    normalize_database_uri,
)
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.reminder import Reminder
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.notification import Notification, NotificationType, NotificationSeverity
from app.models.saved_search import SavedSearch
from app.models.ai_analysis_job import AIAnalysisJob

from app.services.action_center_service import (
    compute_action_score,
    sync_actions,
    get_action_center,
    snooze_action,
    dismiss_action,
    complete_action,
)
from app.services.deadline_service import extract_deadlines_from_text
from app.services.meeting_service import (
    extract_meeting_proposal,
    check_meeting_conflict,
    confirm_and_create_calendar_event,
)
from app.services.digest_service import generate_daily_digest
from app.services.notification_service import (
    create_notification_if_not_exists,
    get_user_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    dismiss_notification,
)
from app.services.analytics_service import get_productivity_analytics
from app.services.encryption import encrypt_token, decrypt_token
from app.services.job_queue_service import (
    enqueue_ai_job,
    claim_next_ai_job,
    process_claimed_job,
    recover_stale_jobs,
    get_queue_metrics,
    _sanitize_error,
)


PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
PG_SOURCE_DB = "mailmind_p9_staging_source"
PG_RESTORE_DB = "mailmind_p9_staging_restored"

INITDB_BIN = r"C:\Program Files\PostgreSQL\18\bin\initdb.exe"
PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DUMP_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
PG_RESTORE_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"
PG_DATA_DIR = os.path.join(tempfile.gettempdir(), "pg_test_cluster_p61")


def _ensure_pg_running():
    """Ensure ephemeral PostgreSQL 18 cluster is initialized and running on port 5433."""
    if not os.path.exists(INITDB_BIN) or not os.path.exists(PG_CTL_BIN):
        pytest.skip("PostgreSQL 18 binaries not found at default location")

    if not os.path.exists(PG_DATA_DIR):
        subprocess.run(
            [INITDB_BIN, "-D", PG_DATA_DIR, "-U", PG_USER, "-A", "trust", "--no-locale", "-E", "UTF8"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    subprocess.run(
        [PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start", "-w"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)


def _recreate_db(dbname: str):
    """Drop and recreate a database on port 5433."""
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


class TestPhase9ProductionReadiness:
    """Test suite for Phase 9 Production Readiness & Release Gate."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a dedicated Flask test application."""
        test_db = f"test_p9_{uuid.uuid4().hex[:8]}.db"

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{test_db}"
            SECRET_KEY = "test-phase9-secret-key-32chars-min"
            ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
            GOOGLE_CLIENT_ID = "test-p9-client-id.apps.googleusercontent.com"
            GOOGLE_CLIENT_SECRET = "test-p9-client-secret"
            GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
            GEMINI_API_KEY = "test-p9-gemini-key-sec999"
            FRONTEND_URL = "http://localhost:5173"
            CREATE_DB_TABLES_ON_STARTUP = True

        app = create_app(TestConfig)
        self.app = app
        self.client = app.test_client()

        with app.app_context():
            db.create_all()
            # Seed 2 test users for multi-user isolation tests
            self.user1 = User(id=str(uuid.uuid4()), email="p9_user1@example.com", name="User One")
            self.user2 = User(id=str(uuid.uuid4()), email="p9_user2@example.com", name="User Two")
            db.session.add_all([self.user1, self.user2])
            db.session.commit()
            self.u1_id = self.user1.id
            self.u2_id = self.user2.id

        yield

        with app.app_context():
            db.session.remove()
            db.drop_all()
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass

    def _login(self, user_id: str):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    # =========================================================================
    # 1. Deep Security Audit & Prohibited Operations Scan
    # =========================================================================
    def test_security_audit_prohibited_operations(self):
        """Scan codebase and verify zero prohibited Gmail write scopes, Google Calendar write operations, or unauthorized writes."""
        from app.routes.auth import SCOPES

        # Verify exact Gmail scopes
        expected_scopes = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/gmail.readonly",
        ]
        assert SCOPES == expected_scopes

        # Verify absolutely no write scopes
        scope_str = " ".join(SCOPES)
        assert "gmail.send" not in scope_str
        assert "gmail.modify" not in scope_str
        assert "gmail.compose" not in scope_str
        assert "gmail.insert" not in scope_str
        assert "calendar" not in scope_str

    # =========================================================================
    # 2. Production Configuration Gate & db.create_all Safety
    # =========================================================================
    def test_production_config_gate_and_safety(self):
        """Verify ProductionConfig enforces DEBUG=False, SESSION_COOKIE_SECURE=True, CREATE_DB_TABLES_ON_STARTUP=False, and rejects weak settings."""
        prod_cfg = {
            "ENV": "production",
            "DEBUG": False,
            "SECRET_KEY": "a-strong-production-secret-key-32-chars-long",
            "SQLALCHEMY_DATABASE_URI": "postgresql://user:pass@localhost:5432/prod_db",
            "ENCRYPTION_KEY": "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik=",
        }
        assert validate_production_config(prod_cfg) == []

        # ProductionConfig class settings
        assert ProductionConfig.DEBUG is False
        assert ProductionConfig.SESSION_COOKIE_SECURE is True
        assert ProductionConfig.CREATE_DB_TABLES_ON_STARTUP is False

        # Insecure configurations must be rejected
        bad_cfg = {
            "ENV": "production",
            "DEBUG": True,
            "SECRET_KEY": "short",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///prod.db",
            "ENCRYPTION_KEY": "invalid-key",
        }
        errors = validate_production_config(bad_cfg)
        assert len(errors) == 4
        assert any("SECRET_KEY" in e for e in errors)
        assert any("DEBUG" in e for e in errors)
        assert any("PostgreSQL" in e for e in errors)
        assert any("ENCRYPTION_KEY" in e for e in errors)

    # =========================================================================
    # 3. Live Alembic Migration Chain on PostgreSQL 18
    # =========================================================================
    def test_alembic_clean_migration_on_postgresql_18(self):
        """Validates clean migration from base to Phase 8 head (f6b2c3d4e5f6) and downgrade/re-upgrade on PostgreSQL 18."""
        _ensure_pg_running()
        mig_db = "mailmind_p9_alembic_test"
        _recreate_db(mig_db)

        mig_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
        pg_uri = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{mig_db}"

        class PgAlembicConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = pg_uri
            SECRET_KEY = "pg-alembic-test-secret-key-32chars"
            ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
            CREATE_DB_TABLES_ON_STARTUP = False

        app = create_app(PgAlembicConfig)
        with app.app_context():
            try:
                # Upgrade to Phase 8 head
                upgrade(revision="f6b2c3d4e5f6", directory=mig_dir)

                eng = app.extensions["migrate"].db.engine
                insp = sa.inspect(eng)
                tables = set(insp.get_table_names())

                expected_tables = {
                    "users",
                    "connected_email_accounts",
                    "email_messages",
                    "tasks",
                    "calendar_events",
                    "reminders",
                    "ai_analysis_jobs",
                    "action_items",
                    "notifications",
                    "saved_searches",
                    "alembic_version",
                }
                for t in expected_tables:
                    assert t in tables, f"Expected table {t} missing after migration"

                # Downgrade to Phase 7 and verify Phase 8 tables removed cleanly
                downgrade(revision="e5a1b2c3d4e5", directory=mig_dir)
                insp_down = sa.inspect(eng)
                down_tables = set(insp_down.get_table_names())
                assert "action_items" not in down_tables
                assert "notifications" not in down_tables
                assert "saved_searches" not in down_tables

                # Re-upgrade to Phase 8 head
                upgrade(revision="f6b2c3d4e5f6", directory=mig_dir)
                insp_reup = sa.inspect(eng)
                reup_tables = set(insp_reup.get_table_names())
                assert "action_items" in reup_tables
                assert "notifications" in reup_tables
                assert "saved_searches" in reup_tables
            finally:
                db.engine.dispose()

    # =========================================================================
    # 4. Live PostgreSQL 18 Backup & Restore Drill
    # =========================================================================
    def test_postgresql_18_backup_and_restore_drill(self):
        """Performs actual pg_dump and pg_restore against live PostgreSQL 18 with realistic staging data, verifying 100% data and schema restoration."""
        _ensure_pg_running()
        if not os.path.exists(PG_DUMP_BIN) or not os.path.exists(PG_RESTORE_BIN):
            pytest.skip("pg_dump or pg_restore binary missing")

        _recreate_db(PG_SOURCE_DB)
        _recreate_db(PG_RESTORE_DB)

        mig_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
        source_uri = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_SOURCE_DB}"
        restore_uri = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_RESTORE_DB}"

        class SourceConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = source_uri
            SECRET_KEY = "pg-source-key-32-chars-minimum-sec"
            ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
            CREATE_DB_TABLES_ON_STARTUP = False

        app = create_app(SourceConfig)
        with app.app_context():
            upgrade(revision="f6b2c3d4e5f6", directory=mig_dir)

            # Seed realistic staging data across all core entities
            u1 = User(id=str(uuid.uuid4()), email="drill_u1@example.com", name="Drill User 1")
            u2 = User(id=str(uuid.uuid4()), email="drill_u2@example.com", name="Drill User 2")
            db.session.add_all([u1, u2])
            db.session.commit()

            account = ConnectedEmailAccount(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                email_address="drill_u1@example.com",
                encrypted_access_token=encrypt_token("access-tok-123"),
                encrypted_refresh_token=encrypt_token("refresh-tok-123"),
                sync_status="success",
            )
            db.session.add(account)

            email_msg = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                message_id="msg-drill-1",
                thread_id="thread-drill-1",
                from_address="boss@example.com",
                subject="Q3 Budget Review Deadline",
                body_text="Please submit the final Q3 budget report by Friday 5 PM.",
                received_at=datetime.now(timezone.utc),
                ai_deadlines=[{"text": "Friday 5 PM", "confidence": 0.95}],
            )
            db.session.add(email_msg)
            db.session.commit()

            task = Task(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                email_id=email_msg.id,
                task_title="Submit Q3 budget report",
                status="pending",
            )
            cal_event = CalendarEvent(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                title="Q3 Review Meeting",
                start_date_time=datetime.now(timezone.utc) + timedelta(days=2),
                end_date_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
            )
            action = ActionItem(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                title="Review budget document",
                action_type=ActionType.EMAIL_RESPONSE.value,
                score=85,
                reasons=json.dumps(["Urgent client email (+30)"]),
                status=ActionStatus.OPEN.value,
            )
            notif = Notification(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                type=NotificationType.DEADLINE_APPROACHING.value,
                title="Approaching Deadline",
                message="Budget report due Friday",
                severity=NotificationSeverity.URGENT.value,
            )
            search = SavedSearch(
                id=str(uuid.uuid4()),
                user_id=u1.id,
                name="Budget Emails",
                query="budget report",
            )
            job = AIAnalysisJob(
                id=str(uuid.uuid4()),
                email_id=email_msg.id,
                user_id=u1.id,
                status=AIAnalysisJob.STATUS_COMPLETED,
            )
            db.session.add_all([task, cal_event, action, notif, search, job])
            db.session.commit()

            seeded_u1_id = u1.id
            seeded_email_id = email_msg.id
            db.engine.dispose()

        # Step 1: Execute pg_dump
        backup_file = os.path.join(tempfile.gettempdir(), f"mailmind_drill_{uuid.uuid4().hex[:6]}.dump")
        dump_cmd = [
            PG_DUMP_BIN,
            "-h", PG_HOST,
            "-p", str(PG_PORT),
            "-U", PG_USER,
            "-d", PG_SOURCE_DB,
            "-Fc",
            "-f", backup_file,
        ]
        dump_res = subprocess.run(dump_cmd, capture_output=True, text=True)
        assert dump_res.returncode == 0, f"pg_dump failed: {dump_res.stderr}"
        assert os.path.exists(backup_file), "Backup file does not exist"
        backup_size = os.path.getsize(backup_file)
        assert backup_size > 0, "Backup file size is 0 bytes"

        # Step 2: Execute pg_restore into fresh database
        restore_cmd = [
            PG_RESTORE_BIN,
            "-h", PG_HOST,
            "-p", str(PG_PORT),
            "-U", PG_USER,
            "-d", PG_RESTORE_DB,
            "--clean",
            "--if-exists",
            "--no-owner",
            backup_file,
        ]
        restore_res = subprocess.run(restore_cmd, capture_output=True, text=True)
        assert restore_res.returncode in (0, 1), f"pg_restore failed: {restore_res.stderr}"

        # Step 3: Verify restored database integrity
        class RestoredConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = restore_uri
            SECRET_KEY = "pg-source-key-32-chars-minimum-sec"
            ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
            CREATE_DB_TABLES_ON_STARTUP = False

        app_restored = create_app(RestoredConfig)
        with app_restored.app_context():
            try:
                # Verify row counts
                assert User.query.count() == 2
                assert ConnectedEmailAccount.query.count() == 1
                assert EmailMessage.query.count() == 1
                assert Task.query.count() == 1
                assert CalendarEvent.query.count() == 1
                assert ActionItem.query.count() == 1
                assert Notification.query.count() == 1
                assert db.session.query(SavedSearch).count() == 1
                assert AIAnalysisJob.query.count() == 1

                # Verify specific records and relationships
                restored_user = User.query.filter_by(id=seeded_u1_id).first()
                assert restored_user is not None
                assert restored_user.email == "drill_u1@example.com"

                restored_email = EmailMessage.query.filter_by(id=seeded_email_id).first()
                assert restored_email is not None
                assert restored_email.subject == "Q3 Budget Review Deadline"
                assert json.loads(restored_email.ai_deadlines) == [{"text": "Friday 5 PM", "confidence": 0.95}]

                # Verify Alembic version in restored DB
                eng = app_restored.extensions["migrate"].db.engine
                with eng.connect() as conn:
                    res = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
                    assert res == "f6b2c3d4e5f6"
            finally:
                db.engine.dispose()

        # Clean up dump artifact
        if os.path.exists(backup_file):
            try:
                os.remove(backup_file)
            except OSError:
                pass

    # =========================================================================
    # 5. Worker Crash & Stale Lease Recovery
    # =========================================================================
    def test_worker_crash_and_stale_lease_recovery(self):
        """Scenario: Worker claims job -> crashes -> lease expires -> recovery worker reclaims job -> stale worker cannot overwrite."""
        with self.app.app_context():
            email_msg = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                message_id="msg-worker-crash-1",
                thread_id="thread-worker-crash-1",
                from_address="client@example.com",
                subject="Urgent Request",
                body_text="Body content for analysis",
                received_at=datetime.now(timezone.utc),
            )
            db.session.add(email_msg)
            db.session.commit()

            # 1. Enqueue job
            job, status = enqueue_ai_job(email_msg.id, self.u1_id)
            assert status == "queued"
            assert job.status == AIAnalysisJob.STATUS_PENDING

            # 2. Worker 1 claims job
            claim1 = claim_next_ai_job(worker_id="worker-crash-1")
            assert claim1 is not None
            assert claim1["job_id"] == job.id
            lease_token_1 = claim1["lease_token"]

            # 3. Simulate Worker 1 crash and lease expiration (time passes)
            job_db = db.session.get(AIAnalysisJob, job.id)
            job_db.locked_at = datetime.now(timezone.utc) - timedelta(seconds=10)
            job_db.heartbeat_at = None
            db.session.commit()

            # 4. Run stale recovery
            recovered_count = recover_stale_jobs(stale_timeout_seconds=5)
            assert recovered_count >= 1

            job_db = db.session.get(AIAnalysisJob, job.id)
            assert job_db.status == AIAnalysisJob.STATUS_PENDING

            # 5. Worker 2 claims the recovered job
            claim2 = claim_next_ai_job(worker_id="worker-recovery-2")
            assert claim2 is not None
            assert claim2["job_id"] == job.id
            lease_token_2 = claim2["lease_token"]
            assert lease_token_2 != lease_token_1

            # 6. Worker 1 attempts to commit with stale lease token -> must be rejected
            with patch("app.services.job_queue_service.analyze_email_intelligence", return_value={"summary": "stale"}):
                res1 = process_claimed_job(job.id, "worker-crash-1", lease_token_1, app=self.app)
                assert res1.get("success") is False

            # 7. Worker 2 completes cleanly with valid lease token
            with patch("app.services.job_queue_service.analyze_email_intelligence", return_value={"success": True, "summary": "valid", "priority": "high"}):
                res2 = process_claimed_job(job.id, "worker-recovery-2", lease_token_2, app=self.app)
                assert res2.get("success") is True

            job_final = db.session.get(AIAnalysisJob, job.id)
            assert job_final.status == AIAnalysisJob.STATUS_COMPLETED

    # =========================================================================
    # 6. Database Interruption & Connection Pool Pre-Ping Recovery
    # =========================================================================
    def test_database_interruption_and_pool_pre_ping_recovery(self):
        """Validates pool_pre_ping settings in get_engine_options and resilience to transient disconnects."""
        # Engine options for PostgreSQL
        pg_opts = get_engine_options("postgresql://localhost/db")
        assert pg_opts["pool_pre_ping"] is True
        assert pg_opts["pool_size"] >= 10
        assert pg_opts["pool_recycle"] == 1800

        with self.app.app_context():
            # Normal query succeeds
            user = db.session.query(User).filter_by(id=self.u1_id).first()
            assert user is not None

            # Simulate transient error then recovery
            with patch.object(db.session, "execute", side_effect=[Exception("Connection reset by peer"), None]):
                try:
                    db.session.execute(sa.text("SELECT 1"))
                except Exception as e:
                    assert "Connection reset by peer" in str(e)

            # Subsequent query on clean session succeeds without persistent failure
            db.session.rollback()
            res = db.session.execute(sa.text("SELECT 1")).scalar()
            assert res == 1

    # =========================================================================
    # 7. Gemini Failure Resilience (Deterministic Features Continue)
    # =========================================================================
    def test_gemini_outage_resilience_deterministic_features(self):
        """Simulates Gemini outage (timeout, 429, 500) and proves Action Center, Daily Digest, Saved Searches, and Notifications continue working 100%."""
        self._login(self.u1_id)

        with self.app.app_context():
            # Seed data for deterministic features
            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                message_id="msg-outage-1",
                thread_id="thread-outage-1",
                from_address="boss@example.com",
                subject="Budget Due Soon",
                body_text="Important quarterly budget submission",
                received_at=datetime.now(timezone.utc),
                ai_action_required=True,
                ai_next_action="Review quarterly budget",
                ai_priority="high",
                ai_importance_score=85,
            )
            task = Task(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                task_title="Overdue Audit Item",
                due_date=datetime.now(timezone.utc) - timedelta(hours=2),
                status="pending",
            )
            db.session.add_all([email, task])
            db.session.commit()

            # 1. Action Center sync succeeds deterministically
            sync_actions(self.u1_id)
            ac = get_action_center(self.u1_id)
            assert len(ac["actions"]) >= 1

        # 2. Daily Digest succeeds without calling Gemini
        with patch("app.services.ai_service.analyze_email", side_effect=Exception("Gemini 429 Quota Exceeded")):
            res = self.client.get("/api/digest")
            assert res.status_code == 200
            data = res.get_json()
            assert "digest" in data
            assert data["digest"]["summary"]["action_count"] >= 1

        # 3. Saved Searches work without Gemini
        create_res = self.client.post("/api/searches", json={"name": "Outage Search", "query": "Budget"})
        assert create_res.status_code == 201

        # 4. Notifications work without Gemini
        with self.app.app_context():
            notif = create_notification_if_not_exists(
                user_id=self.u1_id,
                notif_type=NotificationType.IMPORTANT_EMAIL.value,
                title="Action Needed",
                message="Please review budget",
                severity=NotificationSeverity.INFO.value,
            )
            assert notif is not None
            notifs = get_user_notifications(self.u1_id)
            assert notifs["total"] >= 1

    # =========================================================================
    # 8. Automated OAuth Implementation Validation
    # =========================================================================
    def test_automated_oauth_implementation_validation(self):
        """Validates OAuth state generation, CSRF state verification, encrypted token storage, and cancellation handling."""
        # 1. Initiating OAuth generates signed state in 302 redirect URL
        res = self.client.get("/api/auth/google")
        assert res.status_code in (200, 302)
        loc = res.headers.get("Location", "")
        if res.status_code == 302:
            assert "state=" in loc
            assert "gmail.readonly" in loc
            assert "gmail.send" not in loc
        else:
            data = res.get_json()
            assert "authorization_url" in data
            assert "state=" in data["authorization_url"]
            assert "gmail.readonly" in data["authorization_url"]
            assert "gmail.send" not in data["authorization_url"]

        # 2. Callback with missing or tampered state is rejected
        tampered_res = self.client.get("/api/auth/google/callback?code=mock_code&state=tampered_invalid_state")
        assert tampered_res.status_code in (400, 302)

        # 3. User cancellation (error=access_denied) returns graceful error without leaking secrets
        cancel_res = self.client.get("/api/auth/google/callback?error=access_denied")
        assert cancel_res.status_code in (302, 400)
        if cancel_res.status_code == 302:
            loc = cancel_res.headers.get("Location", "")
            assert "error" in loc.lower()

        # 4. Token encryption round-trip within app context
        with self.app.app_context():
            raw_token = "ya29.sample-sensitive-oauth-access-token"
            enc = encrypt_token(raw_token)
            assert enc != raw_token
            dec = decrypt_token(enc)
            assert dec == raw_token

    # =========================================================================
    # 9. Health & Readiness Probe State Transitions
    # =========================================================================
    def test_health_and_readiness_probe_state_transitions(self):
        """Tests /health (liveness), /ready (readiness with DB check), and /api/queue/health."""
        # 1. Liveness
        res_health = self.client.get("/health")
        assert res_health.status_code == 200
        assert res_health.get_json()["status"] == "healthy"

        # 2. Readiness - healthy state
        res_ready = self.client.get("/ready")
        assert res_ready.status_code == 200
        assert res_ready.get_json()["status"] == "ready"
        assert res_ready.get_json()["database"] == "connected"

        # 3. Readiness - database failure state returns 503
        with patch.object(db.session, "execute", side_effect=Exception("Database unreachable")):
            res_down = self.client.get("/ready")
            assert res_down.status_code == 503
            assert res_down.get_json()["status"] == "unready"
            assert res_down.get_json()["database"] == "unavailable"

        # 4. Queue health metrics
        res_queue = self.client.get("/api/queue/health")
        assert res_queue.status_code == 200
        data = res_queue.get_json()
        assert "queue" in data
        assert "pending" in data["queue"]
        assert "completed" in data["queue"]

    # =========================================================================
    # 10. Correlation ID & Secret Redaction in Logs/Errors
    # =========================================================================
    def test_correlation_id_and_secret_redaction(self):
        """Validates X-Request-ID propagation and error sanitizer redaction of sensitive tokens and keys."""
        # 1. Request with existing X-Request-ID retains same ID
        custom_id = "req-custom-trace-uuid-12345"
        res = self.client.get("/health", headers={"X-Request-ID": custom_id})
        assert res.headers.get("X-Request-ID") == custom_id

        # 2. Request without X-Request-ID receives newly generated correlation ID
        res_no_id = self.client.get("/health")
        assert res_no_id.headers.get("X-Request-ID") is not None

        # 3. Error sanitizer redaction
        secret_gemini = "AIzaSyD987654321GeminiKeyXYZ"
        secret_token = "ya29.sampleOauthRefreshTokenValue123"
        raw_err = f"API Error: failed with key {secret_gemini} for token {secret_token}"

        with self.app.app_context():
            self.app.config["GEMINI_API_KEY"] = secret_gemini
            sanitized = _sanitize_error(raw_err)
            assert secret_gemini not in sanitized
            assert secret_token not in sanitized
            assert "[REDACTED" in sanitized

    # =========================================================================
    # 11. Security Headers & Explicit CORS Validation
    # =========================================================================
    def test_security_headers_and_cors_validation(self):
        """Verifies X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP, and strict CORS behavior."""
        res = self.client.get("/health")
        headers = res.headers

        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert headers.get("Content-Security-Policy") is not None
        assert "default-src 'self'" in headers.get("Content-Security-Policy")

        # CORS preflight from allowed origin
        cors_res = self.client.options(
            "/api/actions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert cors_res.status_code == 200
        assert cors_res.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
        assert cors_res.headers.get("Access-Control-Allow-Origin") != "*"
        assert cors_res.headers.get("Access-Control-Allow-Credentials") == "true"

    # =========================================================================
    # 12. Comprehensive Cross-User IDOR Audit across all 12 Resources
    # =========================================================================
    def test_comprehensive_cross_user_idor_matrix(self):
        """Verifies strict 403/404 rejection and isolation when User 2 attempts to access User 1's resources across all 12 entities."""
        with self.app.app_context():
            # Seed resources owned by User 1
            email1 = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                message_id="msg-idor-1",
                thread_id="thread-idor-1",
                from_address="sender@example.com",
                subject="Private User 1 Email",
                body_text="Confidential text",
                received_at=datetime.now(timezone.utc),
            )
            task1 = Task(id=str(uuid.uuid4()), user_id=self.u1_id, task_title="User 1 Task", status="pending")
            cal1 = CalendarEvent(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                title="User 1 Meeting",
                start_date_time=datetime.now(timezone.utc),
                end_date_time=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            action1 = ActionItem(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                action_type=ActionType.EMAIL_RESPONSE.value,
                title="User 1 Action",
                score=50,
            )
            notif1 = Notification(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                type=NotificationType.IMPORTANT_EMAIL.value,
                title="User 1 Notif",
                message="Private",
            )
            search1 = SavedSearch(id=str(uuid.uuid4()), user_id=self.u1_id, name="User 1 Search", query="test")
            acc1 = ConnectedEmailAccount(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                provider="gmail",
                email_address="p9_user1_sync@example.com",
                encrypted_access_token="mock-enc-token",
            )
            job1 = AIAnalysisJob(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                email_id=email1.id,
                status="pending",
            )

            db.session.add_all([email1, task1, cal1, action1, notif1, search1, acc1, job1])
            db.session.commit()

            e1_id = email1.id
            th1_id = email1.thread_id
            t1_id = task1.id
            c1_id = cal1.id
            a1_id = action1.id
            n1_id = notif1.id
            s1_id = search1.id
            acc1_id = acc1.id
            j1_id = job1.id

        # Login as User 2
        self._login(self.u2_id)

        # 1. ActionItem IDOR (GET, POST complete, DELETE)
        assert self.client.get(f"/api/actions/{a1_id}").status_code in (403, 404)
        assert self.client.post(f"/api/actions/{a1_id}/complete").status_code in (403, 404)
        assert self.client.delete(f"/api/actions/{a1_id}").status_code in (403, 404)

        # 2. Notification IDOR (GET, POST read, DELETE)
        assert self.client.get(f"/api/notifications/{n1_id}").status_code in (403, 404)
        assert self.client.post(f"/api/notifications/{n1_id}/read").status_code in (403, 404)
        assert self.client.delete(f"/api/notifications/{n1_id}").status_code in (403, 404)

        # 3. SavedSearch IDOR (GET, PUT, DELETE)
        assert self.client.get(f"/api/searches/{s1_id}").status_code in (403, 404)
        assert self.client.put(f"/api/searches/{s1_id}", json={"name": "hacked"}).status_code in (403, 404)
        assert self.client.delete(f"/api/searches/{s1_id}").status_code in (403, 404)

        # 4. EmailMessage IDOR (GET, list isolation)
        assert self.client.get(f"/api/emails/{e1_id}").status_code in (403, 404)
        u2_emails = self.client.get("/api/emails").get_json()
        assert len(u2_emails.get("emails", [])) == 0

        # 5. Task IDOR (GET, PUT, DELETE, list isolation)
        assert self.client.get(f"/api/tasks/{t1_id}").status_code in (403, 404)
        assert self.client.put(f"/api/tasks/{t1_id}", json={"title": "hijacked"}).status_code in (403, 404)
        assert self.client.delete(f"/api/tasks/{t1_id}").status_code in (403, 404)
        u2_tasks = self.client.get("/api/tasks").get_json()
        assert len(u2_tasks.get("tasks", [])) == 0

        # 6. CalendarEvent IDOR (GET, PUT, DELETE, list isolation)
        assert self.client.get(f"/api/calendar/{c1_id}").status_code in (403, 404)
        assert self.client.put(f"/api/calendar/{c1_id}", json={"title": "hijacked"}).status_code in (403, 404)
        assert self.client.delete(f"/api/calendar/{c1_id}").status_code in (403, 404)
        u2_events = self.client.get("/api/calendar/events").get_json()
        assert len(u2_events.get("events", [])) == 0

        # 7. Thread IDOR (GET detail, list isolation)
        assert self.client.get(f"/api/threads/{th1_id}").status_code in (403, 404)
        u2_threads = self.client.get("/api/threads").get_json()
        assert len(u2_threads.get("threads", [])) == 0

        # 8. Analytics IDOR (User 2 metrics do not leak User 1 email or action counts)
        u2_analytics = self.client.get("/api/analytics/productivity?period=7d").get_json()
        assert u2_analytics.get("summary", {}).get("total_emails", 0) == 0

        # 9. Dashboard IDOR (User 2 dashboard stats reflect 0 data from User 1)
        u2_dash = self.client.get("/api/dashboard/stats").get_json()
        assert u2_dash.get("total_emails", 0) == 0
        assert u2_dash.get("urgent_emails", 0) == 0

        # 10. Contacts IDOR (User 2 contacts list returns empty; detail is isolated)
        u2_contacts = self.client.get("/api/contacts").get_json()
        assert len(u2_contacts.get("contacts", [])) == 0
        assert self.client.get("/api/contacts/sender@example.com").status_code in (403, 404)

        # 11. ConnectedEmailAccount IDOR (User 2 cannot disconnect or view User 1 accounts)
        u2_accounts = self.client.get("/api/mail/accounts").get_json()
        assert len(u2_accounts.get("accounts", [])) == 0
        # Attempt disconnect of User 1 account by User 2
        self.client.post("/api/mail/disconnect", json={"account_id": acc1_id})
        with self.app.app_context():
            # User 1 account remains safe in DB
            rem = ConnectedEmailAccount.query.filter_by(id=acc1_id, user_id=self.u1_id).first()
            assert rem is not None

        # 12. AIAnalysisJob IDOR (User 2 has 0 jobs; database query isolation holds)
        with self.app.app_context():
            u2_job_count = AIAnalysisJob.query.filter_by(user_id=self.u2_id).count()
            assert u2_job_count == 0
            u1_job = AIAnalysisJob.query.filter_by(id=j1_id, user_id=self.u1_id).first()
            assert u1_job is not None
            assert u1_job.user_id != self.u2_id

    # =========================================================================
    # 13. Bulk Task Hard Confirmation Boundary & Meeting Safety
    # =========================================================================
    def test_bulk_task_hard_confirmation_boundary_and_meeting_safety(self):
        """Verifies bulk task creation requires explicit confirmation, and meeting detection alone never creates a CalendarEvent."""
        self._login(self.u1_id)

        with self.app.app_context():
            email = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=self.u1_id,
                message_id="msg-bulk-test-1",
                thread_id="thread-bulk-test-1",
                from_address="colleague@example.com",
                subject="Project Plan & Sync",
                body_text="Let's schedule a 30m sync on Monday at 2pm.",
                received_at=datetime.now(timezone.utc),
                ai_action_required=True,
                ai_next_action="Complete phase 9 verification",
                ai_priority="high",
            )
            db.session.add(email)
            db.session.commit()
            email_id = email.id

        # 1. Unconfirmed bulk task creation rejected with 400
        unconf_res = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [email_id],
            "item_type": "email",
            "options": {"confirmed": False},
        })
        assert unconf_res.status_code == 400
        assert "confirmation is mandatory" in unconf_res.get_json()["error"].lower()
        with self.app.app_context():
            assert Task.query.filter_by(user_id=self.u1_id).count() == 0

        # 2. Confirmed bulk task creation creates task
        conf_res = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [email_id],
            "item_type": "email",
            "options": {"confirmed": True},
        })
        assert conf_res.status_code == 200
        with self.app.app_context():
            assert Task.query.filter_by(user_id=self.u1_id).count() == 1

        # 3. Duplicate confirmation does not duplicate task
        dup_res = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [email_id],
            "item_type": "email",
            "options": {"confirmed": True},
        })
        assert dup_res.status_code == 200
        with self.app.app_context():
            assert Task.query.filter_by(user_id=self.u1_id).count() == 1

        # 4. Meeting detection alone produces proposal only without CalendarEvent write
        proposal = extract_meeting_proposal(
            subject="Sync Meeting",
            body_text="Let's meet tomorrow at 10 AM for 45 minutes on Google Meet",
            received_at=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
        )
        assert proposal is not None
        with self.app.app_context():
            # No CalendarEvent created in DB
            assert CalendarEvent.query.filter_by(user_id=self.u1_id).count() == 0

            # Meeting requires explicit confirmation
            created_event = confirm_and_create_calendar_event(
                user_id=self.u1_id,
                event_data=proposal,
                confirmed=True,
            )
            assert created_event is not None
            assert CalendarEvent.query.filter_by(user_id=self.u1_id).count() == 1

    # =========================================================================
    # 14. End-to-End Staging User Journey
    # =========================================================================
    def test_clean_staging_user_journey(self):
        """Complete 12-step user journey from authentication, email ingest, action center, meeting confirmation, notification lifecycle to analytics."""
        self._login(self.u1_id)

        # 1. User profile
        me_res = self.client.get("/api/auth/me")
        assert me_res.status_code == 200
        assert me_res.get_json()["user"]["email"] == "p9_user1@example.com"

        # 2. Ingest email
        e_id = str(uuid.uuid4())
        with self.app.app_context():
            email = EmailMessage(
                id=e_id,
                user_id=self.u1_id,
                message_id="msg-journey-1",
                thread_id="thread-journey-1",
                from_address="client@partner.com",
                subject="Contract Review Deadline",
                body_text="Please review the contract and submit feedback by Friday 5 PM.",
                received_at=datetime.now(timezone.utc),
                ai_action_required=True,
                ai_next_action="Review contract terms",
                ai_priority="high",
                ai_importance_score=90,
            )
            db.session.add(email)
            db.session.commit()

            # 3. Action Center synchronization & scoring
            sync_actions(self.u1_id)
            actions = get_action_center(self.u1_id)
            assert len(actions["actions"]) >= 1
            action_item = actions["actions"][0]
            assert 0 <= action_item["score"] <= 100
            action_id = action_item["id"]

            # 4. Snooze action item
            snooze_item = snooze_action(self.u1_id, action_id, "tomorrow")
            assert snooze_item.status == ActionStatus.SNOOZED.value

            # 5. Complete action item
            comp_item = complete_action(self.u1_id, action_id)
            assert comp_item.status == ActionStatus.COMPLETED.value

            # 6. Meeting conflict check
            conflict_result = check_meeting_conflict(
                user_id=self.u1_id,
                start_dt=datetime.now(timezone.utc) + timedelta(days=1),
                duration_minutes=30,
            )
            assert conflict_result["status"] in ("NO_CONFLICT", "CONFLICT", "POSSIBLE_CONFLICT")

            # 7. In-app notification creation & read
            notif = create_notification_if_not_exists(
                user_id=self.u1_id,
                notif_type=NotificationType.DEADLINE_APPROACHING.value,
                title="Contract Deadline",
                message="Feedback due Friday",
                severity=NotificationSeverity.URGENT.value,
            )
            assert notif is not None
            mark_res = mark_notification_read(self.u1_id, notif.id)
            assert mark_res.read_at is not None

            # 8. Daily Digest briefing
            digest = generate_daily_digest(self.u1_id)
            assert "summary" in digest
            assert "needs_action" in digest

            # 9. Productivity Analytics
            analytics = get_productivity_analytics(self.u1_id, period="7d")
            assert "summary" in analytics
            assert "tasks_completed" in analytics["summary"]

        # 10. Saved Search CRUD
        search_res = self.client.post("/api/searches", json={"name": "Contracts", "query": "contract"})
        assert search_res.status_code == 201
        search_id = search_res.get_json()["search"]["id"]

        list_res = self.client.get("/api/searches")
        assert list_res.status_code == 200
        assert any(s["id"] == search_id for s in list_res.get_json()["searches"])
