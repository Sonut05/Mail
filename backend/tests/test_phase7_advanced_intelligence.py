"""
Phase 7 — Advanced Mail Intelligence, Personalization & UX Test Suite.

Verifies:
1. User preferences CRUD & multi-user isolation.
2. AI privacy controls: master toggle disables job enqueueing.
3. AI data purge (DELETE /api/preferences/ai-data): clears AI metadata while preserving raw emails & confirmed tasks/events.
4. Deterministic personalized inbox ranking with bounded scores and structured explainable reasons.
5. User feedback signals CRUD, boundary validation, and ranking influence.
6. Conversation thread intelligence: state resolution (ACTIVE, WAITING_FOR_USER, WAITING_FOR_OTHER, STALE).
7. Advisory follow-up recommendations & threshold-based dismissal.
8. Contact intelligence aggregation, topic extraction, and search.
9. Advanced search AST tokenization, parameterized query execution, and SQL injection resistance.
10. Dashboard 2.0 metrics (inbox health, action center, people, AI activity).
11. Multi-tenant boundary enforcement across all Phase 7 endpoints.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import sqlalchemy as sa
from flask import session

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.user_preference import UserPreference
from app.models.user_feedback_signal import UserFeedbackSignal

from app.services.personalization_service import (
    calculate_personalized_score,
    get_or_create_user_preferences,
    update_user_preferences,
    record_user_feedback_signal,
    get_user_signals_map,
    clear_user_ai_data,
)
from app.services.thread_service import (
    get_threads_for_user,
    get_thread_detail,
    aggregate_thread,
    get_stale_threads,
)
from app.services.follow_up_service import (
    get_follow_up_recommendations,
)
from app.services.contact_service import (
    get_contacts_list,
    get_contact_detail,
)
from app.services.search_service import (
    parse_search_query,
    execute_advanced_search,
)
from app.services.job_queue_service import enqueue_ai_job


class TestPhase7AdvancedIntelligence:
    """Comprehensive test suite for Phase 7."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create a dedicated test application context with SQLite test database."""
        test_db = f"test_p7_{uuid.uuid4().hex[:8]}.db"

        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{test_db}"
            SECRET_KEY = "test-secret-key-at-least-16-characters-long"
            ENCRYPTION_KEY = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="
            GEMINI_API_KEY = "test-gemini-secret-api-key"
            AI_JOB_ALWAYS_EAGER = False

        app = create_app(TestConfig)
        self.app = app
        self.client = app.test_client()
        self.test_db = test_db

        with app.app_context():
            db.create_all()

            # Create primary test user
            self.user1 = User(
                email="user1@mailmind.ai",
                name="Primary User",
                password_hash="mock_hash_1"
            )
            # Create secondary test user for multi-tenant isolation
            self.user2 = User(
                email="user2@mailmind.ai",
                name="Secondary User",
                password_hash="mock_hash_2"
            )
            db.session.add_all([self.user1, self.user2])
            db.session.commit()

            self.user1_id = self.user1.id
            self.user2_id = self.user2.id

        yield

        # Teardown
        with app.app_context():
            db.session.remove()
            db.drop_all()
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except OSError:
                pass

    def _login_as(self, user_id: str):
        """Helper to simulate authenticated session for user_id."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    # -------------------------------------------------------------------------
    # 1. User Preferences CRUD & Multi-User Isolation
    # -------------------------------------------------------------------------
    def test_user_preferences_crud_and_defaults(self):
        """Preferences are auto-created with valid defaults and can be updated."""
        self._login_as(self.user1_id)

        # GET preferences
        res = self.client.get("/api/preferences")
        assert res.status_code == 200
        data = res.get_json()
        assert "preferences" in data
        prefs = data["preferences"]
        assert prefs["ai_analysis_enabled"] is True
        assert prefs["follow_up_threshold_days"] == 3
        assert prefs["preferred_priority_behavior"] == "balanced"
        assert prefs["smart_inbox_enabled"] is True

        # PUT valid updates
        update_payload = {
            "ai_analysis_enabled": False,
            "follow_up_threshold_days": 5,
            "preferred_priority_behavior": "strict_action_required",
            "smart_inbox_enabled": False,
        }
        res_put = self.client.put("/api/preferences", json=update_payload)
        assert res_put.status_code == 200
        updated = res_put.get_json()["preferences"]
        assert updated["ai_analysis_enabled"] is False
        assert updated["follow_up_threshold_days"] == 5
        assert updated["preferred_priority_behavior"] == "strict_action_required"
        assert updated["smart_inbox_enabled"] is False

    def test_user_preferences_validation(self):
        """Invalid threshold days or priority modes are rejected with 400."""
        self._login_as(self.user1_id)

        # Negative follow-up threshold
        res = self.client.put("/api/preferences", json={"follow_up_threshold_days": -1})
        assert res.status_code == 400

        # Unrecognized priority mode
        res2 = self.client.put("/api/preferences", json={"preferred_priority_behavior": "invalid_mode"})
        assert res2.status_code == 400

    def test_user_preferences_multi_user_isolation(self):
        """User 1's preference changes do not affect User 2."""
        self._login_as(self.user1_id)
        self.client.put("/api/preferences", json={"follow_up_threshold_days": 7})

        # Switch to User 2
        self._login_as(self.user2_id)
        res = self.client.get("/api/preferences")
        assert res.status_code == 200
        prefs2 = res.get_json()["preferences"]
        # User 2 should retain default 3 days
        assert prefs2["follow_up_threshold_days"] == 3

    # -------------------------------------------------------------------------
    # 2. AI Privacy Controls: Toggle Disables Job Enqueueing
    # -------------------------------------------------------------------------
    def test_ai_privacy_toggle_disables_enqueue(self):
        """When ai_analysis_enabled is False, enqueue_ai_job returns disabled and does not queue."""
        with self.app.app_context():
            # Create an email for user1
            msg = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-privacy-1",
                thread_id="th-privacy-1",
                subject="Confidential Email",
                body_text="Top secret discussion",
                from_address="partner@external.com",
                to_address="user1@mailmind.ai",
            )
            db.session.add(msg)
            # Disable AI for user1
            pref = get_or_create_user_preferences(self.user1_id)
            pref.ai_analysis_enabled = False
            db.session.commit()
            msg_id = msg.id

            # Attempt to enqueue
            job, status = enqueue_ai_job(email_id=msg_id, user_id=self.user1_id)
            assert job is None
            assert status == "disabled"

            # Verify no job in DB
            queued_jobs = AIAnalysisJob.query.filter_by(email_id=msg_id).all()
            assert len(queued_jobs) == 0

            # Re-enable AI
            pref.ai_analysis_enabled = True
            db.session.commit()

            # Enqueue now succeeds
            job2, status2 = enqueue_ai_job(email_id=msg_id, user_id=self.user1_id)
            assert job2 is not None
            assert status2 in ("queued", "enqueued", "already_queued")

    # -------------------------------------------------------------------------
    # 3. AI Data Purge (DELETE /api/preferences/ai-data)
    # -------------------------------------------------------------------------
    def test_clear_ai_data_resets_ai_fields_and_deletes_jobs(self):
        """Purging AI data resets all AI columns, deletes jobs, but preserves raw emails & tasks."""
        with self.app.app_context():
            # Setup User 1 email with AI data
            e1 = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-purge-u1",
                subject="User 1 Email",
                body_text="Original raw body content",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                ai_summary="Important corporate summary",
                ai_category="work",
                ai_priority="urgent",
                ai_sentiment="neutral",
                ai_action_required=True,
                ai_importance_score=95,
                ai_confidence_score=90,
                ai_key_points='["point 1", "point 2"]',
                ai_status="completed",
            )
            # Setup User 2 email with AI data (must NOT be touched)
            e2 = EmailMessage(
                user_id=self.user2_id,
                message_id="msg-purge-u2",
                subject="User 2 Email",
                body_text="User 2 private body",
                from_address="client@other.com",
                to_address="user2@mailmind.ai",
                ai_summary="User 2 summary",
                ai_category="personal",
                ai_priority="low",
                ai_status="completed",
            )
            db.session.add_all([e1, e2])
            db.session.flush()

            # Add confirmed task and event for User 1
            task = Task(user_id=self.user1_id, email_id=e1.id, task_title="Confirmed Action Item")
            event = CalendarEvent(user_id=self.user1_id, email_id=e1.id, title="Confirmed Meeting", start_date_time=datetime.now(timezone.utc))
            job1 = AIAnalysisJob(email_id=e1.id, user_id=self.user1_id, status="completed")
            job2 = AIAnalysisJob(email_id=e2.id, user_id=self.user2_id, status="completed")
            db.session.add_all([task, event, job1, job2])
            db.session.commit()
            e1_id = e1.id
            e2_id = e2.id

        # Invoke DELETE /api/preferences/ai-data as User 1
        self._login_as(self.user1_id)
        res = self.client.delete("/api/preferences/ai-data")
        assert res.status_code == 200
        result = res.get_json()
        assert result["success"] is True
        assert result["emails_cleared"] >= 1
        assert result["jobs_removed"] >= 1

        with self.app.app_context():
            u1_email = EmailMessage.query.get(e1_id)
            assert u1_email.ai_summary is None
            assert u1_email.ai_category is None
            assert u1_email.ai_priority == "medium"
            assert u1_email.ai_action_required is False
            assert u1_email.ai_importance_score is None
            assert u1_email.ai_status == "pending"
            # Raw fields preserved
            assert u1_email.subject == "User 1 Email"
            assert u1_email.body_text == "Original raw body content"

            # Confirmed task & event preserved
            assert Task.query.filter_by(user_id=self.user1_id).count() == 1
            assert CalendarEvent.query.filter_by(user_id=self.user1_id).count() == 1

            # User 1 job deleted
            assert AIAnalysisJob.query.filter_by(user_id=self.user1_id).count() == 0

            # User 2 email & jobs untouched
            u2_email = EmailMessage.query.get(e2_id)
            assert u2_email.ai_summary == "User 2 summary"
            assert u2_email.ai_category == "personal"
            assert AIAnalysisJob.query.filter_by(user_id=self.user2_id).count() == 1

    # -------------------------------------------------------------------------
    # 4. Personalized Ranking & Deterministic Explainability
    # -------------------------------------------------------------------------
    def test_personalized_score_calculation(self):
        """Scoring is bounded [0, 100], deterministic, and returns structured reasons."""
        with self.app.app_context():
            pref = get_or_create_user_preferences(self.user1_id)
            pref.important_senders = json.dumps(["boss@corp.com"])
            email = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-score-1",
                subject="Urgent Review Needed",
                from_address="boss@corp.com",
                ai_action_required=True,
                ai_priority="urgent",
                ai_importance_score=85,
                ai_deadline=datetime.now(timezone.utc) + timedelta(hours=12),
                received_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
            db.session.add(email)
            db.session.commit()

            score, reasons = calculate_personalized_score(
                email=email,
                pref=pref,
                signals_map={"sender": {"boss@corp.com": 10.0}},
            )

            # Score must be bounded [0, 100]
            assert 0 <= score <= 100
            assert score >= 70  # Should be very high given urgent + deadline + VIP

            # Explainable reasons list check
            assert len(reasons) > 0
            assert any("Action required" in r for r in reasons)
            assert any("deadline" in r.lower() for r in reasons)

    def test_personalized_score_priority_modes(self):
        """Different preferred_priority_behavior alters weights deterministically."""
        with self.app.app_context():
            email = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-score-modes",
                subject="Quick inquiry",
                from_address="client@external.com",
                ai_action_required=True,
                ai_priority="low",
            )
            db.session.add(email)
            db.session.commit()

            pref_balanced = UserPreference(user_id=self.user1_id, preferred_priority_behavior="balanced")
            pref_strict = UserPreference(user_id=self.user1_id, preferred_priority_behavior="strict_action_required")

            score_balanced, _ = calculate_personalized_score(email, pref_balanced)
            score_strict, _ = calculate_personalized_score(email, pref_strict)

            # Strict action required boosts action items higher
            assert score_strict > score_balanced

    # -------------------------------------------------------------------------
    # 5. User Feedback Signals
    # -------------------------------------------------------------------------
    def test_user_feedback_signals_crud_and_validation(self):
        """User can record bounded feedback signals which aggregate correctly."""
        self._login_as(self.user1_id)

        with self.app.app_context():
            msg = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-sig-1",
                thread_id="th-sig-1",
                subject="Feedback test",
                from_address="feedback_sender@test.com",
            )
            db.session.add(msg)
            db.session.commit()
            msg_id = msg.id

        # POST valid signal
        res = self.client.post("/api/preferences/signals", json={
            "email_id": msg_id,
            "signal_type": "user_importance_boost",
            "signal_weight": 2.0
        })
        assert res.status_code == 201
        sig = res.get_json()["signal"]
        assert sig["weight"] == 2.0
        assert sig["target_value"] == "feedback_sender@test.com"

        # POST out of bounds weight (must be rejected with 400)
        res_invalid = self.client.post("/api/preferences/signals", json={
            "email_id": msg_id,
            "signal_type": "user_importance_boost",
            "signal_weight": 999  # Exceeds max 50
        })
        assert res_invalid.status_code == 400

        # Verify aggregate weights map
        with self.app.app_context():
            signals_map = get_user_signals_map(self.user1_id)
            assert signals_map["sender"].get("feedback_sender@test.com", 0) >= 1.0

    # -------------------------------------------------------------------------
    # 6. Conversation Threads & State Intelligence
    # -------------------------------------------------------------------------
    def test_thread_state_resolution(self):
        """Thread state correctly evaluates to ACTIVE, WAITING_FOR_USER, WAITING_FOR_OTHER, STALE."""
        now = datetime.now(timezone.utc)

        # 1. Thread waiting for user action
        m1 = EmailMessage(
            message_id="m1",
            from_address="client@corp.com",
            to_address="user@mailmind.ai",
            received_at=now - timedelta(hours=1),
            ai_action_required=True
        )
        t1 = aggregate_thread([m1], current_user_email="user@mailmind.ai")
        assert t1["status"] == "WAITING_FOR_USER"

        # 2. Thread where user sent last message (waiting for other)
        m2 = EmailMessage(
            message_id="m2",
            from_address="user@mailmind.ai",
            to_address="client@corp.com",
            received_at=now - timedelta(minutes=30),
            ai_action_required=False
        )
        t2 = aggregate_thread([m1, m2], current_user_email="user@mailmind.ai")
        assert t2["status"] == "WAITING_FOR_OTHER"

        # 3. Stale thread (inactive >= 7 days with unresolved action)
        m_stale = EmailMessage(
            message_id="m_stale",
            from_address="client@corp.com",
            to_address="user@mailmind.ai",
            received_at=now - timedelta(days=10),
            ai_action_required=True
        )
        t_stale = aggregate_thread([m_stale], current_user_email="user@mailmind.ai")
        assert t_stale["status"] == "STALE"

    def test_threads_api_endpoints_and_isolation(self):
        """GET /api/threads and GET /api/threads/<thread_id> respect user isolation."""
        with self.app.app_context():
            # User 1 thread
            t1_m1 = EmailMessage(
                user_id=self.user1_id,
                message_id="u1_t1_m1",
                thread_id="th-u1-alpha",
                subject="Alpha Project Discussion",
                from_address="alice@alpha.com",
                to_address="user1@mailmind.ai",
                body_text="Let's start the alpha sprint.",
                received_at=datetime.now(timezone.utc) - timedelta(hours=2)
            )
            t1_m2 = EmailMessage(
                user_id=self.user1_id,
                message_id="u1_t1_m2",
                thread_id="th-u1-alpha",
                subject="Re: Alpha Project Discussion",
                from_address="user1@mailmind.ai",
                to_address="alice@alpha.com",
                body_text="Sounds great, scheduled for Monday.",
                received_at=datetime.now(timezone.utc) - timedelta(hours=1)
            )
            # User 2 thread
            t2_m1 = EmailMessage(
                user_id=self.user2_id,
                message_id="u2_t1_m1",
                thread_id="th-u2-beta",
                subject="Beta Project Private",
                from_address="bob@beta.com",
                to_address="user2@mailmind.ai",
                body_text="Private beta details.",
                received_at=datetime.now(timezone.utc) - timedelta(hours=1)
            )
            db.session.add_all([t1_m1, t1_m2, t2_m1])
            db.session.commit()

        # Login as User 1
        self._login_as(self.user1_id)
        res = self.client.get("/api/threads")
        assert res.status_code == 200
        threads = res.get_json()["threads"]
        assert len(threads) == 1
        assert threads[0]["thread_id"] == "th-u1-alpha"
        assert threads[0]["message_count"] == 2

        # View specific thread details
        res_detail = self.client.get("/api/threads/th-u1-alpha")
        assert res_detail.status_code == 200
        detail = res_detail.get_json()["thread"]
        assert detail["message_count"] == 2
        assert len(detail["messages"]) == 2

        # Attempt to access User 2's thread -> 404
        res_forbidden = self.client.get("/api/threads/th-u2-beta")
        assert res_forbidden.status_code == 404

    # -------------------------------------------------------------------------
    # 7. Follow-up Recommendations & Dismissal
    # -------------------------------------------------------------------------
    def test_follow_up_recommendations_and_dismissal(self):
        """Identifies threads requiring follow-up; dismissing excludes them."""
        now = datetime.now(timezone.utc)

        with self.app.app_context():
            # User 1 sent inquiry 4 days ago with no reply
            msg = EmailMessage(
                user_id=self.user1_id,
                message_id="followup-msg-1",
                thread_id="th-followup-1",
                subject="Inquiry regarding contract",
                from_address="user1@mailmind.ai",
                to_address="vendor@supplier.com",
                body_text="Any update on the supplier contract?",
                received_at=now - timedelta(days=4),
            )
            db.session.add(msg)
            db.session.commit()

        self._login_as(self.user1_id)

        # GET follow-ups with default threshold (3 days) -> should recommend
        res = self.client.get("/api/threads/follow-ups")
        assert res.status_code == 200
        follow_ups = res.get_json()["follow_ups"]
        assert len(follow_ups) == 1
        assert follow_ups[0]["thread_id"] == "th-followup-1"

        # Dismiss the follow-up
        res_dismiss = self.client.post("/api/threads/th-followup-1/dismiss-follow-up")
        assert res_dismiss.status_code == 200
        assert res_dismiss.get_json()["success"] is True

        # GET follow-ups again -> now empty
        res_after = self.client.get("/api/threads/follow-ups")
        assert len(res_after.get_json()["follow_ups"]) == 0

    # -------------------------------------------------------------------------
    # 8. Contact Intelligence
    # -------------------------------------------------------------------------
    def test_contact_intelligence_aggregation(self):
        """Aggregates interactions, extracted topics, and average sentiment per contact."""
        now = datetime.now(timezone.utc)

        with self.app.app_context():
            m1 = EmailMessage(
                user_id=self.user1_id,
                message_id="contact-m1",
                from_address="sarah.connor@cyberdyne.com",
                to_address="user1@mailmind.ai",
                subject="AI Infrastructure and Security",
                body_text="Security protocols for machine intelligence.",
                ai_sentiment="positive",
                ai_category="work",
                ai_action_required=True,
                received_at=now - timedelta(days=2),
            )
            m2 = EmailMessage(
                user_id=self.user1_id,
                message_id="contact-m2",
                from_address="sarah.connor@cyberdyne.com",
                to_address="user1@mailmind.ai",
                subject="Cyberdyne Cloud Deployment",
                body_text="Deployment pipeline verification.",
                ai_sentiment="neutral",
                ai_category="work",
                received_at=now - timedelta(days=1),
            )
            db.session.add_all([m1, m2])
            db.session.commit()

        self._login_as(self.user1_id)

        # GET /api/contacts
        res = self.client.get("/api/contacts")
        assert res.status_code == 200
        contacts = res.get_json()["contacts"]
        assert len(contacts) == 1
        c = contacts[0]
        assert c["email"] == "sarah.connor@cyberdyne.com"
        assert c["message_count"] == 2
        assert c["action_items_count"] == 1
        assert len(c["recent_topics"]) > 0

        # GET /api/contacts/<email>
        res_detail = self.client.get(f"/api/contacts/{c['email']}")
        assert res_detail.status_code == 200
        detail = res_detail.get_json()["contact"]
        assert detail["email"] == "sarah.connor@cyberdyne.com"
        assert len(detail["recent_emails"]) == 2

    # -------------------------------------------------------------------------
    # 9. Advanced Search AST & Parameterized Query Execution
    # -------------------------------------------------------------------------
    def test_search_query_ast_parsing(self):
        """Validates tokenization of filters, flags, quotes, and free text."""
        query = 'from:alice@example.com priority:urgent action:true has:attachment "quarterly review" budget'
        filters, keywords = parse_search_query(query)

        assert filters["from"] == "alice@example.com"
        assert filters["priority"] == "urgent"
        assert filters["action"] == "true"
        assert filters["has"] == "attachment"
        assert "quarterly review" in keywords
        assert "budget" in keywords

    def test_search_query_sql_injection_resistance(self):
        """Malicious SQL injection attempts are safely parsed as text terms and do not execute."""
        query = "' OR '1'='1'; DROP TABLE email_messages; --"
        filters, keywords = parse_search_query(query)

        # AST must not throw and treats injection attempt as pure text
        assert filters.get("from") is None
        assert len(keywords) > 0

        with self.app.app_context():
            # Executing this query must not harm the database or cause syntax errors
            results = execute_advanced_search(self.user1_id, query)
            assert isinstance(results["items"], list)

            # Ensure table still exists and is healthy
            count = EmailMessage.query.count()
            assert count >= 0

    def test_advanced_search_endpoint_execution(self):
        """GET /api/emails/search accurately executes parameterized search."""
        now = datetime.now(timezone.utc)

        with self.app.app_context():
            m1 = EmailMessage(
                user_id=self.user1_id,
                message_id="search-m1",
                from_address="finance@corp.com",
                to_address="user1@mailmind.ai",
                subject="Q3 Budget Approval",
                body_text="Please approve the revised Q3 engineering budget.",
                ai_priority="urgent",
                ai_action_required=True,
                received_at=now,
            )
            m2 = EmailMessage(
                user_id=self.user1_id,
                message_id="search-m2",
                from_address="news@daily.com",
                to_address="user1@mailmind.ai",
                subject="Weekly Technology Digest",
                body_text="Top tech news this week.",
                ai_priority="low",
                ai_action_required=False,
                received_at=now,
            )
            db.session.add_all([m1, m2])
            db.session.commit()

        self._login_as(self.user1_id)

        # Search for priority:urgent action:true
        res = self.client.get("/api/emails/search?q=priority:urgent action:true")
        assert res.status_code == 200
        emails = res.get_json()["emails"]
        assert len(emails) == 1
        assert emails[0]["subject"] == "Q3 Budget Approval"

        # Search for from:news@daily.com
        res2 = self.client.get("/api/emails/search?q=from:news@daily.com")
        assert res2.status_code == 200
        emails2 = res2.get_json()["emails"]
        assert len(emails2) == 1
        assert emails2[0]["subject"] == "Weekly Technology Digest"

    # -------------------------------------------------------------------------
    # 10. Dashboard 2.0 Metrics
    # -------------------------------------------------------------------------
    def test_dashboard_2_metrics(self):
        """GET /api/dashboard/stats returns Dashboard 2.0 sections."""
        self._login_as(self.user1_id)

        res = self.client.get("/api/dashboard/stats")
        assert res.status_code == 200
        data = res.get_json()

        # Phase 7 Dashboard 2.0 keys
        assert "inbox_health" in data
        health = data["inbox_health"]
        assert "total_unread" in health
        assert "needs_action" in health
        assert "stale_threads" in health

        assert "action_center" in data
        assert "people" in data
        assert "ai_activity" in data

    # -------------------------------------------------------------------------
    # 11. Controlled Alembic Migration Upgrade & Downgrade
    # -------------------------------------------------------------------------
    def test_phase7_migration_upgrade_and_downgrade(self):
        """Validates controlled migration from 4b0e9c8d7e6f to e5a1b2c3d4e5 and rollback."""
        from flask_migrate import upgrade, downgrade, stamp
        mig_db = f"test_mig_p7_{uuid.uuid4().hex[:8]}.db"
        mig_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))

        class MigConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{mig_db}"
            SECRET_KEY = "mig-test-key-minimum-16-chars"
            ENCRYPTION_KEY = "MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE="

        mig_app = create_app(MigConfig)
        with mig_app.app_context():
            db.create_all()
            try:
                # Step A: Stamp at e5a1b2c3d4e5 (matching app factory schema) and downgrade to Phase 6.1 (4b0e9c8d7e6f)
                stamp(revision="e5a1b2c3d4e5", directory=mig_dir)
                downgrade(revision="4b0e9c8d7e6f", directory=mig_dir)

                eng = mig_app.extensions["migrate"].db.engine
                insp_pre = sa.inspect(eng)
                tables_pre = insp_pre.get_table_names()
                assert "user_preferences" not in tables_pre
                assert "user_feedback_signals" not in tables_pre

                # Step B: Upgrade to Phase 7 (e5a1b2c3d4e5)
                upgrade(revision="e5a1b2c3d4e5", directory=mig_dir)
                insp_post = sa.inspect(eng)
                tables_post = insp_post.get_table_names()
                assert "user_preferences" in tables_post
                assert "user_feedback_signals" in tables_post

                # Inspect columns
                pref_cols = {c["name"] for c in insp_post.get_columns("user_preferences")}
                assert "id" in pref_cols
                assert "user_id" in pref_cols
                assert "preferred_priority_behavior" in pref_cols
                assert "follow_up_threshold_days" in pref_cols
                assert "ai_analysis_enabled" in pref_cols
                assert "smart_inbox_enabled" in pref_cols

                sig_cols = {c["name"] for c in insp_post.get_columns("user_feedback_signals")}
                assert "id" in sig_cols
                assert "user_id" in sig_cols
                assert "signal_type" in sig_cols
                assert "target_type" in sig_cols
                assert "target_value" in sig_cols
                assert "weight" in sig_cols

                # Step C: Test clean downgrade back to Phase 6.1
                downgrade(revision="4b0e9c8d7e6f", directory=mig_dir)
                insp_down = sa.inspect(eng)
                tables_down = insp_down.get_table_names()
                assert "user_preferences" not in tables_down
                assert "user_feedback_signals" not in tables_down
            finally:
                db.session.remove()
                try:
                    mig_app.extensions["migrate"].db.engine.dispose()
                except Exception:
                    pass
                if os.path.exists(mig_db):
                    try:
                        os.remove(mig_db)
                    except OSError:
                        pass

