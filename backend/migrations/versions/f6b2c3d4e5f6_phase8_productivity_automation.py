"""phase8_productivity_automation

Revision ID: f6b2c3d4e5f6
Revises: e5a1b2c3d4e5
Create Date: 2026-09-09 02:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6b2c3d4e5f6'
down_revision = 'e5a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Create action_items table ─────────────────────────────
    op.create_table(
        'action_items',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('action_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=50), nullable=False, server_default='medium'),
        sa.Column('score', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('reasons', sa.Text(), nullable=True),
        sa.Column('source_email_id', sa.String(length=36), nullable=True),
        sa.Column('source_thread_id', sa.String(length=255), nullable=True),
        sa.Column('due_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='OPEN'),
        sa.Column('snoozed_until', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('score >= 0 AND score <= 100', name='ck_action_items_score_bounds'),
        sa.ForeignKeyConstraint(['source_email_id'], ['email_messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('action_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_action_items_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_action_items_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_action_items_due_at'), ['due_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_action_items_source_email_id'), ['source_email_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_action_items_source_thread_id'), ['source_thread_id'], unique=False)
        batch_op.create_index('ix_action_items_user_status_due', ['user_id', 'status', 'due_at'], unique=False)
        batch_op.create_index('ix_action_items_dedup', ['user_id', 'action_type', 'source_email_id'], unique=False)

    # ── 2. Create notifications table ────────────────────────────
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False, server_default='info'),
        sa.Column('source_type', sa.String(length=50), nullable=True),
        sa.Column('source_id', sa.String(length=255), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_read_at'), ['read_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_created_at'), ['created_at'], unique=False)
        batch_op.create_index('ix_notifications_user_unread', ['user_id', 'read_at', 'dismissed_at'], unique=False)
        batch_op.create_index('ix_notifications_dedup', ['user_id', 'type', 'source_type', 'source_id'], unique=False)

    # ── 3. Create saved_searches table ───────────────────────────
    op.create_table(
        'saved_searches',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('query', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_saved_searches_user_name'),
    )
    with op.batch_alter_table('saved_searches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_saved_searches_user_id'), ['user_id'], unique=False)

    # ── 4. Extend email_messages table with Phase 8 columns ─────
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_deadlines', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_meeting_proposal', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.drop_column('ai_meeting_proposal')
        batch_op.drop_column('ai_deadlines')

    op.drop_table('saved_searches')
    op.drop_table('notifications')
    op.drop_table('action_items')
