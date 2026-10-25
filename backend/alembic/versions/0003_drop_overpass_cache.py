"""Drop the Overpass cache. Masjids come from Photon now.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('overpass_cache')


def downgrade() -> None:
    op.create_table('overpass_cache',
    sa.Column('cell', sa.String(length=32), nullable=False),
    sa.Column('masjid_ids', sa.JSON(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('cell')
    )
