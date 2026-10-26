"""Add each user's main masjid as their Jumuah masjid, if they have none.

From now on, picking a main masjid makes it the first Jumuah masjid (see
user_settings.follow_main_masjid). This does the same for users who
picked theirs before. Users who already have Jumuah masjids are left alone.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op


# Alembic uses these to put migrations in order.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO user_jumuah_masjids (user_id, masjid_id, position)
        SELECT s.user_id, s.main_masjid_id, 0
        FROM user_settings s
        WHERE s.main_masjid_choice = 'masjid'
          AND s.main_masjid_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM user_jumuah_masjids j WHERE j.user_id = s.user_id)
        """
    )
    op.execute(
        """
        UPDATE user_settings s SET jumuah_saved = true
        WHERE EXISTS (SELECT 1 FROM user_jumuah_masjids j WHERE j.user_id = s.user_id)
        """
    )


def downgrade() -> None:
    # Nothing to undo safely: an added row looks the same as one the user
    # picked, so removing them could delete a user's own choice.
    pass
