"""Add the Jumuah pick, Jumuah "how early", Jumuah length, and commute times. Remove the prayer time method.

Existing data is kept:
1. Each user's Jumuah "how early" starts as their current "how early".
2. Nobody has a Jumuah pick yet, so the earliest Jumuah that fits is used.
3. Masjids have no Jumuah length yet, so 45 minutes is used.
4. The saved calculation method and Asr method are dropped. Calculated
   times always use ISNA with standard Asr now. The next calendar update
   sends only the future events that changed.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_settings', sa.Column('jumuah_arrive_early_minutes', sa.SmallInteger(), server_default='5', nullable=False))
    op.execute("UPDATE user_settings SET jumuah_arrive_early_minutes = arrive_early_minutes")
    op.add_column('user_settings', sa.Column('jumuah_pick_masjid_id', sa.Uuid(), nullable=True))
    op.add_column('user_settings', sa.Column('jumuah_pick_order', sa.SmallInteger(), nullable=True))
    op.create_foreign_key(
        'user_settings_jumuah_pick_masjid_id_fkey', 'user_settings', 'masjids',
        ['jumuah_pick_masjid_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_column('user_settings', 'method')
    op.drop_column('user_settings', 'asr_method')

    op.add_column('masjids', sa.Column('jumuah_minutes', sa.SmallInteger(), nullable=True))

    op.create_table('user_commute_times',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.Column('minutes', sa.SmallInteger(), nullable=False),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'masjid_id')
    )


def downgrade() -> None:
    op.drop_table('user_commute_times')
    op.drop_column('masjids', 'jumuah_minutes')
    # The methods come back empty, which means ISNA and standard Asr.
    op.add_column('user_settings', sa.Column('asr_method', sa.String(length=16), nullable=True))
    op.add_column('user_settings', sa.Column('method', sa.String(length=16), nullable=True))
    op.drop_constraint('user_settings_jumuah_pick_masjid_id_fkey', 'user_settings', type_='foreignkey')
    op.drop_column('user_settings', 'jumuah_pick_order')
    op.drop_column('user_settings', 'jumuah_pick_masjid_id')
    op.drop_column('user_settings', 'jumuah_arrive_early_minutes')
