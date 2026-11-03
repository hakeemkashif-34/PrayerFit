"""Give masjid prayer events a location: the masjid's name and public address.

Only masjid prayer blocks get one. Home, moved, and clash prayers stay empty,
and the user's home address is never put in an event.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('prayer_events', sa.Column('location', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('prayer_events', 'location')
