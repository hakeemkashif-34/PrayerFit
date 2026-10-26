"""Add prayer_events.fit: whether busy times moved the prayer.

Every existing row is "normal", since nothing was moved before milestone 6.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic uses these to put migrations in order.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('prayer_events', sa.Column('fit', sa.String(length=8), server_default='normal', nullable=False))


def downgrade() -> None:
    op.drop_column('prayer_events', 'fit')
