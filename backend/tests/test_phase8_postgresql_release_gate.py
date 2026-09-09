"""
Phase 8 PostgreSQL Integration & Release Gate Test.
Verifies live Alembic migration chain (base -> e5a1b2c3d4e5 -> f6b2c3d4e5f6),
table structures, indexes, uniqueness constraints, and concurrency on a real PostgreSQL 18 database.
"""

import os
import time
import tempfile
import threading
import subprocess
import unittest
import psycopg2
from datetime import datetime, timezone, timedelta

import pytest
import sqlalchemy as sa
from flask_migrate import upgrade, downgrade, stamp

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.saved_search import SavedSearch
from app.services.action_center_service import sync_actions


PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
PG_DB_NAME = "mailmild_p8_pg_test_db"
PG_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB_NAME}"

INITDB_BIN = r"C:\Program Files\PostgreSQL\18\bin\initdb.exe"
PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
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


def _reset_pg_db(dbname: str = PG_DB_NAME):
    """Drop and recreate the test database on port 5433."""
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


class TestPhase8PostgresConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = PG_URI
    SECRET_KEY = "test-phase8-pg-secret-key-32chars"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-pg-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-pg-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
    GEMINI_API_KEY = "mock-pg-gemini-key-sec888"


class TestPhase8PostgreSQLReleaseGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_pg_running()

    def setUp(self):
        _reset_pg_db(PG_DB_NAME)

    def test_phase8_alembic_chain_on_postgresql(self):
        """Validates real Alembic upgrade from Phase 7 (e5a1b2c3d4e5) to Phase 8 (f6b2c3d4e5f6) and rollback on PostgreSQL."""
        mig_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")

        app = create_app(TestPhase8PostgresConfig)
        with app.app_context():
            try:
                # Stamp at Phase 8 head and downgrade to Phase 7
                stamp(revision="f6b2c3d4e5f6", directory=mig_dir)
                downgrade(revision="e5a1b2c3d4e5", directory=mig_dir)

                eng = app.extensions["migrate"].db.engine
                insp_pre = sa.inspect(eng)
                pre_tables = insp_pre.get_table_names()
                self.assertNotIn("action_items", pre_tables)
                self.assertNotIn("notifications", pre_tables)
                self.assertNotIn("saved_searches", pre_tables)

                # Upgrade to Phase 8
                upgrade(revision="f6b2c3d4e5f6", directory=mig_dir)

                insp_post = sa.inspect(eng)
                post_tables = insp_post.get_table_names()
                self.assertIn("action_items", post_tables)
                self.assertIn("notifications", post_tables)
                self.assertIn("saved_searches", post_tables)

                # Verify columns on email_messages
                email_cols = {c["name"] for c in insp_post.get_columns("email_messages")}
                self.assertIn("ai_deadlines", email_cols)
                self.assertIn("ai_meeting_proposal", email_cols)

                # Verify clean rollback
                downgrade(revision="e5a1b2c3d4e5", directory=mig_dir)
                insp_down = sa.inspect(eng)
                down_tables = insp_down.get_table_names()
                self.assertNotIn("action_items", down_tables)
                self.assertNotIn("notifications", down_tables)
                self.assertNotIn("saved_searches", down_tables)
            finally:
                db.engine.dispose()

    def test_phase8_concurrency_and_constraints_on_postgresql(self):
        """Verifies multi-threaded concurrency and unique constraints under real PostgreSQL 18."""
        app = create_app(TestPhase8PostgresConfig)
        with app.app_context():
            db.create_all()
            try:
                user = User(
                    email="pg_user_p8@mailmind.ai",
                    name="PG User",
                    password_hash="mock_hash",
                )
                db.session.add(user)
                db.session.commit()
                u_id = user.id

                em = EmailMessage(
                    user_id=u_id,
                    message_id="pg-concurrent-email-1",
                    from_address="boss@client.com",
                    to_address="pg_user_p8@mailmind.ai",
                    subject="Contract Due",
                    body_text="Sign by Friday.",
                    ai_action_required=True,
                    ai_priority="urgent",
                    ai_deadline=datetime.now(timezone.utc) + timedelta(days=2),
                )
                db.session.add(em)
                db.session.commit()
                em_id = em.id

                # Multi-threaded sync on PostgreSQL
                def _worker():
                    with app.app_context():
                        sync_actions(u_id)

                threads = [threading.Thread(target=_worker) for _ in range(5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                # Verify exactly 1 ActionItem exists
                items = ActionItem.query.filter_by(
                    user_id=u_id,
                    source_email_id=em_id,
                ).all()
                self.assertEqual(len(items), 1)

                # Test SavedSearch per-user uniqueness constraint on PostgreSQL
                s1 = SavedSearch(user_id=u_id, name="Urgent Items", query="priority:urgent")
                db.session.add(s1)
                db.session.commit()

                s2_dup = SavedSearch(user_id=u_id, name="Urgent Items", query="other:query")
                db.session.add(s2_dup)
                with self.assertRaises(sa.exc.IntegrityError):
                    db.session.commit()
                db.session.rollback()

            finally:
                db.session.remove()
                db.engine.dispose()
