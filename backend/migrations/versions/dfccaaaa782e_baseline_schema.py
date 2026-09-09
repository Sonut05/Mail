"""baseline_schema

Revision ID: dfccaaaa782e
Revises: 
Create Date: 2026-09-08 09:01:53.510554

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dfccaaaa782e'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Create users table ───────────────────────────────
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('contact_no', sa.String(length=50), nullable=True),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='google'),
        sa.Column('password_hash', sa.String(length=255), nullable=True),
        sa.Column('encrypted_access_token', sa.Text(), nullable=True),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expiry', sa.DateTime(), nullable=True),
        sa.Column('target_role', sa.String(length=255), nullable=True),
        sa.Column('min_salary', sa.Integer(), nullable=True),
        sa.Column('max_salary', sa.Integer(), nullable=True),
        sa.Column('resume_text', sa.Text(), nullable=True),
        sa.Column('resume_parsed_json', sa.Text(), nullable=True),
        sa.Column('resume_profiles', sa.Text(), nullable=True),
        sa.Column('picture', sa.String(length=511), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    # ── 2. Create connected_email_accounts table ────────────
    op.create_table(
        'connected_email_accounts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='gmail'),
        sa.Column('provider_account_id', sa.String(length=255), nullable=True),
        sa.Column('email_address', sa.String(length=255), nullable=False),
        sa.Column('encrypted_access_token', sa.Text(), nullable=False),
        sa.Column('encrypted_refresh_token', sa.Text(), nullable=True),
        sa.Column('token_expiry', sa.DateTime(), nullable=True),
        sa.Column('sync_status', sa.String(length=50), nullable=False, server_default='idle'),
        sa.Column('sync_progress', sa.Text(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('history_id', sa.String(length=255), nullable=True),
        sa.Column('messages_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('connected_email_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_connected_email_accounts_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_connected_email_accounts_email_address'), ['email_address'], unique=False)
        batch_op.create_index(batch_op.f('ix_connected_email_accounts_provider_account_id'), ['provider_account_id'], unique=False)

    # ── 3. Create email_messages table (Phase 1 Baseline) ───
    op.create_table(
        'email_messages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=False),
        sa.Column('thread_id', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('from_address', sa.String(length=255), nullable=True),
        sa.Column('to_address', sa.String(length=255), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=True),
        sa.Column('priority', sa.String(length=50), nullable=True),
        sa.Column('sentiment', sa.String(length=50), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('auto_reply_required', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('needs_human_review', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('spam_score', sa.Integer(), nullable=True),
        sa.Column('reply_draft', sa.Text(), nullable=True),
        sa.Column('auto_reply_sent', sa.Boolean(), server_default=sa.false(), nullable=True),
        sa.Column('sent_reply_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_email_messages_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_email_messages_message_id'), ['message_id'], unique=True)


    # ── 4. Create tasks table (Pre-Phase 5 Baseline) ────────
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email_id', sa.String(length=36), nullable=False),
        sa.Column('task_title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('due_date', sa.DateTime(), nullable=True),
        sa.Column('priority', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('assignee', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tasks_email_id'), ['email_id'], unique=False)

    # ── 5. Create calendar_events table (Pre-Phase 5 Baseline) ─
    op.create_table(
        'calendar_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('start_date_time', sa.DateTime(), nullable=False),
        sa.Column('end_date_time', sa.DateTime(), nullable=True),
        sa.Column('timezone', sa.String(length=100), nullable=False, server_default='UTC'),
        sa.Column('location', sa.String(length=500), nullable=True),
        sa.Column('meeting_link', sa.String(length=1000), nullable=True),
        sa.Column('organizer', sa.String(length=255), nullable=True),
        sa.Column('attendees', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('calendar_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_calendar_events_email_id'), ['email_id'], unique=True)

    # ── 6. Create reminders table (Baseline) ─────────────────
    op.create_table(
        'reminders',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('reminder_type', sa.String(length=100), nullable=False),
        sa.Column('event_date_time', sa.DateTime(), nullable=False),
        sa.Column('reminder_date_time', sa.DateTime(), nullable=False),
        sa.Column('priority', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('reminders', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reminders_email_id'), ['email_id'], unique=False)

    # ── 7. Create entities table (Baseline) ──────────────────
    op.create_table(
        'entities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email_id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('entities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_entities_email_id'), ['email_id'], unique=False)


def downgrade():
    op.drop_table('entities')
    op.drop_table('reminders')
    op.drop_table('calendar_events')
    op.drop_table('tasks')
    op.drop_table('email_messages')
    op.drop_table('connected_email_accounts')
    op.drop_table('users')
