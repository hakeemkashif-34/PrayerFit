"""Runs migrations. Alembic calls this for every alembic command."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.db import database_url
from app.models import Base

config = context.config

# Only set up logging when run from the command line. Tests have their own,
# and fileConfig would otherwise switch off pytest's loggers.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Lets "alembic revision --autogenerate" compare the models with the database.
target_metadata = Base.metadata


def run_migrations() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations()
