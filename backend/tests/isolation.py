"""Pure test-database identity guard shared by pytest and the E2E tooling (guide 07 §3)."""

import re

from dotenv import dotenv_values
from sqlalchemy import URL, make_url

from app.core.config import BACKEND_DIR

TEST_ROLE = "cognuance_test"
TEST_DB_NAME = re.compile(r"^cognuance_test(_[a-z0-9]+)?$")


class UnsafeTestDatabase(RuntimeError):
    pass


def dev_database_url() -> str | None:
    return dotenv_values(BACKEND_DIR / ".env").get("DATABASE_URL")


def configured_test_url(environ: dict[str, str]) -> str | None:
    return environ.get("TEST_DATABASE_URL") or dotenv_values(BACKEND_DIR / ".env.test").get(
        "TEST_DATABASE_URL"
    )


def identity(url: URL) -> tuple[str, int, str]:
    """Normalized (host, port, database): passwords/query strings never make two URLs different."""
    host = (url.host or "").lower()
    host = "127.0.0.1" if host in ("localhost", "::1", "[::1]") else host
    return host, int(url.port or 5432), url.database or ""


def check_test_url(
    test_url: str | None, dev_url: str | None, app_env: str | None, database: str | None = None
) -> URL:
    if not test_url:
        raise UnsafeTestDatabase(
            "TEST_DATABASE_URL is required (backend/.env.test). Start the disposable instance with "
            "`docker compose -f compose.test.yaml --env-file backend/.env.test up -d --wait`."
        )
    url = make_url(test_url)
    if database is not None:
        url = url.set(database=database)
    if url.username != TEST_ROLE or not TEST_DB_NAME.match(url.database or ""):
        raise UnsafeTestDatabase(
            "TEST_DATABASE_URL must use the cognuance_test role and a cognuance_test* database"
        )
    if dev_url and identity(url)[:2] == identity(make_url(dev_url))[:2]:
        raise UnsafeTestDatabase("TEST_DATABASE_URL points at the development PostgreSQL instance")
    if app_env != "test":
        raise UnsafeTestDatabase("APP_ENV must be 'test'")
    return url
