"""Drop usage_stats, the daily snapshot of the old /stats counts.

The /stats page now shows total users and a graph of total users per day,
worked out from each user's sign-up date (users.created_at). So nothing has
to be saved each day, and the old counts (finished setup, active, new this
week) aren't shown anywhere.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('usage_stats')


def downgrade() -> None:
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
