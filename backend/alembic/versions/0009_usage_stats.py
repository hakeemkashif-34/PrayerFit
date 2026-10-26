"""Add usage_stats: the app's 4 usage counts, saved once a day.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'usage_stats',
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('signed_up', sa.Integer(), nullable=False),
        sa.Column('finished_setup', sa.Integer(), nullable=False),
        sa.Column('active', sa.Integer(), nullable=False),
        sa.Column('new_this_week', sa.Integer(), nullable=False),
        sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('day'),
    )


def downgrade() -> None:
    op.drop_table('usage_stats')
