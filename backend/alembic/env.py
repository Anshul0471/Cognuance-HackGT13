from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata from all models imported in app.models, for autogenerate support.
target_metadata = Base.metadata

# The URL comes from validated settings (backend/.env), never from alembic.ini, and is passed
# directly rather than through config.set_main_option to avoid ConfigParser interpolation.
# Programmatic callers (the test suite) may supply config.attributes["database_url"] instead.
database_url = config.attributes.get("database_url") or get_settings().DATABASE_URL.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL without a live connection."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the configured database."""
    connectable = create_engine(database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
