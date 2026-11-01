"""Let setup search my own list of MAWAQIT masjids by name and short name.

1. mawaqit_list gets a short name (like "BIC") and an address, both optional.
2. masjids gets list_external_id: the list entry a masjid was picked from.
   It's unique, so picking the same list masjid again reuses its row.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mawaqit_list', sa.Column('short_name', sa.Text(), nullable=True))
    op.add_column('mawaqit_list', sa.Column('address', sa.Text(), nullable=True))
    op.add_column('masjids', sa.Column('list_external_id', sa.String(200), nullable=True))
    op.create_unique_constraint('uq_masjids_list_external_id', 'masjids', ['list_external_id'])


def downgrade() -> None:
    op.drop_constraint('uq_masjids_list_external_id', 'masjids', type_='unique')
    op.drop_column('masjids', 'list_external_id')
    op.drop_column('mawaqit_list', 'address')
    op.drop_column('mawaqit_list', 'short_name')
