"""phase6_1_durable_ai_jobs

Revision ID: 4b0e9c8d7e6f
Revises: 3a9f8b7c6d5e
Create Date: 2026-09-09 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4b0e9c8d7e6f'
down_revision = '3a9f8b7c6d5e'
branch_labels = None
depends_on = None


def upgrade():
    # Step 1: Create the ai_analysis_jobs table
    op.create_table(
        'ai_analysis_jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_by', sa.String(length=128), nullable=True),
        sa.Column('lease_token', sa.String(length=64), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # Step 2: Create indexes
    op.create_index('ix_ai_analysis_jobs_email_id', 'ai_analysis_jobs', ['email_id'], unique=False)
    op.create_index('ix_ai_analysis_jobs_user_id', 'ai_analysis_jobs', ['user_id'], unique=False)
    op.create_index('ix_ai_analysis_jobs_status', 'ai_analysis_jobs', ['status'], unique=False)
    op.create_index('ix_ai_analysis_jobs_available_at', 'ai_analysis_jobs', ['available_at'], unique=False)
    op.create_index('ix_ai_analysis_jobs_locked_at', 'ai_analysis_jobs', ['locked_at'], unique=False)
    op.create_index('ix_ai_jobs_claim', 'ai_analysis_jobs', ['status', 'available_at'], unique=False)
    op.create_index('ix_ai_jobs_stale', 'ai_analysis_jobs', ['status', 'locked_at'], unique=False)

    # Step 3: Create partial unique index guaranteeing at most 1 active job per email
    op.create_index(
        'uq_active_ai_job_per_email',
        'ai_analysis_jobs',
        ['email_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade():
    op.drop_index('uq_active_ai_job_per_email', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_jobs_stale', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_jobs_claim', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_analysis_jobs_locked_at', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_analysis_jobs_available_at', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_analysis_jobs_status', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_analysis_jobs_user_id', table_name='ai_analysis_jobs')
    op.drop_index('ix_ai_analysis_jobs_email_id', table_name='ai_analysis_jobs')
    op.drop_table('ai_analysis_jobs')
