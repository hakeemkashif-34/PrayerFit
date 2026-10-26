"""Jumuah is always at the main masjid. Remove the separate Jumuah masjids.

Existing data:
1. The user_jumuah_masjids table is dropped, so extra Jumuah masjids are gone.
2. A Jumuah pick at the main masjid stays. Any other pick (or none) resets
   to the main masjid's 1st Jumuah.
3. Someone who prays at home has no Jumuah, so their pick is cleared.
4. jumuah_saved is dropped. It only said whether the Jumuah masjids were saved.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE user_settings
        SET jumuah_pick_masjid_id = main_masjid_id, jumuah_pick_order = 1
        WHERE main_masjid_choice = 'masjid' AND main_masjid_id IS NOT NULL
          AND jumuah_pick_masjid_id IS DISTINCT FROM main_masjid_id
        """
    )
    op.execute(
        """
        UPDATE user_settings
        SET jumuah_pick_masjid_id = NULL, jumuah_pick_order = NULL
        WHERE main_masjid_choice IS DISTINCT FROM 'masjid' OR main_masjid_id IS NULL
        """
    )
    op.drop_table('user_jumuah_masjids')
    op.drop_column('user_settings', 'jumuah_saved')


def downgrade() -> None:
    op.add_column('user_settings', sa.Column('jumuah_saved', sa.Boolean(), server_default='false', nullable=False))
    op.create_table(
        'user_jumuah_masjids',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('masjid_id', sa.Uuid(), nullable=False),
        sa.Column('position', sa.SmallInteger(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'masjid_id'),
    )
    # Back to how it was before: the main masjid is the Jumuah masjid.
    op.execute(
        """
        INSERT INTO user_jumuah_masjids (user_id, masjid_id, position)
        SELECT user_id, main_masjid_id, 0 FROM user_settings
        WHERE main_masjid_choice = 'masjid' AND main_masjid_id IS NOT NULL
        """
    )
    op.execute(
        "UPDATE user_settings SET jumuah_saved = true WHERE main_masjid_choice = 'masjid' AND main_masjid_id IS NOT NULL"
    )
