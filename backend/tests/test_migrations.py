"""Check the migrations build the same tables the models describe."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import Base


def test_migrations_match_the_models(db):
    with db.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # Empty means nobody changed a model without adding a migration.
    assert differences == []
