"""
Models package — import every model so that SQLAlchemy (and Alembic)
can discover them automatically.
"""

from app.models.user import User
from app.models.connected_email_account import ConnectedEmailAccount
from app.models.email_message import EmailMessage
from app.models.task import Task
from app.models.calendar_event import CalendarEvent
from app.models.reminder import Reminder
from app.models.entity import Entity
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.user_preference import UserPreference
from app.models.user_feedback_signal import UserFeedbackSignal
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.notification import Notification, NotificationType, NotificationSeverity
from app.models.saved_search import SavedSearch

__all__ = [
    "User",
    "ConnectedEmailAccount",
    "EmailMessage",
    "Task",
    "CalendarEvent",
    "Reminder",
    "Entity",
    "AIAnalysisJob",
    "UserPreference",
    "UserFeedbackSignal",
    "ActionItem",
    "ActionType",
    "ActionStatus",
    "Notification",
    "NotificationType",
    "NotificationSeverity",
    "SavedSearch",
]

