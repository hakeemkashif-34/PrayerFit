"""Add user_count_changes, the anonymous sign-up and deletion counts per hour.

The /stats graph used to add up users.created_at. A deleted user's row is
gone, so they vanished from the past too and the line could only go up.
Now each hour keeps how many signed up and how many deleted their account,
with nothing that leads back to a person.

The table starts with today's users, by the hour they signed up. People who
deleted their account before this migration can't be counted any more.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_count_changes',
        sa.Column('hour', sa.DateTime(timezone=True), nullable=False),
        sa.Column('signed_up', sa.Integer(), server_default='0', nullable=False),
        sa.Column('deleted', sa.Integer(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('hour'),
    )
    # Each user's sign-up hour, counted in UTC so the session's time zone doesn't matter.
    op.execute(
        """
        INSERT INTO user_count_changes (hour, signed_up, deleted)
        SELECT date_trunc('hour', created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC', count(*), 0
        FROM users
        GROUP BY 1
        """
    )


def downgrade() -> None:
    op.drop_table('user_count_changes')
