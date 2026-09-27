"""Throwaway databases on the disposable test instance (guide 07 §3, §4.3, §4.5).

Only `cognuance_test_*` names on the guarded test URL can be created or dropped here.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, text

from app.core.config import BACKEND_DIR
from tests.conftest import TEST_DB_NAME, guarded_test_url


def alembic_config(url: URL) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url.render_as_string(hide_password=False)
    return config


@contextmanager
def throwaway_database(name: str) -> Iterator[URL]:
    assert TEST_DB_NAME.match(name) and name != "cognuance_test", name
    url = guarded_test_url(name)
    admin = create_engine(guarded_test_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def upgrade(url: URL, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)
