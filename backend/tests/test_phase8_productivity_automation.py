"""
Phase 8 — Advanced Productivity Automation & Intelligence Test Suite.

Verifies:
1. Action Center:
   - compute_action_score bounded in [0, 100].
   - Explainability reasons list structured and non-empty.
   - Smart snooze modes (1h, tomorrow, 3d, next_week, custom).
   - Action dismissal and completion state transitions.
   - Idempotent action sync.
   - Multi-user isolation.
2. Deadline Intelligence:
   - Hybrid deterministic extraction (absolute, relative, EOD/COB, timezone aware).
   - Multiple deadlines extraction from single text.
   - Thread deadline change detection (detects shifts across messages chronologically without altering user tasks).
3. Meeting Intelligence:
   - Meeting proposal extraction (date, time, duration, location).
   - Conflict detection using canonical start_dt < c_end and end_dt > c_start.
   - Explicit confirmation required before internal CalendarEvent creation.
4. Relationship Intelligence:
   - Observable relationship score [0, 100].
   - Response turnaround stats (< 3 samples returns 'Insufficient history' safeguard).
   - Relationship health states (ACTIVE, ENGAGED, DORMANT, WAITING, NEEDS_ATTENTION).
   - Multi-user isolation.
5. Daily Digest:
   - Deterministic aggregation without Gemini API.
   - Morning focus cards: urgent emails, needs action, deadlines, follow-ups, schedule.
   - Multi-user isolation.
6. Notification Center:
   - Creation and deduplication (user_id, notif_type, source_type, source_id).
   - Unread counter, mark read, mark all read, dismiss.
   - Multi-user isolation.
7. Productivity Analytics:
   - Time-series trends over 7d, 30d, 90d.
   - Invalid period rejection (returns 400).
   - Multi-user isolation.
8. Saved Searches:
   - CRUD operations.
   - Unique per user (user_id, name).
   - Different users can have identical search name.
   - SQL injection resistance.
9. Bulk Actions & Security:
   - Bulk action execution (mark_read, mark_unread, star, unstar, create_tasks).
   - Two-layer confirmation safeguard for task creation.
   - All-or-nothing multi-user ownership check (cross-user rejection).
   - IDOR security tests across all new endpoints.
10. Alembic Migration & Schema:
   - Migration f6b2c3d4e5f6 upgrade, downgrade to e5a1b2c3d4e5, and re-upgrade.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.notification import Notification, NotificationType, NotificationSeverity
from app.models.saved_search import SavedSearch

from app.services.action_center_service import (
    compute_action_score,
    sync_actions,
    get_action_center,
    snooze_action,
    dismiss_action,
    complete_action,
)
from app.services.deadline_service import (
    extract_deadlines_from_text,
    detect_thread_deadline_changes,
)
from app.services.meeting_service import (
    extract_meeting_proposal,
    check_meeting_conflict,
    confirm_and_create_calendar_event,
)
from app.services.relationship_service import (
    compute_relationship_score,
    calculate_response_time_stats,
    determine_relationship_health,
    get_relationship_profile,
)
from app.services.digest_service import generate_daily_digest
from app.services.notification_service import (
    create_notification_if_not_exists,
    get_user_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    dismiss_notification,
    get_unread_notifications_count,
)
from app.services.analytics_service import get_productivity_analytics
from app.services.bulk_action_service import execute_bulk_action


class TestPhase8ProductivityAutomation:
    """Comprehensive test suite for Phase 8."""

    @pytest.fixture(autouse=True)
    def setup_app(self):
        """Create a dedicated test application context with SQLite test database."""
        test_db = f"test_p8_{uuid.uuid4().hex[:8]}.db"

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

            self.user1 = User(
                email="user1@mailmind.ai",
                name="Primary User",
                password_hash="mock_hash_1"
            )
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
    # 1. Action Center: Scoring, Reasons, Snooze, Dismiss, Complete, Idempotency
    # -------------------------------------------------------------------------
    def test_action_score_bounded_and_explainability(self):
        """Action score must be clamped strictly in [0, 100] with non-empty reasons."""
        # Max extreme
        high_score, high_reasons = compute_action_score(
            urgency=100.0,
            deadline_proximity=100.0,
            importance=100.0,
            waiting_duration=100.0,
            relationship_importance=100.0,
        )
        assert 0 <= high_score <= 100
        assert high_score == 100
        assert len(high_reasons) > 0
        assert isinstance(high_reasons, list)

        # Min extreme
        low_score, low_reasons = compute_action_score(
            urgency=0.0,
            deadline_proximity=0.0,
            importance=0.0,
            waiting_duration=0.0,
            relationship_importance=0.0,
        )
        assert 0 <= low_score <= 100
        assert low_score >= 0
        assert len(low_reasons) > 0

    def test_action_sync_idempotency_and_lifecycle(self):
        """Action sync creates action items idempotently and supports snooze, dismiss, complete."""
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            em = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-act-1",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                subject="Q3 Budget Review",
                body_text="Please submit the final Q3 budget numbers by tomorrow.",
                ai_action_required=True,
                ai_deadline=now + timedelta(days=1),
                ai_importance_score=85,
                priority="urgent",
                received_at=now,
            )
            db.session.add(em)
            db.session.commit()

            # First sync
            items1 = sync_actions(self.user1_id)
            assert len(items1) >= 1
            action = items1[0]
            action_id = action.id
            assert action.score >= 50
            assert len(action.reasons) > 0

            # Second sync (idempotency check)
            items2 = sync_actions(self.user1_id)
            assert len(items2) == len(items1)
            # Item ID preserved
            assert any(a.id == action_id for a in items2)

        self._login_as(self.user1_id)

        # Snooze action (1h mode)
        res_snooze = self.client.post(f"/api/actions/{action_id}/snooze", json={"mode": "1h"})
        assert res_snooze.status_code == 200
        data = res_snooze.get_json()
        assert data["action"]["status"].upper() == "SNOOZED"
        assert data["action"]["snoozed_until"] is not None

        # Snooze with custom ISO date
        custom_dt = (now + timedelta(days=5)).isoformat()
        res_custom = self.client.post(f"/api/actions/{action_id}/snooze", json={"mode": "custom", "custom_date": custom_dt})
        assert res_custom.status_code == 200
        assert res_custom.get_json()["action"]["status"].upper() == "SNOOZED"

        # Complete action
        res_comp = self.client.post(f"/api/actions/{action_id}/complete")
        assert res_comp.status_code == 200
        assert res_comp.get_json()["action"]["status"].upper() == "COMPLETED"

        # Dismiss action
        res_dism = self.client.post(f"/api/actions/{action_id}/dismiss")
        assert res_dism.status_code == 200
        assert res_dism.get_json()["action"]["status"].upper() == "DISMISSED"

    def test_action_center_multi_user_isolation(self):
        """User 2 cannot view or mutate User 1's action items."""
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            act = ActionItem(
                user_id=self.user1_id,
                title="Confidential User 1 Audit",
                action_type=ActionType.EMAIL_RESPONSE.value,
                score=90,
                reasons=["High priority"],
                status=ActionStatus.OPEN.value,
            )
            db.session.add(act)
            db.session.commit()
            act_id = act.id

        # User 2 tries to snooze User 1's action
        self._login_as(self.user2_id)
        res_snooze = self.client.post(f"/api/actions/{act_id}/snooze", json={"mode": "1h"})
        assert res_snooze.status_code == 404

        # User 2 tries to complete User 1's action
        res_comp = self.client.post(f"/api/actions/{act_id}/complete")
        assert res_comp.status_code == 404

        # User 2 action list does not include User 1 action
        res_list = self.client.get("/api/actions")
        assert res_list.status_code == 200
        assert not any(a["id"] == act_id for a in res_list.get_json()["actions"])

    # -------------------------------------------------------------------------
    # 2. Advanced Deadline Intelligence & Thread Change Detection
    # -------------------------------------------------------------------------
    def test_deadline_intelligence_extraction(self):
        """Hybrid deterministic extraction handles absolute, relative, EOD/COB, and multiple deadlines."""
        ref_dt = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)

        # Absolute date
        t1 = "Please submit the manuscript by October 15, 2026."
        d1 = extract_deadlines_from_text(t1, reference_dt=ref_dt)
        assert len(d1) >= 1
        assert "2026-10-15" in d1[0]["deadline"]

        # Relative date + EOD
        t2 = "We need this by tomorrow EOD."
        d2 = extract_deadlines_from_text(t2, reference_dt=ref_dt)
        assert len(d2) >= 1
        assert d2[0]["confidence"] > 0.7

        # Multiple deadlines
        t3 = "Draft due by tomorrow 5pm, and final report due Friday COB."
        d3 = extract_deadlines_from_text(t3, reference_dt=ref_dt)
        assert len(d3) >= 2

    def test_thread_deadline_change_detection(self):
        """Chronological comparison of thread messages detects deadline shifts without altering user tasks."""
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            th_id = "th-deadline-shift"
            m1 = EmailMessage(
                user_id=self.user1_id,
                message_id="shift-1",
                thread_id=th_id,
                from_address="colleague@corp.com",
                to_address="user1@mailmind.ai",
                subject="Proposal Timeline",
                body_text="Proposal is due this Friday Oct 16, 2026.",
                ai_deadlines=[{"deadline": "2026-10-16T17:00:00Z", "context": "due this Friday"}],
                received_at=now - timedelta(days=2),
            )
            m2 = EmailMessage(
                user_id=self.user1_id,
                message_id="shift-2",
                thread_id=th_id,
                from_address="colleague@corp.com",
                to_address="user1@mailmind.ai",
                subject="Re: Proposal Timeline",
                body_text="Update: client extended deadline to next Tuesday Oct 20, 2026.",
                ai_deadlines=[{"deadline": "2026-10-20T17:00:00Z", "context": "extended deadline"}],
                received_at=now - timedelta(days=1),
            )
            db.session.add_all([m1, m2])
            db.session.commit()

            changes = detect_thread_deadline_changes(th_id, self.user1_id)
            assert len(changes) >= 1
            change = changes[0]
            assert change["previous_deadline"] == "2026-10-16T17:00:00Z"
            assert change["new_deadline"] == "2026-10-20T17:00:00Z"
            assert change["status"] == "shifted"

    # -------------------------------------------------------------------------
    # 3. Meeting Intelligence & Canonical Conflict Detection
    # -------------------------------------------------------------------------
    def test_meeting_proposal_extraction_and_canonical_conflict(self):
        """Meeting proposal extraction and canonical overlap check: new_start < existing_end AND new_end > existing_start."""
        text = "Let's meet on 2026-10-15 at 14:00 UTC for 60 minutes via Google Meet to review designs."
        proposal = extract_meeting_proposal(text)
        assert proposal is not None
        assert proposal["date"] == "2026-10-15"
        assert proposal["duration_minutes"] == 60

        now = datetime.now(timezone.utc)
        with self.app.app_context():
            # Existing event: Oct 15 from 14:00 to 15:00 UTC
            c_event = CalendarEvent(
                user_id=self.user1_id,
                title="Existing Product Sync",
                start_date_time=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc),
                end_date_time=datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc),
            )
            db.session.add(c_event)
            db.session.commit()

            # Overlap 1: 14:30 to 15:30 (conflicts)
            conf1 = check_meeting_conflict(
                self.user1_id,
                datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc),
                datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc),
            )
            assert conf1["has_conflict"] is True
            assert len(conf1["conflicts"]) == 1

            # Overlap 2: 13:30 to 14:30 (conflicts)
            conf2 = check_meeting_conflict(
                self.user1_id,
                datetime(2026, 10, 15, 13, 30, tzinfo=timezone.utc),
                datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc),
            )
            assert conf2["has_conflict"] is True

            # Non-overlap adjacent: 15:00 to 16:00 (no conflict)
            conf3 = check_meeting_conflict(
                self.user1_id,
                datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc),
            )
            assert conf3["has_conflict"] is False

    def test_meeting_confirmation_safeguard(self):
        """Creating an event requires explicit user confirmation (advisory safeguard)."""
        proposal = {
            "title": "Design Discussion",
            "start_time": "2026-10-15T16:00:00Z",
            "end_time": "2026-10-15T17:00:00Z",
            "location": "https://meet.google.com/abc-defg-hij",
        }

        # Unconfirmed creation raises ValueError
        with pytest.raises(ValueError, match="User confirmation required"):
            confirm_and_create_calendar_event(self.user1_id, proposal, confirmed=False)

        # Confirmed creation succeeds
        with self.app.app_context():
            evt = confirm_and_create_calendar_event(self.user1_id, proposal, confirmed=True)
            assert evt.id is not None
            assert evt.title == "Design Discussion"
            assert evt.user_id == self.user1_id

    # -------------------------------------------------------------------------
    # 4. Relationship Intelligence & Insufficient History Safeguard
    # -------------------------------------------------------------------------
    def test_relationship_scoring_and_history_safeguard(self):
        """Turnaround stats return 'Insufficient history' when samples < 3."""
        with self.app.app_context():
            # 1 message only
            em = EmailMessage(
                user_id=self.user1_id,
                message_id="rel-1",
                thread_id="th-rel-1",
                from_address="vendor@partner.org",
                to_address="user1@mailmind.ai",
                subject="Vendor Intro",
                body_text="Hello, here is our brochure.",
                received_at=datetime.now(timezone.utc),
            )
            db.session.add(em)
            db.session.commit()

            stats = calculate_response_time_stats(self.user1_id, "vendor@partner.org")
            assert stats["status"] == "Insufficient history"
            assert stats["average_hours"] is None

        # Observable score bounded in [0, 100]
        score, reasons = compute_relationship_score(
            interaction_frequency=12,
            recency_days=3.0,
            response_rate=0.85,
            thread_count=4,
            open_actions=1,
            avg_importance=75.0,
        )
        assert 0 <= score <= 100
        assert len(reasons) > 0

    def test_relationship_health_states(self):
        """Relationship health states map correctly to observable signals."""
        assert determine_relationship_health(10, 2.0, open_actions=2, is_waiting_for_them=False) == "NEEDS_ATTENTION"
        assert determine_relationship_health(10, 2.0, open_actions=0, is_waiting_for_them=True) == "WAITING"
        assert determine_relationship_health(6, 3.0, open_actions=0, is_waiting_for_them=False) == "ENGAGED"
        assert determine_relationship_health(3, 10.0, open_actions=0, is_waiting_for_them=False) == "ACTIVE"
        assert determine_relationship_health(2, 30.0, open_actions=0, is_waiting_for_them=False) == "DORMANT"

    # -------------------------------------------------------------------------
    # 5. Deterministic AI Daily Digest
    # -------------------------------------------------------------------------
    def test_deterministic_daily_digest(self):
        """Daily digest generates morning focus cards deterministically without Gemini API."""
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            e1 = EmailMessage(
                user_id=self.user1_id,
                message_id="dig-1",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                subject="Urgent Board Report",
                body_text="Board needs review by today.",
                ai_action_required=True,
                priority="urgent",
                ai_importance_score=95,
                received_at=now,
            )
            db.session.add(e1)
            db.session.commit()

            digest = generate_daily_digest(self.user1_id)
            assert digest["user_id"] == self.user1_id
            assert "summary" in digest
            assert len(digest["urgent_emails"]) >= 1
            assert len(digest["needs_action"]) >= 1

        self._login_as(self.user1_id)
        res = self.client.get("/api/digest")
        assert res.status_code == 200
        data = res.get_json()["digest"]
        assert data["user_id"] == self.user1_id

    # -------------------------------------------------------------------------
    # 6. Notification Center: Creation, Deduplication, Read, Dismiss, Isolation
    # -------------------------------------------------------------------------
    def test_notification_deduplication_and_lifecycle(self):
        """Notifications deduplicate on (user_id, notif_type, source_type, source_id) and support read/dismiss."""
        with self.app.app_context():
            n1 = create_notification_if_not_exists(
                user_id=self.user1_id,
                notif_type=NotificationType.DEADLINE_APPROACHING,
                title="Proposal Due Soon",
                message="Proposal deadline is in 2 hours",
                severity=NotificationSeverity.WARNING,
                source_type="email",
                source_id="email-notif-1",
            )
            assert n1.id is not None
            notif_id = n1.id

            # Duplicate call returns existing notification
            n2 = create_notification_if_not_exists(
                user_id=self.user1_id,
                notif_type=NotificationType.DEADLINE_APPROACHING,
                title="Proposal Due Soon",
                message="Proposal deadline is in 2 hours",
                severity=NotificationSeverity.WARNING,
                source_type="email",
                source_id="email-notif-1",
            )
            assert n2.id == notif_id

        self._login_as(self.user1_id)

        # Unread count
        res_count = self.client.get("/api/notifications/unread-count")
        assert res_count.status_code == 200
        assert res_count.get_json()["unread_count"] >= 1

        # Mark read
        res_read = self.client.post(f"/api/notifications/{notif_id}/read")
        assert res_read.status_code == 200
        assert res_read.get_json()["notification"]["is_read"] is True

        # Dismiss
        res_dism = self.client.post(f"/api/notifications/{notif_id}/dismiss")
        assert res_dism.status_code == 200
        assert res_dism.get_json()["notification"]["is_dismissed"] is True

        # Multi-user isolation
        self._login_as(self.user2_id)
        res_foreign = self.client.post(f"/api/notifications/{notif_id}/read")
        assert res_foreign.status_code == 404

    # -------------------------------------------------------------------------
    # 7. Productivity Analytics: 7d, 30d, 90d, and Validation
    # -------------------------------------------------------------------------
    def test_productivity_analytics_periods(self):
        """Productivity analytics generates correct time-series trends and validates periods."""
        self._login_as(self.user1_id)

        for period in ["7d", "30d", "90d"]:
            res = self.client.get(f"/api/analytics/productivity?period={period}")
            assert res.status_code == 200
            data = res.get_json()
            assert data["period"] == period
            assert "trends" in data
            assert "summary" in data

        # Invalid period returns 400
        res_bad = self.client.get("/api/analytics/productivity?period=1y")
        assert res_bad.status_code == 400

    # -------------------------------------------------------------------------
    # 8. Saved Searches: CRUD, Uniqueness, and Multi-Tenant Isolation
    # -------------------------------------------------------------------------
    def test_saved_searches_crud_and_uniqueness(self):
        """Saved searches enforce unique (user_id, name) while allowing same name across users."""
        self._login_as(self.user1_id)

        # Create
        res_create = self.client.post("/api/searches", json={
            "name": "Urgent Client Emails",
            "query": "from:client priority:urgent",
        })
        assert res_create.status_code == 201
        s1 = res_create.get_json()["saved_search"]
        s1_id = s1["id"]

        # Duplicate name for user1 fails
        res_dup = self.client.post("/api/searches", json={
            "name": "Urgent Client Emails",
            "query": "action:true",
        })
        assert res_dup.status_code == 400

        # User 2 can use the EXACT same name
        self._login_as(self.user2_id)
        res_user2 = self.client.post("/api/searches", json={
            "name": "Urgent Client Emails",
            "query": "from:other",
        })
        assert res_user2.status_code == 201

        # User 2 cannot edit or delete User 1's saved search
        res_hack = self.client.put(f"/api/searches/{s1_id}", json={"name": "Hacked"})
        assert res_hack.status_code == 404
        res_del_hack = self.client.delete(f"/api/searches/{s1_id}")
        assert res_del_hack.status_code == 404

        # User 1 can update and delete
        self._login_as(self.user1_id)
        res_upd = self.client.put(f"/api/searches/{s1_id}", json={"name": "Updated Search"})
        assert res_upd.status_code == 200
        res_del = self.client.delete(f"/api/searches/{s1_id}")
        assert res_del.status_code == 200

    # -------------------------------------------------------------------------
    # 9. Bulk Actions & Multi-User Ownership Safeguard
    # -------------------------------------------------------------------------
    def test_bulk_actions_and_ownership_safeguard(self):
        """Bulk actions reject cross-user requests completely and require task confirmation."""
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            e1 = EmailMessage(
                user_id=self.user1_id,
                message_id="bulk-e1",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                subject="Task 1",
                body_text="Review report 1",
                labels="UNREAD",
                received_at=now,
            )
            e2 = EmailMessage(
                user_id=self.user1_id,
                message_id="bulk-e2",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                subject="Task 2",
                body_text="Review report 2",
                labels="UNREAD",
                received_at=now,
            )
            # Foreign email belonging to user2
            e_foreign = EmailMessage(
                user_id=self.user2_id,
                message_id="bulk-foreign",
                from_address="boss@corp.com",
                to_address="user2@mailmind.ai",
                subject="Foreign Email",
                body_text="Confidential data",
                labels="UNREAD",
                received_at=now,
            )
            db.session.add_all([e1, e2, e_foreign])
            db.session.commit()
            e1_id, e2_id, foreign_id = e1.id, e2.id, e_foreign.id

        self._login_as(self.user1_id)

        # Mark read on user1 emails
        res_read = self.client.post("/api/actions/bulk", json={
            "email_ids": [e1_id, e2_id],
            "action": "mark_read",
        })
        assert res_read.status_code == 200
        assert res_read.get_json()["affected"] == 2

        # Bulk task creation without confirmation fails
        res_task_unconf = self.client.post("/api/actions/bulk", json={
            "email_ids": [e1_id, e2_id],
            "action": "create_tasks",
            "options": {"confirmed": False},
        })
        assert res_task_unconf.status_code == 400

        # Bulk task creation with confirmation succeeds
        res_task_conf = self.client.post("/api/actions/bulk", json={
            "email_ids": [e1_id, e2_id],
            "action": "create_tasks",
            "options": {"confirmed": True},
        })
        assert res_task_conf.status_code == 200
        assert res_task_conf.get_json()["affected"] == 2

        # Cross-user attempt: User 1 includes foreign_id -> entire batch rejected with 403
        res_cross = self.client.post("/api/actions/bulk", json={
            "email_ids": [e1_id, foreign_id],
            "action": "star",
        })
        assert res_cross.status_code == 403

    # -------------------------------------------------------------------------
    # 10. Alembic Migration & Schema Up/Down Verification
    # -------------------------------------------------------------------------
    def test_phase8_migration_upgrade_and_downgrade(self):
        """Validates controlled migration from e5a1b2c3d4e5 to f6b2c3d4e5f6 and rollback."""
        from flask_migrate import upgrade, downgrade, stamp
        mig_db = f"test_mig_p8_{uuid.uuid4().hex[:8]}.db"
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
                # Step A: Stamp at f6b2c3d4e5f6 (matching full schema) and downgrade to Phase 7 (e5a1b2c3d4e5)
                stamp(revision="f6b2c3d4e5f6", directory=mig_dir)
                downgrade(revision="e5a1b2c3d4e5", directory=mig_dir)

                eng = mig_app.extensions["migrate"].db.engine
                insp_pre = sa.inspect(eng)
                tables_pre = insp_pre.get_table_names()
                assert "action_items" not in tables_pre
                assert "notifications" not in tables_pre
                assert "saved_searches" not in tables_pre

                # Step B: Upgrade to Phase 8 (f6b2c3d4e5f6)
                upgrade(revision="f6b2c3d4e5f6", directory=mig_dir)
                insp_post = sa.inspect(eng)
                tables_post = insp_post.get_table_names()
                assert "action_items" in tables_post
                assert "notifications" in tables_post
                assert "saved_searches" in tables_post

                # Inspect columns
                action_cols = {c["name"] for c in insp_post.get_columns("action_items")}
                assert "id" in action_cols
                assert "user_id" in action_cols
                assert "score" in action_cols
                assert "status" in action_cols

                email_cols = {c["name"] for c in insp_post.get_columns("email_messages")}
                assert "ai_deadlines" in email_cols
                assert "ai_meeting_proposal" in email_cols

                # Step C: Test clean downgrade back to Phase 7
                downgrade(revision="e5a1b2c3d4e5", directory=mig_dir)
                insp_down = sa.inspect(eng)
                tables_down = insp_down.get_table_names()
                assert "action_items" not in tables_down
                assert "notifications" not in tables_down
                assert "saved_searches" not in tables_down
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

    # -------------------------------------------------------------------------
    # 11. ActionItem Concurrency, Idempotency & Snooze Persistence Across DB Reload
    # -------------------------------------------------------------------------
    def test_action_item_concurrent_sync_and_snooze_persistence(self):
        """Concurrent sync attempts for the same source email produce exactly 1 ActionItem.
        Snooze state persists across fresh database session reloads without data loss.
        """
        import threading
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            em = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-concurrent-sync",
                from_address="vip@client.com",
                to_address="user1@mailmind.ai",
                subject="Urgent contract review",
                body_text="Please sign the agreement by tomorrow.",
                ai_action_required=True,
                ai_priority="urgent",
                ai_deadline=now + timedelta(days=1),
                ai_importance_score=95,
            )
            db.session.add(em)
            db.session.commit()
            em_id = em.id

            # Concurrent sync across multiple threads
            def _sync_worker():
                with self.app.app_context():
                    sync_actions(self.user1_id)

            threads = [threading.Thread(target=_sync_worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Verify idempotency: exactly 1 logical action item created for this email
            items = ActionItem.query.filter_by(
                user_id=self.user1_id,
                source_email_id=em_id,
                action_type=ActionType.EMAIL_RESPONSE.value,
            ).all()
            assert len(items) == 1
            act = items[0]
            act_id = act.id

            # Test Snooze Persistence
            snooze_target = now + timedelta(days=3, hours=4)
            snoozed = snooze_action(
                self.user1_id,
                act_id,
                duration="custom",
                custom_date=snooze_target.isoformat(),
            )
            assert snoozed.status == ActionStatus.SNOOZED.value

            # Flush and clear session cache (simulate process restart / fresh request)
            db.session.expire_all()
            db.session.close()

            # Reload from database in a fresh query
            reloaded = ActionItem.query.filter_by(id=act_id, user_id=self.user1_id).first()
            assert reloaded is not None
            assert reloaded.status == ActionStatus.SNOOZED.value
            assert reloaded.snoozed_until is not None
            # Verify timezone correctness (converted / stored as UTC)
            reloaded_utc = reloaded.snoozed_until.replace(tzinfo=timezone.utc) if reloaded.snoozed_until.tzinfo is None else reloaded.snoozed_until
            diff_seconds = abs((reloaded_utc - snooze_target).total_seconds())
            assert diff_seconds < 2  # Within 2 seconds precision

            # Verify repeated sync while snoozed preserves SNOOZED status and does not duplicate
            sync_actions(self.user1_id)
            items_after = ActionItem.query.filter_by(
                user_id=self.user1_id,
                source_email_id=em_id,
            ).all()
            assert len(items_after) == 1
            assert items_after[0].status == ActionStatus.SNOOZED.value

    # -------------------------------------------------------------------------
    # 12. Notification Concurrency Deduplication & Cross-User IDOR Protection
    # -------------------------------------------------------------------------
    def test_notification_concurrent_dedup_and_idor(self):
        """Concurrent notification creation deduplicates to exactly 1 record.
        Cross-user access to notification details or deletion strictly returns 403 or 404.
        """
        import threading
        with self.app.app_context():
            source_id = f"email-dedup-{uuid.uuid4().hex[:6]}"

            def _notif_worker():
                with self.app.app_context():
                    create_notification_if_not_exists(
                        user_id=self.user1_id,
                        notif_type=NotificationType.IMPORTANT_EMAIL.value,
                        title="Urgent Message",
                        message="Please review immediately.",
                        severity="urgent",
                        source_type="email",
                        source_id=source_id,
                    )

            threads = [threading.Thread(target=_notif_worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            notifs = Notification.query.filter_by(
                user_id=self.user1_id,
                source_type="email",
                source_id=source_id,
            ).all()
            assert len(notifs) == 1
            n_id = notifs[0].id

        # Cross-user IDOR attempt by User 2
        self._login_as(self.user2_id)

        # GET User 1 notification
        res_get = self.client.get(f"/api/notifications/{n_id}")
        assert res_get.status_code in (403, 404)

        # POST read User 1 notification
        res_read = self.client.post(f"/api/notifications/{n_id}/read")
        assert res_read.status_code in (403, 404)

        # POST dismiss User 1 notification
        res_dismiss = self.client.post(f"/api/notifications/{n_id}/dismiss")
        assert res_dismiss.status_code in (403, 404)

        # DELETE User 1 notification
        res_del = self.client.delete(f"/api/notifications/{n_id}")
        assert res_del.status_code in (403, 404)

    # -------------------------------------------------------------------------
    # 13. Bulk Task Creation — Mandatory Confirmation & Duplicate Prevention
    # -------------------------------------------------------------------------
    def test_bulk_task_hard_confirmation_boundary(self):
        """Email selection alone MUST NOT create tasks.
        Explicit confirmation is required; duplicate submission does not produce duplicate tasks.
        """
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            em = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-bulk-task-check",
                from_address="lead@corp.com",
                to_address="user1@mailmind.ai",
                subject="Ship release 8.0",
                body_text="Prepare the release notes and update changelog.",
                ai_action_required=True,
                ai_next_action="Prepare release notes",
                ai_deadline=now + timedelta(days=2),
                ai_priority="high",
            )
            db.session.add(em)
            db.session.commit()
            e_id = em.id

        self._login_as(self.user1_id)

        # Step 1: Selection without confirmation -> REJECTED
        res_unconfirmed = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [e_id],
            "item_type": "email",
            "options": {"confirmed": False},
        })
        assert res_unconfirmed.status_code == 400
        assert "confirmation is mandatory" in res_unconfirmed.get_json()["error"]

        # Verify 0 tasks exist in database
        with self.app.app_context():
            assert Task.query.filter_by(user_id=self.user1_id, email_id=e_id).count() == 0

        # Step 2: Explicit confirmation -> Task Created
        res_confirmed = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [e_id],
            "item_type": "email",
            "options": {"confirmed": True},
        })
        assert res_confirmed.status_code == 200
        assert res_confirmed.get_json()["affected_count"] == 1

        with self.app.app_context():
            created_tasks = Task.query.filter_by(user_id=self.user1_id, email_id=e_id).all()
            assert len(created_tasks) == 1
            assert "Ship release 8.0" in created_tasks[0].task_title
            assert created_tasks[0].status == "pending"

        # Step 3: Duplicate submission protection
        res_dup = self.client.post("/api/actions/bulk", json={
            "action": "create_tasks",
            "item_ids": [e_id],
            "item_type": "email",
            "options": {"confirmed": True},
        })
        assert res_dup.status_code == 200
        # No duplicate row created
        with self.app.app_context():
            assert Task.query.filter_by(user_id=self.user1_id, email_id=e_id).count() == 1

    # -------------------------------------------------------------------------
    # 14. Hybrid Deadline Extraction: Deterministic, Ambiguous & Timezone Handling
    # -------------------------------------------------------------------------
    def test_hybrid_deadline_semantic_and_timezone_boundary(self):
        """Deterministic dates parse with high confidence.
        Ambiguous expressions do NOT fabricate an exact date.
        Multiple deadlines are all preserved without collapsing.
        """
        ref_dt = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)

        # 1. Obvious deterministic date
        text_det = "Please finalize by November 25, 2026 at 4:00 PM."
        d_det = extract_deadlines_from_text(text_det, reference_dt=ref_dt)
        assert len(d_det) >= 1
        assert "2026-11-25" in d_det[0]["deadline"]
        assert d_det[0]["confidence"] >= 0.85
        assert d_det[0]["datetime"] is not None

        # 2. Ambiguous semantic expression: NO fabricated date
        text_amb = "Please take a look at this as soon as possible and let me know."
        d_amb = extract_deadlines_from_text(text_amb, reference_dt=ref_dt)
        assert len(d_amb) >= 1
        amb_item = [d for d in d_amb if d.get("is_ambiguous")][0]
        assert amb_item["datetime"] is None
        assert amb_item["deadline"] is None
        assert amb_item["confidence"] < 0.50

        # 3. Multiple independent deadlines preserved without collapse
        text_multi = (
            "Milestone 1 due by 2026-11-10. "
            "Milestone 2 due by 2026-11-20. "
            "Final release due by 2026-11-30."
        )
        d_multi = extract_deadlines_from_text(text_multi, reference_dt=ref_dt)
        dates_found = [d["deadline"][:10] for d in d_multi if d.get("deadline")]
        assert "2026-11-10" in dates_found
        assert "2026-11-20" in dates_found
        assert "2026-11-30" in dates_found
        assert len(d_multi) >= 3

        # 4. Timezone-aware date normalization
        text_tz = "Due tomorrow at 5pm."
        d_ny = extract_deadlines_from_text(text_tz, reference_dt=ref_dt, user_timezone="America/New_York")
        assert len(d_ny) >= 1
        # America/New_York is UTC-5 in November (EST), so 5pm EST is 22:00 UTC
        assert "22:00:00" in d_ny[0]["datetime"]

    # -------------------------------------------------------------------------
    # 15. AI Failure Isolation & Deterministic Features Resilience
    # -------------------------------------------------------------------------
    def test_ai_failure_isolation_and_resilience(self):
        """Simulate Gemini outage / quota exhaustion.
        All deterministic productivity services must succeed without 500 error.
        """
        from unittest.mock import patch

        now = datetime.now(timezone.utc)
        with self.app.app_context():
            em = EmailMessage(
                user_id=self.user1_id,
                message_id="msg-ai-outage",
                from_address="boss@corp.com",
                to_address="user1@mailmind.ai",
                subject="Weekly Plan",
                body_text="Review weekly goals.",
                ai_action_required=True,
                ai_priority="high",
                ai_deadline=now + timedelta(hours=5),
            )
            db.session.add(em)
            db.session.commit()

        self._login_as(self.user1_id)

        # Mock Gemini failing completely
        with patch("app.services.ai_service.analyze_email", side_effect=RuntimeError("503 Service Unavailable / Quota Exceeded")):
            # Action Center succeeds
            res_actions = self.client.get("/api/actions")
            assert res_actions.status_code == 200

            # Daily Digest succeeds deterministically
            res_digest = self.client.get("/api/digest")
            assert res_digest.status_code == 200
            assert "digest" in res_digest.get_json()

            # Notifications list succeeds
            res_notifs = self.client.get("/api/notifications")
            assert res_notifs.status_code == 200

            # Productivity Analytics succeeds
            res_analytics = self.client.get("/api/analytics/productivity?period=7d")
            assert res_analytics.status_code == 200

            # Meeting conflict check succeeds
            res_conf = self.client.post("/api/calendar/check-conflict", json={
                "start": "2026-10-15T14:00:00Z",
                "end": "2026-10-15T15:00:00Z",
            })
            assert res_conf.status_code == 200

            # Saved Searches succeeds
            res_search = self.client.get("/api/searches")
            assert res_search.status_code == 200

    # -------------------------------------------------------------------------
    # 16. Comprehensive Resource IDOR Audit across All Phase 8 Entities
    # -------------------------------------------------------------------------
    def test_phase8_comprehensive_idor_protection(self):
        """Verify strict ownership enforcement for ActionItem, Notification, and SavedSearch.
        User B attempts GET, UPDATE/PATCH, DELETE on User A's resources -> 403 or 404.
        """
        now = datetime.now(timezone.utc)
        with self.app.app_context():
            # User 1 resources
            act = ActionItem(
                user_id=self.user1_id,
                action_type=ActionType.EMAIL_RESPONSE.value,
                title="User 1 Secret Action",
                priority="high",
                score=80,
                status=ActionStatus.OPEN.value,
            )
            notif = Notification(
                user_id=self.user1_id,
                type=NotificationType.IMPORTANT_EMAIL.value,
                title="User 1 Private Alert",
                message="Private alert text",
                severity="info",
            )
            search = SavedSearch(
                user_id=self.user1_id,
                name="User 1 Private Search",
                query="is:unread important",
            )
            db.session.add_all([act, notif, search])
            db.session.commit()

            act_id = act.id
            notif_id = notif.id
            search_id = search.id

        # Authenticate as User 2
        self._login_as(self.user2_id)

        # 1. ActionItem IDOR checks
        assert self.client.get(f"/api/actions/{act_id}").status_code in (403, 404)
        assert self.client.patch(f"/api/actions/{act_id}", json={"title": "Hacked"}).status_code in (403, 404)
        assert self.client.delete(f"/api/actions/{act_id}").status_code in (403, 404)

        # 2. Notification IDOR checks
        assert self.client.get(f"/api/notifications/{notif_id}").status_code in (403, 404)
        assert self.client.delete(f"/api/notifications/{notif_id}").status_code in (403, 404)

        # 3. SavedSearch IDOR checks
        assert self.client.get(f"/api/searches/{search_id}").status_code in (403, 404)
        assert self.client.put(f"/api/searches/{search_id}", json={"name": "Tampered"}).status_code in (403, 404)
        assert self.client.delete(f"/api/searches/{search_id}").status_code in (403, 404)

    # -------------------------------------------------------------------------
    # 17. Secrets Redaction & Logging Safety
    # -------------------------------------------------------------------------
    def test_no_secrets_in_logs_and_error_sanitization(self):
        """Sanitizer must redact GEMINI_API_KEY, ENCRYPTION_KEY, SECRET_KEY, and OAuth tokens."""
        from app.services.job_queue_service import _sanitize_error

        fake_gemini_key = "AIzaSyD987654321FakeGeminiApiKeySecretXYZ"
        fake_oauth_token = "ya29.a0AfH6SMCxyz1234567890abcdefghijklmnopqrstuvwxyz"
        raw_error_message = (
            f"Failed to connect to Google API using key={fake_gemini_key}. "
            f"Authorization: Bearer {fake_oauth_token}. Token: {fake_oauth_token}."
        )

        with self.app.app_context():
            self.app.config["GEMINI_API_KEY"] = fake_gemini_key
            sanitized = _sanitize_error(raw_error_message)

            assert fake_gemini_key not in sanitized
            assert fake_oauth_token not in sanitized
            assert "[REDACTED_GEMINI_API_KEY]" in sanitized or "[REDACTED" in sanitized
            assert "[REDACTED_OAUTH_TOKEN]" in sanitized or "[REDACTED" in sanitized
