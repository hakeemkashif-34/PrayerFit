"""Let my masjid list hold masjids from sources other than MAWAQIT.

Masjid ar-Rahmah (AMA) isn't on MAWAQIT. Its times come from its own
website, mymasjid.ca. Each list entry now says which source it's read from,
and every row already there is a MAWAQIT one.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mawaqit_list', sa.Column('source', sa.String(16), nullable=False, server_default='mawaqit'))


def downgrade() -> None:
    op.drop_column('mawaqit_list', 'source')
