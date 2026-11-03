"""Save a source's Jumuah times for the coming Friday apart from its days.

mymasjid.ca only shows today, so there's no row for Friday until Friday
comes. It shows the Jumuah times every day, so they're saved on the
masjid's source instead, like {"friday": "2026-11-06", "slots": [...]}.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('masjid_sources', sa.Column('upcoming_jumuah', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('masjid_sources', 'upcoming_jumuah')
