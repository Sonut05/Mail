"""phase6_advanced_intelligence

Revision ID: 3a9f8b7c6d5e
Revises: 28814bc4372b
Create Date: 2026-09-08 23:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a9f8b7c6d5e'
down_revision = '28814bc4372b'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Add new Phase 6 intelligence fields
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_importance_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('ai_confidence_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('ai_key_points', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_waiting_for', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_next_action', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_reasons', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ai_retry_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('ai_last_error', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_email_messages_ai_importance_score'), ['ai_importance_score'], unique=False)

    # Step 2: Backfill safe defaults for existing records
    op.execute("UPDATE email_messages SET ai_retry_count = 0 WHERE ai_retry_count IS NULL")


def downgrade():
    with op.batch_alter_table('email_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_messages_ai_importance_score'))
        batch_op.drop_column('ai_last_error')
        batch_op.drop_column('ai_retry_count')
        batch_op.drop_column('ai_reasons')
        batch_op.drop_column('ai_next_action')
        batch_op.drop_column('ai_waiting_for')
        batch_op.drop_column('ai_key_points')
        batch_op.drop_column('ai_confidence_score')
        batch_op.drop_column('ai_importance_score')
