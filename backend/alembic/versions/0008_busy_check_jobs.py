"""Add busy_check_jobs: the 15-minute checks of each user's busy times.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'busy_check_jobs',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('block_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('events_sent', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_busy_check_jobs_user_id'), 'busy_check_jobs', ['user_id'], unique=False)
    op.create_index(op.f('ix_busy_check_jobs_block_start'), 'busy_check_jobs', ['block_start'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_busy_check_jobs_block_start'), table_name='busy_check_jobs')
    op.drop_index(op.f('ix_busy_check_jobs_user_id'), table_name='busy_check_jobs')
    op.drop_table('busy_check_jobs')
