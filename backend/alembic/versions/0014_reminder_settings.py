"""Add the 3 notification settings: minutes before iqamah, leaving, and home prayers.

Each one is a Google Calendar popup reminder on the matching events. Empty
means no notification. Everyone, existing users too, starts with 5 minutes
before leaving and before home prayers, and none before iqamah.

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


def upgrade() -> None:
    op.add_column('user_settings', sa.Column('masjid_reminder_minutes', sa.SmallInteger(), nullable=True))
    # A column added with a default fills every existing row with it, so existing users get 5 too.
    op.add_column('user_settings', sa.Column('leave_reminder_minutes', sa.SmallInteger(), server_default='5', nullable=True))
    op.add_column('user_settings', sa.Column('home_reminder_minutes', sa.SmallInteger(), server_default='5', nullable=True))


def downgrade() -> None:
    for column in ('masjid_reminder_minutes', 'leave_reminder_minutes', 'home_reminder_minutes'):
        op.drop_column('user_settings', column)
