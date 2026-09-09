"""
Phase 5 Tests — Smart Tasks & Calendar Intelligence Hardening Suite

Covers 14 core sections according to specification:
Section 1: Task Creation
    - test_manual_task_creation: Manual task creation with explicit fields.
    - test_manual_task_null_email_id_valid: Explicit null email_id creates manual task.
    - test_email_linked_task_creation: Email-linked task creation maintains email_id and ownership.
Section 2: Task Ownership
    - test_task_ownership_isolation: User A cannot view, update, complete, reopen, or delete User B's task.
    - test_task_client_supplied_user_id_ignored: Client user_id in payload cannot override authenticated ownership.
Section 3: Task Lifecycle
    - test_task_update: Updates modify fields and verify ownership.
    - test_task_completion: Task completion sets status=completed and completed_at.
    - test_task_reopen: Task reopen sets status=in_progress and clears completed_at.
    - test_reopen_resets_completed_at_timestamp: Repeated completion and reopening cycles clear timestamp correctly.
Section 4: Task Validation
    - test_task_status_validation_invalid_rejected: Rejects statuses like 'done', 'random', 'COMPLETE'.
    - test_task_priority_validation_invalid_rejected: Rejects priorities like 'super_urgent'.
    - test_task_invalid_due_date_rejected: Rejects malformed due_date strings.
Section 5: Task Filters & Overdue / Due-Today Boundaries
    - test_overdue_task_detection: Detects past-due incomplete tasks and excludes completed/cancelled tasks.
    - test_overdue_statuses_logic: Verifies pending, in_progress, completed, cancelled, and future overdue rules.
    - test_task_filters_due_today_boundaries: Deterministic testing of yesterday, today 00:00, today 23:59, tomorrow 00:00, tomorrow.
Section 6: Task / Email Relationships & Duplicates
    - test_email_related_tasks: Email detail exposes linked tasks.
    - test_duplicate_ai_task_confirmation_protection: Exact duplicate confirmation returns 409 and is_duplicate=True.
    - test_duplicate_legitimate_tasks_allowed: Distinct task titles for same email are allowed.
    - test_cross_user_email_cannot_create_task: User A cannot create task linked to User B's email.
    - test_deadline_inheritance_from_ai_deadline: Inherits email ai_deadline when no explicit due_date provided.
    - test_explicit_deadline_overrides_ai_deadline: Explicit due_date takes precedence over email ai_deadline.
    - test_task_source_email_resolution: Task GET returns source email metadata.
Section 7: Calendar Creation
    - test_manual_calendar_event_creation: Manual calendar event created with valid start/end.
    - test_manual_calendar_null_email_id_valid: Explicit null email_id creates manual event.
    - test_email_linked_calendar_event_creation: Event linked to email persists email_id and metadata.
Section 8: Calendar Ownership
    - test_calendar_ownership_isolation: User A cannot view, update, or delete User B's calendar event.
    - test_cross_user_email_cannot_create_calendar_event: User A cannot link event to User B's email (403).
    - test_calendar_client_supplied_user_id_ignored: Client user_id in payload cannot override authenticated ownership.
Section 9: Calendar Time Validation
    - test_calendar_validation_end_before_start: Case A - end < start rejected with 400.
    - test_calendar_validation_end_equals_start: Case B - end == start rejected with 400.
    - test_calendar_validation_missing_start: Case C - missing start rejected with 400.
    - test_calendar_validation_missing_end: Case D - missing end rejected with 400.
    - test_calendar_validation_invalid_start_format: Case E - malformed start datetime rejected with 400.
    - test_calendar_validation_invalid_end_format: Case F - malformed end datetime rejected with 400.
Section 10: Calendar Conflicts & Formula Verification
    - test_calendar_conflict_formula_overlap: Overlapping intervals correctly detected as conflicts.
    - test_calendar_conflict_formula_boundary_touching_no_conflict: Touching intervals (10:00-11:00 & 11:00-12:00) do NOT conflict.
    - test_calendar_cross_user_conflicts_isolated: User A event does not conflict with User B overlapping event.
    - test_calendar_event_update_conflict_detection: Moving event into overlapping range reports conflict.
    - test_calendar_event_self_conflict_exclusion: Updating event metadata without moving range does NOT report self-conflict.
Section 11: AI Safety & Autonomous-Write Protection
    - test_ai_analysis_alone_does_not_create_task: AI service suggestions do not write Task to DB.
    - test_ai_analysis_alone_does_not_create_calendar_event: AI service suggestions do not write CalendarEvent to DB.
    - test_ai_analysis_endpoint_does_not_create_task: POST /api/emails/<id>/analyze does not insert Task.
    - test_ai_analysis_endpoint_does_not_create_calendar_event: POST /api/emails/<id>/analyze does not insert CalendarEvent.
    - test_ai_analysis_cross_user_forbidden: User A cannot analyze User B's email (403/404) and no Task/Event created.
Section 12: Human Confirmation Flow
    - test_human_confirmation_required_for_tasks_and_calendar: Suggestion storage followed by explicit user POST creates objects.
Section 13: Dashboard Isolation & Source Data Integrity
    - test_dashboard_stats_and_isolation: Dashboard metrics strictly isolate User A and User B data.
    - test_task_and_calendar_deletion_leaves_email_intact: Deleting task and event never deletes source email message.
Section 14: Unauthenticated Security Tests
    - test_unauthenticated_phase5_endpoints_rejected: Rejects unauthenticated requests with 401 on all Phase 5 endpoints.
"""

import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.services.encryption import encrypt_token


class TestPhase5Config(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-phase5-secret-key"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"
    GEMINI_API_KEY = "mock-test-gemini-key"
    GEMINI_MODEL = "gemini-2.0-flash"


class TestPhase5TasksAndCalendar(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestPhase5Config)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # User A
            self.user_a = User(
                email="alice@mailmild.com",
                name="Alice Analyst",
                provider="google",
            )
            db.session.add(self.user_a)

            # User B
            self.user_b = User(
                email="bob@mailmild.com",
                name="Bob Bystander",
                provider="google",
            )
            db.session.add(self.user_b)
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            # User A's connected account & email
            self.acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="gmail_alice",
                email_address="alice@gmail.com",
                encrypted_access_token=encrypt_token("tok-a"),
                encrypted_refresh_token=encrypt_token("ref-a"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                history_id="1000",
                messages_synced=1,
            )
            db.session.add(self.acc_a)
            db.session.commit()
            self.acc_a_id = self.acc_a.id

            self.email_a = EmailMessage(
                user_id=self.user_a_id,
                connected_account_id=self.acc_a_id,
                message_id="msg-alice-001",
                provider_message_id="pmsg-alice-001",
                subject="Q3 Product Review and Next Steps",
                body_text="Please submit the slides by Friday September 15. The sync is at 3 PM.",
                from_address="boss@company.com",
                to_address="alice@gmail.com",
                received_at=datetime.now(timezone.utc),
                ai_status="completed",
                ai_action_required=True,
                ai_deadline=datetime.now(timezone.utc) + timedelta(days=5),
            )
            db.session.add(self.email_a)

            # User B's connected account & email
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                provider_account_id="gmail_bob",
                email_address="bob@gmail.com",
                encrypted_access_token=encrypt_token("tok-b"),
                encrypted_refresh_token=encrypt_token("ref-b"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                history_id="2000",
                messages_synced=1,
            )
            db.session.add(self.acc_b)
            db.session.commit()
            self.acc_b_id = self.acc_b.id

            self.email_b = EmailMessage(
                user_id=self.user_b_id,
                connected_account_id=self.acc_b_id,
                message_id="msg-bob-001",
                provider_message_id="pmsg-bob-001",
                subject="Bob Private Email",
                body_text="Private details for Bob only.",
                from_address="someone@company.com",
                to_address="bob@gmail.com",
                received_at=datetime.now(timezone.utc),
            )
            db.session.add(self.email_b)
            db.session.commit()

            self.email_a_id = self.email_a.id
            self.email_b_id = self.email_b.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _login_as(self, user_id: str):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    # ─────────────────────────────────────────────────────────────
    # Section 1: Task Creation
    # ─────────────────────────────────────────────────────────────

    def test_manual_task_creation(self):
        """1.1 Manual task creation without email (email_id = None) succeeds."""
        self._login_as(self.user_a_id)

        due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        resp = self.client.post("/api/tasks", json={
            "email_id": None,
            "title": "Study for interview",
            "description": "Complete DSA revision",
            "due_date": due,
            "priority": "high",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["task"]["title"], "Study for interview")
        self.assertIsNone(data["task"]["email_id"])
        self.assertEqual(data["task"]["user_id"], self.user_a_id)
        self.assertEqual(data["task"]["status"], "pending")

    def test_manual_task_null_email_id_valid(self):
        """1.2 Explicit email_id=None returns 201, task.email_id=null, user_id=User A."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "email_id": None,
            "title": "Standalone Prep Task",
            "priority": "medium",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["task"]
        self.assertIsNone(data["email_id"])
        self.assertEqual(data["user_id"], self.user_a_id)
        self.assertEqual(data["title"], "Standalone Prep Task")

        with self.app.app_context():
            saved = db.session.get(Task, data["id"])
            self.assertIsNotNone(saved)
            self.assertIsNone(saved.email_id)
            self.assertEqual(saved.user_id, self.user_a_id)

    def test_email_linked_task_creation(self):
        """1.3 Email-linked task creation maintains email_id and ownership."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Email Action Item",
            "priority": "high",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["task"]
        self.assertEqual(data["email_id"], self.email_a_id)
        self.assertEqual(data["user_id"], self.user_a_id)

    # ─────────────────────────────────────────────────────────────
    # Section 2: Task Ownership
    # ─────────────────────────────────────────────────────────────

    def test_task_ownership_isolation(self):
        """2.1 User A cannot view, update, complete, reopen, or delete User B's task."""
        # Create task for User B
        self._login_as(self.user_b_id)
        resp_b = self.client.post("/api/tasks", json={
            "title": "Bob's Confidential Task",
            "priority": "urgent"
        })
        self.assertEqual(resp_b.status_code, 201)
        task_b_id = resp_b.get_json()["task"]["id"]

        # User A attempts to access User B's task
        self._login_as(self.user_a_id)

        # User A list should not contain User B's task
        list_resp = self.client.get("/api/tasks")
        self.assertEqual(list_resp.status_code, 200)
        task_ids = [t["id"] for t in list_resp.get_json()["tasks"]]
        self.assertNotIn(task_b_id, task_ids)

        # GET User B's task directly returns 404
        self.assertEqual(self.client.get(f"/api/tasks/{task_b_id}").status_code, 404)

        # PATCH User B's task directly returns 404
        self.assertEqual(self.client.patch(f"/api/tasks/{task_b_id}", json={"title": "Hacked"}).status_code, 404)

        # Complete User B's task directly returns 404
        self.assertEqual(self.client.post(f"/api/tasks/{task_b_id}/complete").status_code, 404)

        # Reopen User B's task directly returns 404
        self.assertEqual(self.client.post(f"/api/tasks/{task_b_id}/reopen").status_code, 404)

        # DELETE User B's task directly returns 404
        self.assertEqual(self.client.delete(f"/api/tasks/{task_b_id}").status_code, 404)

        # Confirm Bob's task is intact in DB
        with self.app.app_context():
            bob_task = db.session.get(Task, task_b_id)
            self.assertIsNotNone(bob_task)
            self.assertEqual(bob_task.task_title, "Bob's Confidential Task")
            self.assertEqual(bob_task.user_id, self.user_b_id)

    def test_task_client_supplied_user_id_ignored(self):
        """2.2 Client-supplied user_id in JSON cannot hijack task ownership."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "user_id": self.user_b_id,
            "title": "Spoofed Ownership Task",
            "priority": "low"
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["task"]
        # Must be assigned to authenticated user A, ignoring payload user_b_id
        self.assertEqual(data["user_id"], self.user_a_id)

    # ─────────────────────────────────────────────────────────────
    # Section 3: Task Lifecycle
    # ─────────────────────────────────────────────────────────────

    def test_task_update(self):
        """3.1 Task update modifies fields and preserves ownership."""
        self._login_as(self.user_a_id)
        create_resp = self.client.post("/api/tasks", json={
            "title": "Initial Title",
            "priority": "low"
        })
        task_id = create_resp.get_json()["task"]["id"]

        update_resp = self.client.patch(f"/api/tasks/{task_id}", json={
            "title": "Updated Title",
            "description": "Updated Description",
            "priority": "urgent",
        })
        self.assertEqual(update_resp.status_code, 200)
        updated_data = update_resp.get_json()["task"]
        self.assertEqual(updated_data["title"], "Updated Title")
        self.assertEqual(updated_data["description"], "Updated Description")
        self.assertEqual(updated_data["priority"], "Urgent")

    def test_task_completion(self):
        """3.2 Task completion sets status=completed and completed_at != None."""
        self._login_as(self.user_a_id)
        create_resp = self.client.post("/api/tasks", json={"title": "Finish Report"})
        task_id = create_resp.get_json()["task"]["id"]

        comp_resp = self.client.post(f"/api/tasks/{task_id}/complete")
        self.assertEqual(comp_resp.status_code, 200)
        data = comp_resp.get_json()["task"]
        self.assertEqual(data["status"], "completed")
        self.assertIsNotNone(data["completed_at"])

    def test_task_reopen(self):
        """3.3 Task reopen sets status=in_progress and completed_at = None."""
        self._login_as(self.user_a_id)
        create_resp = self.client.post("/api/tasks", json={"title": "Review PR"})
        task_id = create_resp.get_json()["task"]["id"]

        self.client.post(f"/api/tasks/{task_id}/complete")
        reopen_resp = self.client.post(f"/api/tasks/{task_id}/reopen")
        self.assertEqual(reopen_resp.status_code, 200)
        data = reopen_resp.get_json()["task"]
        self.assertEqual(data["status"], "in_progress")
        self.assertIsNone(data["completed_at"])

    def test_reopen_resets_completed_at_timestamp(self):
        """3.4 Completing then reopening a task clears completed_at timestamp."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={"title": "Timestamp Test"})
        task_id = resp.get_json()["task"]["id"]

        self.client.post(f"/api/tasks/{task_id}/complete")
        with self.app.app_context():
            t = db.session.get(Task, task_id)
            self.assertIsNotNone(t.completed_at)

        self.client.post(f"/api/tasks/{task_id}/reopen")
        with self.app.app_context():
            t = db.session.get(Task, task_id)
            self.assertIsNone(t.completed_at)
            self.assertEqual(t.status, "in_progress")

    # ─────────────────────────────────────────────────────────────
    # Section 4: Task Validation
    # ─────────────────────────────────────────────────────────────

    def test_task_status_validation_invalid_rejected(self):
        """4.1 Invalid status values ('done', 'random', 'COMPLETE') are rejected with 400."""
        self._login_as(self.user_a_id)

        for bad_status in ["done", "random", "COMPLETE", ""]:
            resp = self.client.post("/api/tasks", json={
                "title": f"Bad Status {bad_status}",
                "status": bad_status
            })
            self.assertEqual(resp.status_code, 400, f"Expected 400 for status: {bad_status}")
            self.assertIn("error", resp.get_json())

        # Also verify PATCH status validation
        create_resp = self.client.post("/api/tasks", json={"title": "Valid Task"})
        task_id = create_resp.get_json()["task"]["id"]

        patch_resp = self.client.patch(f"/api/tasks/{task_id}", json={"status": "done"})
        self.assertEqual(patch_resp.status_code, 400)

    def test_task_priority_validation_invalid_rejected(self):
        """4.2 Invalid priority values ('super_urgent', 'asap') are rejected with 400."""
        self._login_as(self.user_a_id)

        for bad_priority in ["super_urgent", "asap", "UNKNOWN"]:
            resp = self.client.post("/api/tasks", json={
                "title": f"Bad Priority {bad_priority}",
                "priority": bad_priority
            })
            self.assertEqual(resp.status_code, 400, f"Expected 400 for priority: {bad_priority}")
            self.assertIn("error", resp.get_json())

    def test_task_invalid_due_date_rejected(self):
        """4.3 Invalid due_date format is rejected with 400."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "title": "Bad Due Date Task",
            "due_date": "not-a-valid-datetime"
        })
        self.assertEqual(resp.status_code, 400)

    # ─────────────────────────────────────────────────────────────
    # Section 5: Task Filters & Overdue / Due-Today Boundaries
    # ─────────────────────────────────────────────────────────────

    def test_overdue_task_detection(self):
        """5.1 Overdue task detection identifies past-due incomplete tasks."""
        self._login_as(self.user_a_id)

        # Past due task
        past_due = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        resp1 = self.client.post("/api/tasks", json={
            "title": "Past Due Task",
            "due_date": past_due,
        })
        task1 = resp1.get_json()["task"]
        self.assertTrue(task1["is_overdue"])

        # Completed past due task is NOT overdue
        self.client.post(f"/api/tasks/{task1['id']}/complete")
        get_comp = self.client.get(f"/api/tasks/{task1['id']}")
        self.assertFalse(get_comp.get_json()["task"]["is_overdue"])

        # Future due task is NOT overdue
        future_due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        resp2 = self.client.post("/api/tasks", json={
            "title": "Future Task",
            "due_date": future_due,
        })
        task2 = resp2.get_json()["task"]
        self.assertFalse(task2["is_overdue"])

    def test_overdue_statuses_logic(self):
        """5.2 Pending/in_progress overdue tasks report overdue; completed/cancelled/future do not."""
        self._login_as(self.user_a_id)

        past_due = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        future_due = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()

        # 1. Pending overdue -> overdue
        r1 = self.client.post("/api/tasks", json={"title": "Pending Overdue", "due_date": past_due, "status": "pending"})
        self.assertTrue(r1.get_json()["task"]["is_overdue"])

        # 2. In_progress overdue -> overdue
        r2 = self.client.post("/api/tasks", json={"title": "InProgress Overdue", "due_date": past_due, "status": "in_progress"})
        self.assertTrue(r2.get_json()["task"]["is_overdue"])

        # 3. Completed overdue -> NOT overdue
        r3 = self.client.post("/api/tasks", json={"title": "Completed Overdue", "due_date": past_due, "status": "completed"})
        self.assertFalse(r3.get_json()["task"]["is_overdue"])

        # 4. Cancelled overdue -> NOT overdue
        r4 = self.client.post("/api/tasks", json={"title": "Cancelled Overdue", "due_date": past_due, "status": "cancelled"})
        self.assertFalse(r4.get_json()["task"]["is_overdue"])

        # 5. Future pending -> NOT overdue
        r5 = self.client.post("/api/tasks", json={"title": "Future Pending", "due_date": future_due, "status": "pending"})
        self.assertFalse(r5.get_json()["task"]["is_overdue"])

    def test_task_filters_due_today_boundaries(self):
        """5.3 Deterministic due_today boundary tests: yesterday, today 00:00, today 23:59, tomorrow 00:00, tomorrow."""
        self._login_as(self.user_a_id)

        now_utc = datetime.now(timezone.utc)
        today_0000 = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        today_2359 = now_utc.replace(hour=23, minute=59, second=59, microsecond=0)
        yesterday_1200 = today_0000 - timedelta(days=1, hours=12)
        tomorrow_0000 = today_0000 + timedelta(days=1)
        tomorrow_1200 = today_0000 + timedelta(days=1, hours=12)

        self.client.post("/api/tasks", json={"title": "Task Yesterday", "due_date": yesterday_1200.isoformat()})
        self.client.post("/api/tasks", json={"title": "Task Today Midnight", "due_date": today_0000.isoformat()})
        self.client.post("/api/tasks", json={"title": "Task Today EndOfDay", "due_date": today_2359.isoformat()})
        self.client.post("/api/tasks", json={"title": "Task Tomorrow Midnight", "due_date": tomorrow_0000.isoformat()})
        self.client.post("/api/tasks", json={"title": "Task Tomorrow Afternoon", "due_date": tomorrow_1200.isoformat()})

        # Query due_today filter
        res = self.client.get("/api/tasks?due_today=true")
        self.assertEqual(res.status_code, 200)
        titles = [t["title"] for t in res.get_json()["tasks"]]

        self.assertIn("Task Today Midnight", titles)
        self.assertIn("Task Today EndOfDay", titles)
        self.assertNotIn("Task Yesterday", titles)
        self.assertNotIn("Task Tomorrow Midnight", titles)
        self.assertNotIn("Task Tomorrow Afternoon", titles)

    # ─────────────────────────────────────────────────────────────
    # Section 6: Task / Email Relationships & Duplicates
    # ─────────────────────────────────────────────────────────────

    def test_email_related_tasks(self):
        """6.1 Related tasks for an email are exposed in the email detail."""
        self._login_as(self.user_a_id)

        self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Task 1 for Email",
            "priority": "high"
        })
        self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Task 2 for Email",
            "priority": "medium"
        })

        email_resp = self.client.get(f"/api/emails/{self.email_a_id}")
        self.assertEqual(email_resp.status_code, 200)
        related = email_resp.get_json()["email"]["tasks"]
        self.assertEqual(len(related), 2)
        titles = [t["title"] for t in related]
        self.assertIn("Task 1 for Email", titles)
        self.assertIn("Task 2 for Email", titles)

    def test_duplicate_ai_task_confirmation_protection(self):
        """6.2 Duplicate AI task confirmation protection blocks repeating exact same task for email."""
        self._login_as(self.user_a_id)

        # Confirm task first time
        resp1 = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Submit Q3 Slides",
        })
        self.assertEqual(resp1.status_code, 201)

        # Confirm exact same task second time
        resp2 = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Submit Q3 Slides",
        })
        self.assertEqual(resp2.status_code, 409)
        self.assertTrue(resp2.get_json()["is_duplicate"])

    def test_duplicate_legitimate_tasks_allowed(self):
        """6.3 Distinct legitimate tasks for the same email are allowed."""
        self._login_as(self.user_a_id)

        resp1 = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Prepare Financial Slides",
        })
        self.assertEqual(resp1.status_code, 201)

        resp2 = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Send Agenda to Attendees",
        })
        self.assertEqual(resp2.status_code, 201)

        with self.app.app_context():
            count = Task.query.filter_by(email_id=self.email_a_id).count()
            self.assertEqual(count, 2)

    def test_cross_user_email_cannot_create_task(self):
        """6.4 User A cannot create a task linked to User B's email (returns 403)."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "email_id": self.email_b_id,
            "title": "Illicit Task",
        })
        self.assertEqual(resp.status_code, 403)

        with self.app.app_context():
            illicit = Task.query.filter_by(task_title="Illicit Task").first()
            self.assertIsNone(illicit)

    def test_deadline_inheritance_from_ai_deadline(self):
        """6.5 Email has ai_deadline and task has no explicit due_date: inherits ai_deadline."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Inherited Deadline Task",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["task"]
        self.assertIsNotNone(data["due_date"])
        with self.app.app_context():
            em = db.session.get(EmailMessage, self.email_a_id)
            self.assertEqual(data["due_date"], em.ai_deadline.isoformat())

    def test_explicit_deadline_overrides_ai_deadline(self):
        """6.6 Explicit due_date takes precedence over email ai_deadline."""
        self._login_as(self.user_a_id)

        explicit_due = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        resp = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Explicit Deadline Task",
            "due_date": explicit_due,
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["task"]
        self.assertTrue(data["due_date"].startswith(explicit_due[:19]))

    def test_task_source_email_resolution(self):
        """6.7 Task GET returns source email metadata."""
        self._login_as(self.user_a_id)

        resp = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Email Linked Action",
        })
        task_id = resp.get_json()["task"]["id"]

        get_resp = self.client.get(f"/api/tasks/{task_id}")
        self.assertEqual(get_resp.status_code, 200)
        source = get_resp.get_json()["task"]["source_email"]
        self.assertIsNotNone(source)
        self.assertEqual(source["id"], self.email_a_id)
        self.assertEqual(source["subject"], "Q3 Product Review and Next Steps")
        self.assertEqual(source["from_address"], "boss@company.com")

    # ─────────────────────────────────────────────────────────────
    # Section 7: Calendar Creation
    # ─────────────────────────────────────────────────────────────

    def test_manual_calendar_event_creation(self):
        """7.1 Manual calendar event creation without email succeeds."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "email_id": None,
            "title": "DSA Practice",
            "description": "Practice arrays",
            "start": start,
            "end": end,
            "location": "Library",
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["event"]["title"], "DSA Practice")
        self.assertIsNone(data["event"]["email_id"])
        self.assertEqual(data["event"]["user_id"], self.user_a_id)
        self.assertFalse(data["has_conflict"])

    def test_manual_calendar_null_email_id_valid(self):
        """7.2 Explicit null email_id creates valid calendar event for User A."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=2, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "email_id": None,
            "title": "Standalone Strategy Session",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()["event"]
        self.assertIsNone(data["email_id"])
        self.assertEqual(data["user_id"], self.user_a_id)

        with self.app.app_context():
            ev = db.session.get(CalendarEvent, data["id"])
            self.assertIsNotNone(ev)
            self.assertIsNone(ev.email_id)
            self.assertEqual(ev.user_id, self.user_a_id)

    def test_email_linked_calendar_event_creation(self):
        """7.3 Calendar event linked to email maintains email_id and metadata."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=3, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "email_id": self.email_a_id,
            "title": "Q3 Review Call",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp.status_code, 201)
        event_id = resp.get_json()["event"]["id"]

        get_resp = self.client.get(f"/api/calendar/{event_id}")
        self.assertEqual(get_resp.status_code, 200)
        source = get_resp.get_json()["event"]["source_email"]
        self.assertIsNotNone(source)
        self.assertEqual(source["id"], self.email_a_id)
        self.assertEqual(source["subject"], "Q3 Product Review and Next Steps")

    # ─────────────────────────────────────────────────────────────
    # Section 8: Calendar Ownership
    # ─────────────────────────────────────────────────────────────

    def test_calendar_ownership_isolation(self):
        """8.1 User A cannot view, update, or delete User B's calendar event."""
        self._login_as(self.user_b_id)
        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        resp_b = self.client.post("/api/calendar", json={
            "title": "Bob's Secret Meeting",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp_b.status_code, 201)
        event_b_id = resp_b.get_json()["event"]["id"]

        # User A attempts access
        self._login_as(self.user_a_id)

        # User A list does not contain event
        list_resp = self.client.get("/api/calendar")
        self.assertEqual(list_resp.status_code, 200)
        event_ids = [e["id"] for e in list_resp.get_json()["events"]]
        self.assertNotIn(event_b_id, event_ids)

        # GET User B's event directly returns 404
        self.assertEqual(self.client.get(f"/api/calendar/{event_b_id}").status_code, 404)

        # PATCH User B's event directly returns 404
        self.assertEqual(self.client.patch(f"/api/calendar/{event_b_id}", json={"title": "Hacked"}).status_code, 404)

        # DELETE User B's event directly returns 404
        self.assertEqual(self.client.delete(f"/api/calendar/{event_b_id}").status_code, 404)

        with self.app.app_context():
            bob_evt = db.session.get(CalendarEvent, event_b_id)
            self.assertIsNotNone(bob_evt)
            self.assertEqual(bob_evt.user_id, self.user_b_id)

    def test_cross_user_email_cannot_create_calendar_event(self):
        """8.2 User A cannot create a calendar event linked to User B's email (returns 403)."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "email_id": self.email_b_id,
            "title": "Illicit Calendar Event",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp.status_code, 403)

        with self.app.app_context():
            illicit = CalendarEvent.query.filter_by(title="Illicit Calendar Event").first()
            self.assertIsNone(illicit)

    def test_calendar_client_supplied_user_id_ignored(self):
        """8.3 Client-supplied user_id cannot hijack calendar event ownership."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=2, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "user_id": self.user_b_id,
            "title": "Spoofed Event",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["event"]["user_id"], self.user_a_id)

    # ─────────────────────────────────────────────────────────────
    # Section 9: Calendar Time Validation
    # ─────────────────────────────────────────────────────────────

    def test_calendar_validation_end_before_start(self):
        """9.1 Case A: end < start is rejected with 400."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=1, hours=2)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()

        resp = self.client.post("/api/calendar", json={
            "title": "Backward Time",
            "start": start,
            "end": end,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("after start", resp.get_json()["error"])

    def test_calendar_validation_end_equals_start(self):
        """9.2 Case B: end == start is rejected with 400."""
        self._login_as(self.user_a_id)

        same_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        resp = self.client.post("/api/calendar", json={
            "title": "Zero Duration",
            "start": same_time,
            "end": same_time,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("after start", resp.get_json()["error"])

    def test_calendar_validation_missing_start(self):
        """9.3 Case C: missing start is rejected with 400."""
        self._login_as(self.user_a_id)

        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        resp = self.client.post("/api/calendar", json={
            "title": "Missing Start",
            "end": end,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("start", resp.get_json()["error"].lower())

    def test_calendar_validation_missing_end(self):
        """9.4 Case D: missing end is rejected with 400."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        resp = self.client.post("/api/calendar", json={
            "title": "Missing End",
            "start": start,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("end", resp.get_json()["error"].lower())

    def test_calendar_validation_invalid_start_format(self):
        """9.5 Case E: invalid start datetime format is rejected with 400."""
        self._login_as(self.user_a_id)

        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        resp = self.client.post("/api/calendar", json={
            "title": "Bad Start Format",
            "start": "not-a-datetime",
            "end": end,
        })
        self.assertEqual(resp.status_code, 400)

    def test_calendar_validation_invalid_end_format(self):
        """9.6 Case F: invalid end datetime format is rejected with 400."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        resp = self.client.post("/api/calendar", json={
            "title": "Bad End Format",
            "start": start,
            "end": "not-a-datetime",
        })
        self.assertEqual(resp.status_code, 400)

    # ─────────────────────────────────────────────────────────────
    # Section 10: Calendar Conflicts & Formula Verification
    # ─────────────────────────────────────────────────────────────

    def test_calendar_conflict_formula_overlap(self):
        """10.1 Conflict formula (start < existing_end AND end > existing_start) detects overlaps."""
        self._login_as(self.user_a_id)

        base_time = datetime.now(timezone.utc) + timedelta(days=5)
        # Base event: 10:00 - 11:00
        start_base = (base_time.replace(hour=10, minute=0, second=0)).isoformat()
        end_base = (base_time.replace(hour=11, minute=0, second=0)).isoformat()

        resp = self.client.post("/api/calendar", json={"title": "Anchor Event", "start": start_base, "end": end_base})
        self.assertEqual(resp.status_code, 201)

        # Overlap 1: 10:59 - 12:00 (overlaps base at 10:59) -> conflict
        r1 = self.client.post("/api/calendar", json={
            "title": "Overlap 1",
            "start": (base_time.replace(hour=10, minute=59, second=0)).isoformat(),
            "end": (base_time.replace(hour=12, minute=0, second=0)).isoformat(),
        })
        self.assertEqual(r1.status_code, 201)
        self.assertTrue(r1.get_json()["has_conflict"])

        # Overlap 2: 09:00 - 10:30 (overlaps base from 10:00 to 10:30) -> conflict
        r2 = self.client.post("/api/calendar", json={
            "title": "Overlap 2",
            "start": (base_time.replace(hour=9, minute=0, second=0)).isoformat(),
            "end": (base_time.replace(hour=10, minute=30, second=0)).isoformat(),
        })
        self.assertEqual(r2.status_code, 201)
        self.assertTrue(r2.get_json()["has_conflict"])

        # Overlap 3: 10:30 - 12:00 -> conflict
        r3 = self.client.post("/api/calendar", json={
            "title": "Overlap 3",
            "start": (base_time.replace(hour=10, minute=30, second=0)).isoformat(),
            "end": (base_time.replace(hour=12, minute=0, second=0)).isoformat(),
        })
        self.assertEqual(r3.status_code, 201)
        self.assertTrue(r3.get_json()["has_conflict"])

        # Overlap 4: 10:00 - 11:00 (exact same range) -> conflict
        r4 = self.client.post("/api/calendar", json={
            "title": "Overlap 4",
            "start": start_base,
            "end": end_base,
        })
        self.assertEqual(r4.status_code, 201)
        self.assertTrue(r4.get_json()["has_conflict"])

    def test_calendar_conflict_formula_boundary_touching_no_conflict(self):
        """10.2 Touching boundaries (10:00-11:00 and 11:00-12:00) MUST NOT conflict."""
        self._login_as(self.user_a_id)

        base_time = datetime.now(timezone.utc) + timedelta(days=6)
        # Event 1: 10:00 to 11:00
        start1 = (base_time.replace(hour=10, minute=0, second=0)).isoformat()
        end1 = (base_time.replace(hour=11, minute=0, second=0)).isoformat()
        resp1 = self.client.post("/api/calendar", json={"title": "Morning Slot", "start": start1, "end": end1})
        self.assertEqual(resp1.status_code, 201)
        self.assertFalse(resp1.get_json()["has_conflict"])

        # Event 2: 11:00 to 12:00 (touches at 11:00)
        start2 = (base_time.replace(hour=11, minute=0, second=0)).isoformat()
        end2 = (base_time.replace(hour=12, minute=0, second=0)).isoformat()
        resp2 = self.client.post("/api/calendar", json={"title": "Afternoon Slot", "start": start2, "end": end2})
        self.assertEqual(resp2.status_code, 201)
        self.assertFalse(resp2.get_json()["has_conflict"])
        self.assertEqual(len(resp2.get_json()["conflicts"]), 0)

    def test_calendar_cross_user_conflicts_isolated(self):
        """10.3 Cross-user conflict isolation: User A's 10:00-11:00 and User B's 10:30-11:30 do not conflict."""
        base_time = datetime.now(timezone.utc) + timedelta(days=7)
        start_a = (base_time.replace(hour=10, minute=0, second=0)).isoformat()
        end_a = (base_time.replace(hour=11, minute=0, second=0)).isoformat()

        start_b = (base_time.replace(hour=10, minute=30, second=0)).isoformat()
        end_b = (base_time.replace(hour=11, minute=30, second=0)).isoformat()

        # User A creates event
        self._login_as(self.user_a_id)
        resp_a = self.client.post("/api/calendar", json={"title": "User A Meeting", "start": start_a, "end": end_a})
        self.assertEqual(resp_a.status_code, 201)
        self.assertFalse(resp_a.get_json()["has_conflict"])

        # User B creates overlapping event
        self._login_as(self.user_b_id)
        resp_b = self.client.post("/api/calendar", json={"title": "User B Meeting", "start": start_b, "end": end_b})
        self.assertEqual(resp_b.status_code, 201)
        self.assertFalse(resp_b.get_json()["has_conflict"], "User B should not see User A event as conflict")
        self.assertEqual(len(resp_b.get_json()["conflicts"]), 0)

        # Check User A again
        self._login_as(self.user_a_id)
        resp_a2 = self.client.post("/api/calendar", json={
            "title": "User A Meeting 2",
            "start": (base_time.replace(hour=14, minute=0, second=0)).isoformat(),
            "end": (base_time.replace(hour=15, minute=0, second=0)).isoformat()
        })
        self.assertFalse(resp_a2.get_json()["has_conflict"])

    def test_calendar_event_update_conflict_detection(self):
        """10.4 Updating an event to overlap another event detects conflict."""
        self._login_as(self.user_a_id)

        base_time = datetime.now(timezone.utc) + timedelta(days=8)
        # Event 1: 14:00 - 15:00
        e1_start = (base_time.replace(hour=14, minute=0, second=0)).isoformat()
        e1_end = (base_time.replace(hour=15, minute=0, second=0)).isoformat()
        resp1 = self.client.post("/api/calendar", json={"title": "E1", "start": e1_start, "end": e1_end})
        self.assertEqual(resp1.status_code, 201)

        # Event 2: 16:00 - 17:00 (no initial conflict)
        e2_start = (base_time.replace(hour=16, minute=0, second=0)).isoformat()
        e2_end = (base_time.replace(hour=17, minute=0, second=0)).isoformat()
        resp2 = self.client.post("/api/calendar", json={"title": "E2", "start": e2_start, "end": e2_end})
        self.assertEqual(resp2.status_code, 201)
        self.assertFalse(resp2.get_json()["has_conflict"])
        e2_id = resp2.get_json()["event"]["id"]

        # Update Event 2 to 14:30 - 15:30 (overlaps Event 1)
        new_e2_start = (base_time.replace(hour=14, minute=30, second=0)).isoformat()
        new_e2_end = (base_time.replace(hour=15, minute=30, second=0)).isoformat()
        upd_resp = self.client.patch(f"/api/calendar/{e2_id}", json={
            "start": new_e2_start,
            "end": new_e2_end,
        })
        self.assertEqual(upd_resp.status_code, 200)
        self.assertTrue(upd_resp.get_json()["has_conflict"])
        self.assertEqual(len(upd_resp.get_json()["conflicts"]), 1)

    def test_calendar_event_self_conflict_exclusion(self):
        """10.5 Updating event metadata without moving time does NOT conflict with itself."""
        self._login_as(self.user_a_id)

        start = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=9, hours=1)).isoformat()
        resp = self.client.post("/api/calendar", json={"title": "Solo Event", "start": start, "end": end})
        event_id = resp.get_json()["event"]["id"]

        upd = self.client.patch(f"/api/calendar/{event_id}", json={"description": "Updated details"})
        self.assertEqual(upd.status_code, 200)
        self.assertFalse(upd.get_json()["has_conflict"])
        self.assertEqual(len(upd.get_json()["conflicts"]), 0)

    # ─────────────────────────────────────────────────────────────
    # Section 11: AI Safety & Autonomous-Write Protection
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_ai_analysis_alone_does_not_create_task(self, mock_model_cls):
        """11.1 AI service suggestions do NOT autonomously insert Task records."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_ai_output = {
            "summary": "Meeting invitation regarding Q3 financial review and slides.",
            "category": "work",
            "priority": "high",
            "sentiment": "neutral",
            "action_required": True,
            "deadline": "2026-09-20T17:00:00Z",
            "suggested_tasks": [
                {
                    "title": "Suggested Task",
                    "description": "Prepare Q3 financial slides",
                    "due_date": "2026-09-20T17:00:00Z",
                    "priority": "high"
                }
            ],
            "suggested_event": {
                "title": "Suggested Meeting",
                "start": "2026-09-20T15:00:00Z",
                "end": "2026-09-20T16:00:00Z",
                "location": "Google Meet"
            },
            "entities": []
        }
        mock_response.text = json.dumps(mock_ai_output)
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model_instance

        with self.app.app_context():
            initial_count = Task.query.count()
            self.assertEqual(initial_count, 0)

        self._login_as(self.user_a_id)
        resp = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            em = db.session.get(EmailMessage, self.email_a_id)
            self.assertIsNotNone(em.ai_suggested_tasks)
            self.assertIn("Suggested Task", em.ai_suggested_tasks)
            self.assertEqual(Task.query.count(), 0)

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_ai_analysis_alone_does_not_create_calendar_event(self, mock_model_cls):
        """11.2 AI service suggestions do NOT autonomously insert CalendarEvent records."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_ai_output = {
            "summary": "Meeting invitation regarding Q3 financial review.",
            "category": "work",
            "priority": "high",
            "sentiment": "neutral",
            "action_required": True,
            "deadline": "2026-09-20T17:00:00Z",
            "suggested_tasks": [],
            "suggested_event": {
                "title": "Suggested Meeting",
                "start": "2026-09-20T15:00:00Z",
                "end": "2026-09-20T16:00:00Z",
                "location": "Google Meet"
            },
            "entities": []
        }
        mock_response.text = json.dumps(mock_ai_output)
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model_instance

        with self.app.app_context():
            initial_count = CalendarEvent.query.count()
            self.assertEqual(initial_count, 0)

        self._login_as(self.user_a_id)
        resp = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            em = db.session.get(EmailMessage, self.email_a_id)
            self.assertIsNotNone(em.ai_suggested_event)
            self.assertIn("Suggested Meeting", em.ai_suggested_event)
            self.assertEqual(CalendarEvent.query.count(), 0)

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_ai_analysis_endpoint_does_not_create_task(self, mock_model_cls):
        """11.3 Explicit database count assertion: before=X, after=X for tasks."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_ai_output = {
            "summary": "Action required probe.",
            "category": "work",
            "priority": "urgent",
            "sentiment": "neutral",
            "action_required": True,
            "suggested_tasks": [{"title": "Autonomous Creation Task Probe", "priority": "urgent"}],
            "suggested_event": None,
            "entities": []
        }
        mock_response.text = json.dumps(mock_ai_output)
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model_instance

        with self.app.app_context():
            initial_count = Task.query.count()

        self._login_as(self.user_a_id)
        resp = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            self.assertEqual(Task.query.count(), initial_count)

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_ai_analysis_endpoint_does_not_create_calendar_event(self, mock_model_cls):
        """11.4 Explicit database count assertion: before=Y, after=Y for calendar events."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_ai_output = {
            "summary": "Meeting proposal probe.",
            "category": "work",
            "priority": "urgent",
            "sentiment": "neutral",
            "action_required": True,
            "suggested_tasks": [],
            "suggested_event": {"title": "Autonomous Meeting Probe", "start": "2026-09-25T10:00:00Z", "end": "2026-09-25T11:00:00Z"},
            "entities": []
        }
        mock_response.text = json.dumps(mock_ai_output)
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model_instance

        with self.app.app_context():
            initial_count = CalendarEvent.query.count()

        self._login_as(self.user_a_id)
        resp = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            self.assertEqual(CalendarEvent.query.count(), initial_count)

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_ai_analysis_cross_user_forbidden(self, mock_model_cls):
        """11.5 User A cannot analyze User B's email (403 forbidden). No Task or Event created."""
        mock_model_instance = MagicMock()
        mock_model_cls.return_value = mock_model_instance

        with self.app.app_context():
            initial_tasks = Task.query.count()
            initial_events = CalendarEvent.query.count()
            b_email_before = db.session.get(EmailMessage, self.email_b_id)
            self.assertIsNone(b_email_before.ai_summary)

        # Login as User A and attempt to analyze User B's email
        self._login_as(self.user_a_id)
        resp = self.client.post(f"/api/emails/{self.email_b_id}/analyze")
        self.assertEqual(resp.status_code, 403)

        # Mock model should never have been called
        mock_model_instance.generate_content.assert_not_called()

        with self.app.app_context():
            b_email_after = db.session.get(EmailMessage, self.email_b_id)
            self.assertIsNone(b_email_after.ai_summary)
            self.assertEqual(Task.query.count(), initial_tasks)
            self.assertEqual(CalendarEvent.query.count(), initial_events)

    # ─────────────────────────────────────────────────────────────
    # Section 12: Human Confirmation Flow
    # ─────────────────────────────────────────────────────────────

    @patch("app.services.ai_service.genai.GenerativeModel")
    def test_human_confirmation_required_for_tasks_and_calendar(self, mock_model_cls):
        """12.1 End-to-end verification of AI suggestion -> Human confirmation -> Object created."""
        mock_model_instance = MagicMock()
        mock_response = MagicMock()
        mock_ai_output = {
            "summary": "Review Q3 deck and schedule a debrief session.",
            "category": "work",
            "priority": "high",
            "sentiment": "neutral",
            "action_required": True,
            "deadline": "2026-09-25T18:00:00Z",
            "suggested_tasks": [
                {"title": "Review Q3 Deck", "priority": "high", "due_date": "2026-09-25T18:00:00Z"}
            ],
            "suggested_event": {
                "title": "Debrief Session",
                "start": "2026-09-26T10:00:00Z",
                "end": "2026-09-26T11:00:00Z",
                "location": "Meet Room"
            },
            "entities": []
        }
        mock_response.text = json.dumps(mock_ai_output)
        mock_model_instance.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model_instance

        self._login_as(self.user_a_id)

        # Step 1: AI analysis
        analyze_resp = self.client.post(f"/api/emails/{self.email_a_id}/analyze")
        self.assertEqual(analyze_resp.status_code, 200)

        # Confirm nothing in database yet
        with self.app.app_context():
            self.assertEqual(Task.query.count(), 0)
            self.assertEqual(CalendarEvent.query.count(), 0)

        # Step 2: Human clicks 'Create Task'
        t_resp = self.client.post("/api/tasks", json={
            "email_id": self.email_a_id,
            "title": "Review Q3 Deck",
            "priority": "high"
        })
        self.assertEqual(t_resp.status_code, 201)

        # Step 3: Human clicks 'Create Calendar Event'
        e_resp = self.client.post("/api/calendar", json={
            "email_id": self.email_a_id,
            "title": "Debrief Session",
            "start": "2026-09-26T10:00:00Z",
            "end": "2026-09-26T11:00:00Z",
        })
        self.assertEqual(e_resp.status_code, 201)

        # Confirm exactly 1 Task and 1 CalendarEvent exist now
        with self.app.app_context():
            self.assertEqual(Task.query.count(), 1)
            self.assertEqual(CalendarEvent.query.count(), 1)

    # ─────────────────────────────────────────────────────────────
    # Section 13: Dashboard Isolation & Source Data Integrity
    # ─────────────────────────────────────────────────────────────

    def test_dashboard_stats_and_isolation(self):
        """13.1 Dashboard stats strictly isolate task and calendar metrics per user."""
        now = datetime.now(timezone.utc)
        start_a = (now + timedelta(hours=3)).isoformat()
        end_a = (now + timedelta(hours=4)).isoformat()

        # User A creates a task and event
        self._login_as(self.user_a_id)
        self.client.post("/api/tasks", json={"title": "Alice Task 1", "priority": "high"})
        self.client.post("/api/calendar", json={"title": "Alice Event 1", "start": start_a, "end": end_a})

        # User B creates a task
        self._login_as(self.user_b_id)
        self.client.post("/api/tasks", json={"title": "Bob Task 1", "priority": "low"})

        # User A dashboard
        self._login_as(self.user_a_id)
        resp_a = self.client.get("/api/dashboard/stats")
        self.assertEqual(resp_a.status_code, 200)
        stats_a = resp_a.get_json()
        self.assertEqual(stats_a["tasks"]["total"], 1)
        self.assertEqual(stats_a["calendar"]["today_events_count"], 1)

        # User B dashboard
        self._login_as(self.user_b_id)
        resp_b = self.client.get("/api/dashboard/stats")
        self.assertEqual(resp_b.status_code, 200)
        stats_b = resp_b.get_json()
        self.assertEqual(stats_b["tasks"]["total"], 1)
        self.assertEqual(stats_b["calendar"]["today_events_count"], 0)

    def test_task_and_calendar_deletion_leaves_email_intact(self):
        """13.2 Deleting task and calendar event never deletes source email message."""
        self._login_as(self.user_a_id)

        t_resp = self.client.post("/api/tasks", json={"email_id": self.email_a_id, "title": "Deletable Task"})
        task_id = t_resp.get_json()["task"]["id"]

        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=1, hours=1)).isoformat()
        e_resp = self.client.post("/api/calendar", json={
            "email_id": self.email_a_id,
            "title": "Deletable Event",
            "start": start,
            "end": end,
        })
        event_id = e_resp.get_json()["event"]["id"]

        # Delete task & event
        self.assertEqual(self.client.delete(f"/api/tasks/{task_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/calendar/{event_id}").status_code, 200)

        # Email must still exist
        with self.app.app_context():
            em = db.session.get(EmailMessage, self.email_a_id)
            self.assertIsNotNone(em)
            self.assertEqual(em.subject, "Q3 Product Review and Next Steps")

    # ─────────────────────────────────────────────────────────────
    # Section 14: Unauthenticated Security Tests
    # ─────────────────────────────────────────────────────────────

    def test_unauthenticated_phase5_endpoints_rejected(self):
        """14.1 Unauthenticated requests to Phase 5 endpoints return 401."""
        dummy_id = "00000000-0000-0000-0000-000000000000"

        endpoints = [
            ("GET", "/api/tasks"),
            ("GET", f"/api/tasks/{dummy_id}"),
            ("POST", "/api/tasks"),
            ("PATCH", f"/api/tasks/{dummy_id}"),
            ("DELETE", f"/api/tasks/{dummy_id}"),
            ("POST", f"/api/tasks/{dummy_id}/complete"),
            ("POST", f"/api/tasks/{dummy_id}/reopen"),
            ("GET", "/api/calendar"),
            ("GET", f"/api/calendar/{dummy_id}"),
            ("POST", "/api/calendar"),
            ("PATCH", f"/api/calendar/{dummy_id}"),
            ("DELETE", f"/api/calendar/{dummy_id}"),
            ("GET", "/api/dashboard/stats"),
            ("POST", f"/api/emails/{dummy_id}/analyze"),
        ]

        for method, url in endpoints:
            if method == "GET":
                resp = self.client.get(url)
            elif method == "POST":
                resp = self.client.post(url, json={})
            elif method == "PATCH":
                resp = self.client.patch(url, json={})
            elif method == "DELETE":
                resp = self.client.delete(url)
            else:
                self.fail(f"Unsupported method: {method}")

            self.assertEqual(resp.status_code, 401, f"Expected 401 for unauthenticated {method} {url}, got {resp.status_code}")


if __name__ == "__main__":
    unittest.main()
