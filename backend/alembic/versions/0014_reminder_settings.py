"""Add the 3 notification settings: minutes before iqamah, leaving, and home prayers.

Each one is a Google Calendar popup reminder on the matching events. Empty
means no notification, so every existing user starts with none.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ('masjid_reminder_minutes', 'leave_reminder_minutes', 'home_reminder_minutes')


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column('user_settings', sa.Column(column, sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    for column in COLUMNS:
        op.drop_column('user_settings', column)
