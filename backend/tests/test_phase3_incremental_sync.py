"""
Phase 3 Tests — Gmail Incremental Synchronization Using historyId.

Covers:
1. Initial sync stores history_id on ConnectedEmailAccount.
2. Incremental sync finds and stores new messages from messagesAdded.
3. Incremental sync with 0 changes reports up-to-date and 0 new messages.
4. Duplicate message in history is not duplicated in DB (idempotency).
5. Multiple new messages across pages are processed and persisted.
6. History pagination using nextPageToken traverses all pages.
7. history_id advances only after successful commit (does not advance on failure).
8. Expired historyId (HTTP 404 / historyIdNotFound) triggers sync_status = "resync_required".
9. Token auto-refreshes when expired during incremental sync.
10. Revoked refresh token marks account as "error" with token_revoked flag.
11. Multi-user isolation (User A cannot sync User B's account).
12. Concurrent sync protection returns 409 when account is already syncing.
13. Label changes (labelsAdded, labelsRemoved) update existing EmailMessage.labels.
14. API endpoints (/api/mail/sync/incremental, /api/mail/sync-status) never expose OAuth tokens.
"""

import base64
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from googleapiclient.errors import HttpError
import httplib2
from google.auth.exceptions import RefreshError

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.services.encryption import encrypt_token, decrypt_token
from app.services.sync_service import (
    sync_gmail_mailbox,
    sync_gmail_incremental,
)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-phase3-secret-key"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    GOOGLE_CLIENT_SECRET = "test-client-secret"
    GOOGLE_REDIRECT_URI = "http://localhost:5000/api/auth/google/callback"


def _b64(text: str) -> str:
    """Helper to encode string to urlsafe base64 without padding."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def _make_http_error(status: int, reason: str, message: str = ""):
    resp = httplib2.Response({"status": str(status), "reason": reason})
    content = json.dumps({"error": {"code": status, "message": message or reason}}).encode("utf-8")
    return HttpError(resp, content)


class TestPhase3IncrementalSync(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            # Create User A
            self.user_a = User(
                email="alice@mailmild.com",
                name="Alice User",
                provider="google",
            )
            db.session.add(self.user_a)

            # Create User B
            self.user_b = User(
                email="bob@mailmild.com",
                name="Bob User",
                provider="google",
            )
            db.session.add(self.user_b)
            db.session.commit()

            self.user_a_id = self.user_a.id
            self.user_b_id = self.user_b.id

            # Create Connected Account for User A with existing history_id
            self.acc_a = ConnectedEmailAccount(
                user_id=self.user_a_id,
                provider="gmail",
                provider_account_id="gmail_sub_alice",
                email_address="alice.work@gmail.com",
                encrypted_access_token=encrypt_token("valid-access-token-a"),
                encrypted_refresh_token=encrypt_token("valid-refresh-token-a"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                history_id="100000",
                messages_synced=5,
            )
            db.session.add(self.acc_a)

            # Create Connected Account for User B
            self.acc_b = ConnectedEmailAccount(
                user_id=self.user_b_id,
                provider="gmail",
                provider_account_id="gmail_sub_bob",
                email_address="bob.work@gmail.com",
                encrypted_access_token=encrypt_token("valid-access-token-b"),
                encrypted_refresh_token=encrypt_token("valid-refresh-token-b"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                sync_status="completed",
                history_id="200000",
                messages_synced=10,
            )
            db.session.add(self.acc_b)
            db.session.commit()

            self.acc_a_id = self.acc_a.id
            self.acc_b_id = self.acc_b.id

    def _login_as(self, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id

    # ──────────────────────────────────────────────────────────
    # 1. Initial Sync Stores history_id
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_initial_sync_stores_history_id(self, mock_build_service):
        """Full mailbox sync queries users().getProfile() and records history_id."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # Messages list
        mock_gmail.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg_init_1"}],
        }

        # Message get
        mock_gmail.users().messages().get().execute.return_value = {
            "id": "msg_init_1",
            "threadId": "th_1",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Welcome"},
                    {"name": "From", "value": "admin@example.com"},
                    {"name": "To", "value": "alice.work@gmail.com"},
                ],
                "body": {"data": _b64("Initial welcome message")},
            },
        }

        # users().getProfile() returns historyId
        mock_gmail.users().getProfile().execute.return_value = {
            "emailAddress": "alice.work@gmail.com",
            "historyId": "999999",
            "messagesTotal": 1,
        }

        with self.app.app_context():
            res = sync_gmail_mailbox(self.acc_a_id)
            self.assertEqual(res["status"], "completed")

            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, "999999")
            self.assertEqual(acc.sync_status, "completed")

    # ──────────────────────────────────────────────────────────
    # 2. Incremental Sync Finds and Stores New Messages
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_incremental_sync_fetches_and_stores_new_messages(self, mock_build_service):
        """Incremental sync queries history.list and stores messagesAdded."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # history().list response
        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "100500",
            "history": [
                {
                    "id": "100100",
                    "messagesAdded": [
                        {"message": {"id": "inc_msg_1", "threadId": "th_inc_1", "labelIds": ["INBOX"]}},
                    ],
                }
            ],
        }

        # Message get response
        mock_gmail.users().messages().get().execute.return_value = {
            "id": "inc_msg_1",
            "threadId": "th_inc_1",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "New Incremental Email"},
                    {"name": "From", "value": "boss@work.com"},
                    {"name": "To", "value": "alice.work@gmail.com"},
                ],
                "body": {"data": _b64("Here is the latest report.")},
            },
        }

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["messages_added"], 1)
            self.assertEqual(res["history_id"], "100500")

            # Check message in DB
            msg = EmailMessage.query.filter_by(provider_message_id="inc_msg_1").first()
            self.assertIsNotNone(msg)
            self.assertEqual(msg.subject, "New Incremental Email")
            self.assertEqual(msg.body_text, "Here is the latest report.")

            # Check account updated
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, "100500")
            self.assertEqual(acc.sync_status, "completed")

    # ──────────────────────────────────────────────────────────
    # 3. Incremental Sync with 0 Changes
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_incremental_sync_zero_changes(self, mock_build_service):
        """When history list has no changes, returns completed with 0 messages added."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # history().list with no history items
        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "100000",
            # No 'history' key or empty list
        }

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["messages_added"], 0)
            self.assertIn("0 new messages", res["progress"])

            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, "100000")
            self.assertEqual(acc.sync_status, "completed")

    # ──────────────────────────────────────────────────────────
    # 4. Duplicate Message in History is Not Duplicated in DB
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_duplicate_message_in_history_not_duplicated_in_db(self, mock_build_service):
        """If history repeats a message ID, it is updated and not duplicated."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # First insert a message manually
        with self.app.app_context():
            existing_msg = EmailMessage(
                user_id=self.user_a_id,
                connected_account_id=self.acc_a_id,
                provider_message_id="dup_msg_1",
                message_id="dup_msg_1",
                subject="Old Subject",
                from_address="old@test.com",
                to_address="alice@work.com",
                body_text="Old body",
                labels=json.dumps(["INBOX"]),
            )
            db.session.add(existing_msg)
            db.session.commit()

        # history().list returns the same message
        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "100200",
            "history": [
                {
                    "id": "100150",
                    "messagesAdded": [
                        {"message": {"id": "dup_msg_1", "threadId": "th_dup"}},
                    ],
                }
            ],
        }

        mock_gmail.users().messages().get().execute.return_value = {
            "id": "dup_msg_1",
            "threadId": "th_dup",
            "labelIds": ["INBOX", "STARRED"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": "Updated Subject"},
                    {"name": "From", "value": "new@test.com"},
                    {"name": "To", "value": "alice@work.com"},
                ],
                "body": {"data": _b64("Updated body text")},
            },
        }

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")

            # Must still be exactly 1 record in SQLite
            count = EmailMessage.query.filter_by(provider_message_id="dup_msg_1").count()
            self.assertEqual(count, 1)

            updated = EmailMessage.query.filter_by(provider_message_id="dup_msg_1").first()
            self.assertEqual(updated.subject, "Updated Subject")
            self.assertIn("STARRED", updated.labels)

    # ──────────────────────────────────────────────────────────
    # 5. Multiple New Messages Across History Records
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_multiple_new_messages_across_history_records(self, mock_build_service):
        """Collects all messagesAdded across multiple history records."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "100600",
            "history": [
                {
                    "id": "100100",
                    "messagesAdded": [
                        {"message": {"id": "msg_multi_a"}},
                    ],
                },
                {
                    "id": "100200",
                    "messagesAdded": [
                        {"message": {"id": "msg_multi_b"}},
                        {"message": {"id": "msg_multi_c"}},
                    ],
                },
            ],
        }

        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = {
                "id": id,
                "threadId": f"th_{id}",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": f"Subject for {id}"},
                        {"name": "From", "value": "sender@test.com"},
                        {"name": "To", "value": "alice@work.com"},
                    ],
                    "body": {"data": _b64(f"Body of {id}")},
                },
            }
            return req

        mock_gmail.users().messages().get.side_effect = mock_get

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["messages_added"], 3)

            self.assertEqual(EmailMessage.query.filter_by(connected_account_id=self.acc_a_id).count(), 3)

    # ──────────────────────────────────────────────────────────
    # 6. History Pagination: Test A (Multiple pages) & Test B (Incomplete safety)
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_history_pagination_with_next_page_token(self, mock_build_service):
        """Test A: history().list paginates Page 1 -> Page 2 -> Page 3 -> no token, processing all pages."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        page1 = {
            "historyId": "100700",
            "nextPageToken": "page_token_2",
            "history": [
                {"id": "1", "messagesAdded": [{"message": {"id": "p1_msg1"}}]},
            ],
        }
        page2 = {
            "historyId": "100800",
            "nextPageToken": "page_token_3",
            "history": [
                {"id": "2", "messagesAdded": [{"message": {"id": "p2_msg1"}}]},
            ],
        }
        page3 = {
            "historyId": "100900",
            "history": [
                {"id": "3", "messagesAdded": [{"message": {"id": "p3_msg1"}}]},
            ],
        }

        def mock_history_list(**kwargs):
            req = MagicMock()
            pt = kwargs.get("pageToken")
            if pt == "page_token_2":
                req.execute.return_value = page2
            elif pt == "page_token_3":
                req.execute.return_value = page3
            else:
                req.execute.return_value = page1
            return req

        mock_gmail.users().history().list.side_effect = mock_history_list

        def mock_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = {
                "id": id,
                "threadId": f"th_{id}",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": f"Page Subject {id}"},
                        {"name": "From", "value": "sender@test.com"},
                        {"name": "To", "value": "alice@work.com"},
                    ],
                    "body": {"data": _b64(f"Content {id}")},
                },
            }
            return req

        mock_gmail.users().messages().get.side_effect = mock_get

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["messages_added"], 3)
            self.assertEqual(res["history_id"], "100900")

            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, "100900")
            self.assertEqual(acc.sync_status, "completed")

    @patch("app.services.sync_service.build_service")
    def test_pagination_incomplete_preserves_previous_cursor(self, mock_build_service):
        """Test B: If max_pages limit is reached and nextPageToken exists, history_id must NOT advance."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # Page 1 returns nextPageToken
        page1 = {
            "historyId": "100700",
            "nextPageToken": "pending_page_token_2",
            "history": [
                {"id": "1", "messagesAdded": [{"message": {"id": "p1_msg1"}}]},
            ],
        }

        mock_gmail.users().history().list().execute.return_value = page1

        with self.app.app_context():
            initial_history = self.acc_a.history_id  # "100000"

            # Execute with max_pages=1 so it exits while nextPageToken is still pending
            res = sync_gmail_incremental(self.acc_a_id, max_pages=1)

            # Must report error / incomplete, NOT completed
            self.assertEqual(res["status"], "error")
            self.assertFalse(res.get("success", False))
            self.assertIn("incomplete", res.get("error", "").lower())

            # Verify history_id was NOT advanced and remains available for retry
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, initial_history)
            self.assertEqual(acc.sync_status, "error")
            self.assertIn("limit reached", acc.sync_progress.lower())

    # ──────────────────────────────────────────────────────────
    # 7. history_id Advances Only After Successful Commit
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_history_id_does_not_advance_on_commit_failure(self, mock_build_service):
        """If database commit fails, history_id must NOT advance."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "999999",
            "history": [
                {"id": "1", "messagesAdded": [{"message": {"id": "err_msg_1"}}]},
            ],
        }

        mock_gmail.users().messages().get().execute.return_value = {
            "id": "err_msg_1",
            "threadId": "th_err",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [{"name": "Subject", "value": "Test"}],
                "body": {"data": _b64("body")},
            },
        }

        with self.app.app_context():
            initial_history = self.acc_a.history_id  # "100000"

            # Simulate commit raising an exception during message save, then succeeding for cleanup
            with patch.object(db.session, "commit", side_effect=[None, Exception("Database lock error"), None]):
                res = sync_gmail_incremental(self.acc_a_id)
                self.assertEqual(res["status"], "error")

            # Verify history_id was NOT advanced
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.history_id, initial_history)
            self.assertEqual(acc.sync_status, "error")

    # ──────────────────────────────────────────────────────────
    # 8. Expired historyId (HTTP 404) Triggers resync_required
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_expired_history_id_404_sets_resync_required(self, mock_build_service):
        """When history().list returns HTTP 404 (cursor expired), set status = resync_required."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        http_404 = _make_http_error(404, "Not Found", "historyIdNotFound: History ID has expired")
        mock_gmail.users().history().list().execute.side_effect = http_404

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "resync_required")
            self.assertTrue(res.get("resync_required"))

            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.sync_status, "resync_required")
            # history_id must remain unchanged for reference
            self.assertEqual(acc.history_id, "100000")
            self.assertIn("expired", acc.sync_progress.lower())

    # ──────────────────────────────────────────────────────────
    # 9. Token Auto-Refreshes When Expired
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.Credentials")
    @patch("app.services.sync_service.build_service")
    def test_token_auto_refresh_on_incremental_sync(self, mock_build, mock_credentials_cls):
        """Expired access token triggers auto-refresh and updates encrypted token in SQLite."""
        # Set token_expiry to past
        with self.app.app_context():
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            acc.token_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
            db.session.commit()

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.token = "refreshed-new-access-token"
        mock_creds.refresh_token = "valid-refresh-token-a"
        mock_creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_credentials_cls.return_value = mock_creds

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        mock_service.users().history().list().execute.return_value = {
            "historyId": "100300",
            "history": [],
        }

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")

            # Verify refresh was triggered
            mock_creds.refresh.assert_called_once()

            # Verify new token stored encrypted in database
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            decrypted = decrypt_token(acc.encrypted_access_token)
            self.assertEqual(decrypted, "refreshed-new-access-token")

    # ──────────────────────────────────────────────────────────
    # 10. Revoked Refresh Token Marks Account as Error
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.Credentials")
    @patch("app.services.sync_service.build_service")
    def test_revoked_token_sets_error_status(self, mock_build, mock_credentials_cls):
        """Google RefreshError (token revoked) marks account sync_status='error' and token_revoked."""
        with self.app.app_context():
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            acc.token_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
            db.session.commit()

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")
        mock_credentials_cls.return_value = mock_creds

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "error")
            self.assertTrue(res.get("token_revoked"))

            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            self.assertEqual(acc.sync_status, "error")
            self.assertIn("revoked", acc.sync_progress.lower())

    # ──────────────────────────────────────────────────────────
    # 11. Multi-User Isolation (User A cannot sync User B's account)
    # ──────────────────────────────────────────────────────────

    def test_multi_user_isolation_incremental_sync(self):
        """User A cannot trigger incremental sync on User B's connected account."""
        self._login_as(self.user_a_id)

        # Attempt to trigger incremental sync on User B's account
        resp = self.client.post(
            "/api/mail/sync/incremental",
            data=json.dumps({"account_id": self.acc_b_id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("unauthorized", data["error"].lower())

    # ──────────────────────────────────────────────────────────
    # 12. Concurrent Incremental Sync Protection Returns 409
    # ──────────────────────────────────────────────────────────

    def test_concurrent_incremental_sync_protection(self):
        """Attempting incremental sync while account is already syncing returns HTTP 409."""
        with self.app.app_context():
            acc = db.session.get(ConnectedEmailAccount, self.acc_a_id)
            acc.sync_status = "syncing"
            acc.sync_progress = "Sync in progress..."
            db.session.commit()

        self._login_as(self.user_a_id)

        resp = self.client.post(
            "/api/mail/sync/incremental",
            data=json.dumps({"account_id": self.acc_a_id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("already in progress", data["error"].lower())

    # ──────────────────────────────────────────────────────────
    # 13. Label Changes in History Update Existing Message Labels
    # ──────────────────────────────────────────────────────────

    @patch("app.services.sync_service.build_service")
    def test_label_changes_in_history_update_message_labels(self, mock_build_service):
        """labelsAdded and labelsRemoved in history update EmailMessage.labels."""
        mock_gmail = MagicMock()
        mock_build_service.return_value = mock_gmail

        # Seed existing email
        with self.app.app_context():
            msg = EmailMessage(
                user_id=self.user_a_id,
                connected_account_id=self.acc_a_id,
                provider_message_id="msg_label_test",
                message_id="msg_label_test",
                subject="Labels Test",
                from_address="friend@test.com",
                to_address="alice@work.com",
                body_text="Body",
                labels=json.dumps(["INBOX", "UNREAD"]),
            )
            db.session.add(msg)
            db.session.commit()

        # history list contains label changes
        mock_gmail.users().history().list().execute.return_value = {
            "historyId": "100450",
            "history": [
                {
                    "id": "100350",
                    "labelsAdded": [
                        {"message": {"id": "msg_label_test"}, "labelIds": ["STARRED", "IMPORTANT"]},
                    ],
                    "labelsRemoved": [
                        {"message": {"id": "msg_label_test"}, "labelIds": ["UNREAD"]},
                    ],
                }
            ],
        }

        with self.app.app_context():
            res = sync_gmail_incremental(self.acc_a_id)
            self.assertEqual(res["status"], "completed")

            updated = EmailMessage.query.filter_by(provider_message_id="msg_label_test").first()
            labels_list = json.loads(updated.labels) if isinstance(updated.labels, str) else updated.labels
            self.assertIn("INBOX", labels_list)
            self.assertIn("STARRED", labels_list)
            self.assertIn("IMPORTANT", labels_list)
            self.assertNotIn("UNREAD", labels_list)

    # ──────────────────────────────────────────────────────────
    # 14. API Endpoints Never Expose OAuth Tokens
    # ──────────────────────────────────────────────────────────

    def test_api_endpoints_never_leak_oauth_tokens(self):
        """Endpoints /api/mail/sync/incremental and /api/mail/sync-status never return tokens."""
        self._login_as(self.user_a_id)

        # GET /api/mail/sync-status
        resp = self.client.get(f"/api/mail/sync-status?account_id={self.acc_a_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        # Check for token leak
        raw_text = resp.data.decode("utf-8")
        self.assertNotIn("token", raw_text.lower().replace("nextpagetoken", ""))
        self.assertNotIn("encrypted_access_token", data)
        self.assertNotIn("encrypted_refresh_token", data)
        self.assertNotIn("valid-access-token-a", raw_text)
        self.assertNotIn("valid-refresh-token-a", raw_text)

        # Check safe metadata fields
        self.assertIn("history_id", data)
        self.assertEqual(data["history_id"], "100000")
        self.assertIn("messages_synced", data)


if __name__ == "__main__":
    unittest.main()
