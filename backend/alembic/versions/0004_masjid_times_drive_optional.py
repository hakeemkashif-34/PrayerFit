"""Add masjid times, drive times, update jobs, drive blocks, and the optional step.

Existing data is kept:
1. Users who already finished setup get optional_saved = true, so they
   aren't sent back to setup. Their short names stay where they are.
2. Jumuah masjids get a position in name order, the order the settings
   page showed them in before.
3. Every existing event is a prayer block (kind = "prayer").

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_settings', sa.Column('optional_saved', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('user_settings', sa.Column('arrive_early_minutes', sa.SmallInteger(), server_default='0', nullable=False))
    op.add_column('user_settings', sa.Column('prayer_color_id', sa.String(length=2), nullable=True))
    op.add_column('user_settings', sa.Column('drive_color_id', sa.String(length=2), nullable=True))
    op.execute("UPDATE user_settings SET optional_saved = true WHERE setup_completed_at IS NOT NULL")

    op.add_column('user_jumuah_masjids', sa.Column('position', sa.SmallInteger(), server_default='0', nullable=False))
    op.execute(
        """
        UPDATE user_jumuah_masjids AS j SET position = ordered.position
        FROM (
            SELECT j2.user_id, j2.masjid_id,
                   row_number() OVER (PARTITION BY j2.user_id ORDER BY m.name NULLS LAST, m.id) - 1 AS position
            FROM user_jumuah_masjids j2 JOIN masjids m ON m.id = j2.masjid_id
        ) AS ordered
        WHERE j.user_id = ordered.user_id AND j.masjid_id = ordered.masjid_id
        """
    )

    op.add_column('prayer_events', sa.Column('kind', sa.String(length=8), server_default='prayer', nullable=False))
    op.add_column('prayer_events', sa.Column('color_id', sa.String(length=2), nullable=True))
    op.add_column('prayer_events', sa.Column('reminder_minutes', sa.SmallInteger(), nullable=True))
    # Postgres named this one itself in 0001.
    op.drop_constraint('prayer_events_user_id_local_date_prayer_key', 'prayer_events', type_='unique')
    op.create_unique_constraint(
        'prayer_events_user_id_local_date_prayer_kind_key', 'prayer_events', ['user_id', 'local_date', 'prayer', 'kind']
    )

    op.create_table('masjid_sources',
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=False),
    sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_changed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
    sa.Column('retry_after', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('masjid_id')
    )
    op.create_table('masjid_day_times',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('fajr_adhan', sa.Time(), nullable=False),
    sa.Column('dhuhr_adhan', sa.Time(), nullable=False),
    sa.Column('asr_adhan', sa.Time(), nullable=False),
    sa.Column('maghrib_adhan', sa.Time(), nullable=False),
    sa.Column('isha_adhan', sa.Time(), nullable=False),
    sa.Column('fajr_iqamah', sa.Time(), nullable=True),
    sa.Column('dhuhr_iqamah', sa.Time(), nullable=True),
    sa.Column('asr_iqamah', sa.Time(), nullable=True),
    sa.Column('maghrib_iqamah', sa.Time(), nullable=True),
    sa.Column('isha_iqamah', sa.Time(), nullable=True),
    sa.Column('jumuah', sa.JSON(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('masjid_id', 'local_date', 'source')
    )
    op.create_index(op.f('ix_masjid_day_times_masjid_id'), 'masjid_day_times', ['masjid_id'], unique=False)
    op.create_table('masjid_fetch_jobs',
    sa.Column('id', sa.String(length=100), nullable=False),
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_masjid_fetch_jobs_masjid_id'), 'masjid_fetch_jobs', ['masjid_id'], unique=False)
    op.create_table('user_drive_times',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.Column('seconds', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('route_key', sa.String(length=64), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'masjid_id')
    )
    op.create_table('update_jobs',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('events_sent', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )


def downgrade() -> None:
    op.drop_table('update_jobs')
    op.drop_table('user_drive_times')
    op.drop_index(op.f('ix_masjid_fetch_jobs_masjid_id'), table_name='masjid_fetch_jobs')
    op.drop_table('masjid_fetch_jobs')
    op.drop_index(op.f('ix_masjid_day_times_masjid_id'), table_name='masjid_day_times')
    op.drop_table('masjid_day_times')
    op.drop_table('masjid_sources')
    # Drive blocks didn't exist before, so they go before the old unique key comes back.
    op.execute("DELETE FROM prayer_events WHERE kind <> 'prayer'")
    op.drop_constraint('prayer_events_user_id_local_date_prayer_kind_key', 'prayer_events', type_='unique')
    op.create_unique_constraint(
        'prayer_events_user_id_local_date_prayer_key', 'prayer_events', ['user_id', 'local_date', 'prayer']
    )
    op.drop_column('prayer_events', 'reminder_minutes')
    op.drop_column('prayer_events', 'color_id')
    op.drop_column('prayer_events', 'kind')
    op.drop_column('user_jumuah_masjids', 'position')
    op.drop_column('user_settings', 'drive_color_id')
    op.drop_column('user_settings', 'prayer_color_id')
    op.drop_column('user_settings', 'arrive_early_minutes')
    op.drop_column('user_settings', 'optional_saved')
