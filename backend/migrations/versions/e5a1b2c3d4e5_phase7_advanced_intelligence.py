"""phase7_advanced_intelligence

Revision ID: e5a1b2c3d4e5
Revises: 4b0e9c8d7e6f
Create Date: 2026-09-09 01:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a1b2c3d4e5'
down_revision = '4b0e9c8d7e6f'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Create user_preferences table ─────────────────────────
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('preferred_priority_behavior', sa.String(length=50), nullable=False, server_default='balanced'),
        sa.Column('important_senders', sa.Text(), nullable=True),
        sa.Column('ignored_senders', sa.Text(), nullable=True),
        sa.Column('preferred_categories', sa.Text(), nullable=True),
        sa.Column('default_inbox_view', sa.String(length=50), nullable=False, server_default='needs_action'),
        sa.Column('show_low_priority', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('smart_inbox_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('follow_up_detection_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('follow_up_threshold_days', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('ai_summary_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_contact_insights_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('ai_analysis_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('auto_ai_analysis', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_user_preferences_user_id'),
    )
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_preferences_user_id'), ['user_id'], unique=True)

    # ── 2. Create user_feedback_signals table ────────────────────
    op.create_table(
        'user_feedback_signals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('signal_type', sa.String(length=50), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('target_value', sa.String(length=255), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_feedback_signals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_feedback_signals_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_feedback_signals_signal_type'), ['signal_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_feedback_signals_target_type'), ['target_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_feedback_signals_target_value'), ['target_value'], unique=False)
        batch_op.create_index('ix_user_feedback_lookup', ['user_id', 'target_type', 'target_value'], unique=False)

    # ── 3. Add composite indexes on email_messages ──────────────
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.create_index('ix_email_messages_user_thread', ['user_id', 'thread_id'], unique=False)
        batch_op.create_index('ix_email_messages_user_from', ['user_id', 'from_address'], unique=False)


def downgrade():
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.drop_index('ix_email_messages_user_from')
        batch_op.drop_index('ix_email_messages_user_thread')

    op.drop_table('user_feedback_signals')
    op.drop_table('user_preferences')
