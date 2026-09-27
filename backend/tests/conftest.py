"""Test configuration (guide 07 §3).

Process env vars take precedence over backend/.env, so the app under test points at an
unreachable database by default. Database tests need an explicit **TEST_DATABASE_URL** (process
env or the private `backend/.env.test`) for the disposable instance in `compose.test.yaml`; there is
no fallback to the development DATABASE_URL. `test_engine` refuses any URL that is not the
dedicated test role/database or that resolves to the same host/port/database as development.
Each test's changes are rolled back; race/migration tests use separate throwaway databases on the
same test instance.
"""

import os

from app.core.config import BACKEND_DIR
from tests.isolation import TEST_DB_NAME, TEST_ROLE, configured_test_url, dev_database_url  # noqa: F401

_DEV_DATABASE_URL = dev_database_url()
_TEST_DATABASE_URL = configured_test_url(dict(os.environ))

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://test_user:test-password-should-not-leak@127.0.0.1:1/test_db"
)
os.environ.pop("TEST_DATABASE_URL", None)  # read once above; never visible to the app under test
os.environ["JWT_SECRET"] = "test-only-jwt-secret-with-enough-length-0123456789"
os.environ["MODEL_MODE"] = "unconfigured"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_login_limiter():
    from app.services.login_limiter import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def guarded_test_url(database: str | None = None):
    """The explicit test URL (optionally another disposable DB on the same test instance), or fail."""
    from tests.isolation import UnsafeTestDatabase, check_test_url

    try:
        return check_test_url(_TEST_DATABASE_URL, _DEV_DATABASE_URL, os.environ.get("APP_ENV"), database)
    except UnsafeTestDatabase as exc:
        pytest.fail(str(exc))


@pytest.fixture(scope="session")
def test_engine():
    test_url = guarded_test_url()
    try:
        probe = create_engine(test_url, connect_args={"connect_timeout": 3})
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
        probe.dispose()
    except Exception as exc:
        hint = "is `docker compose -f compose.test.yaml --env-file backend/.env.test up -d --wait` running?"
        pytest.fail(f"Test PostgreSQL unavailable ({hint}): {type(exc).__name__}")

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = test_url.render_as_string(hide_password=False)
    command.upgrade(config, "head")

    engine = create_engine(test_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """A session whose commits become savepoints inside a transaction rolled back after the test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        app.dependency_overrides.pop(get_db, None)


DEMO_PASSWORD = "test-demo-password-123"


@pytest.fixture
def seeded(db_session):
    from app.scripts.seed_demo import seed_demo

    seed_demo(db_session, DEMO_PASSWORD)
    return db_session


@pytest.fixture
def login_as(client):
    """Returns a function email -> Authorization headers (real login through the API)."""

    def _login(email: str) -> dict[str, str]:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login
