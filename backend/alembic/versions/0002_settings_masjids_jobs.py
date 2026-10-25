"""Add setup answers, masjids, caches, nightly jobs, and event titles.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('api_throttle',
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('last_request_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('geocode_cache',
    sa.Column('query_hash', sa.String(length=64), nullable=False),
    sa.Column('result_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('query_hash')
    )
    op.create_table('overpass_cache',
    sa.Column('cell', sa.String(length=32), nullable=False),
    sa.Column('masjid_ids', sa.JSON(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('cell')
    )
    op.create_table('masjids',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('osm_type', sa.String(length=8), nullable=True),
    sa.Column('osm_id', sa.BigInteger(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('osm_type', 'osm_id')
    )
    op.create_index(op.f('ix_masjids_created_by_user_id'), 'masjids', ['created_by_user_id'], unique=False)
    op.create_table('nightly_jobs',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('events_sent', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'local_date')
    )
    op.create_index(op.f('ix_nightly_jobs_user_id'), 'nightly_jobs', ['user_id'], unique=False)
    op.create_table('weekly_masjid_prayers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=False),
    sa.Column('fajr', sa.Boolean(), nullable=False),
    sa.Column('dhuhr', sa.Boolean(), nullable=False),
    sa.Column('asr', sa.Boolean(), nullable=False),
    sa.Column('maghrib', sa.Boolean(), nullable=False),
    sa.Column('isha', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'weekday')
    )
    op.create_index(op.f('ix_weekly_masjid_prayers_user_id'), 'weekly_masjid_prayers', ['user_id'], unique=False)
    op.create_table('user_jumuah_masjids',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('masjid_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['masjid_id'], ['masjids.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'masjid_id')
    )
    op.create_table('user_settings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('address_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('place_name_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('location_encrypted', sa.LargeBinary(), nullable=True),
    sa.Column('time_zone', sa.String(length=64), nullable=True),
    sa.Column('method', sa.String(length=16), nullable=True),
    sa.Column('asr_method', sa.String(length=16), nullable=True),
    sa.Column('main_masjid_choice', sa.String(length=8), nullable=True),
    sa.Column('main_masjid_id', sa.Uuid(), nullable=True),
    sa.Column('main_masjid_short_name', sa.String(length=40), nullable=True),
    sa.Column('jumuah_saved', sa.Boolean(), nullable=False),
    sa.Column('setup_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['main_masjid_id'], ['masjids.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )
    op.add_column('prayer_events', sa.Column('place', sa.String(length=8), nullable=True))
    op.add_column('prayer_events', sa.Column('masjid_id', sa.Uuid(), nullable=True))
    op.add_column('prayer_events', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('prayer_events', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('prayer_events', sa.Column('synced_hash', sa.String(length=64), nullable=True))
    op.create_foreign_key('prayer_events_masjid_id_fkey', 'prayer_events', 'masjids', ['masjid_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('prayer_events_masjid_id_fkey', 'prayer_events', type_='foreignkey')
    op.drop_column('prayer_events', 'synced_hash')
    op.drop_column('prayer_events', 'description')
    op.drop_column('prayer_events', 'summary')
    op.drop_column('prayer_events', 'masjid_id')
    op.drop_column('prayer_events', 'place')
    op.drop_table('user_settings')
    op.drop_table('user_jumuah_masjids')
    op.drop_index(op.f('ix_weekly_masjid_prayers_user_id'), table_name='weekly_masjid_prayers')
    op.drop_table('weekly_masjid_prayers')
    op.drop_index(op.f('ix_nightly_jobs_user_id'), table_name='nightly_jobs')
    op.drop_table('nightly_jobs')
    op.drop_index(op.f('ix_masjids_created_by_user_id'), table_name='masjids')
    op.drop_table('masjids')
    op.drop_table('overpass_cache')
    op.drop_table('geocode_cache')
    op.drop_table('api_throttle')
