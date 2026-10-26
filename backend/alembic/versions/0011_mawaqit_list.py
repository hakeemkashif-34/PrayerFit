"""Add mawaqit_list, my list of MAWAQIT masjids, and automatic links.

1. mawaqit_list: one row per masjid on the list. The rows themselves are
   loaded from app/data/mawaqit_masjids.csv when the app starts, not here,
   so adding a masjid to the file doesn't need a new migration.
2. masjid_sources.origin: "admin" (link-mawaqit) or "auto" (matched to the
   list). Every link that already exists was made by hand, so it's "admin".
3. masjid_sources.list_external_id and match_distance_m: which list entry
   an automatic link matched, and how far away it is, for spot-checks.
4. masjids.no_auto_link: set by unlink-mawaqit, so a link I removed by
   hand isn't added back.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mawaqit_list',
        sa.Column('external_id', sa.String(length=200), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('added_by', sa.String(length=8), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('external_id'),
    )
    op.add_column(
        'masjid_sources',
        sa.Column('origin', sa.String(length=8), server_default='admin', nullable=False),
    )
    op.add_column('masjid_sources', sa.Column('list_external_id', sa.String(length=200), nullable=True))
    op.add_column('masjid_sources', sa.Column('match_distance_m', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'masjid_sources_list_external_id_fkey', 'masjid_sources', 'mawaqit_list',
        ['list_external_id'], ['external_id'], ondelete='SET NULL',
    )
    op.add_column(
        'masjids',
        sa.Column('no_auto_link', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('masjids', 'no_auto_link')
    op.drop_constraint('masjid_sources_list_external_id_fkey', 'masjid_sources', type_='foreignkey')
    op.drop_column('masjid_sources', 'match_distance_m')
    op.drop_column('masjid_sources', 'list_external_id')
    op.drop_column('masjid_sources', 'origin')
    op.drop_table('mawaqit_list')
