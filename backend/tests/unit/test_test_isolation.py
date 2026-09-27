"""The test-database guard (guide 07 §3) refuses anything but the disposable test instance."""

import pytest

from tests import conftest

TEST = "postgresql+psycopg://cognuance_test:pw@127.0.0.1:55432/cognuance_test"
DEV = "postgresql+psycopg://cognitive_app:other@localhost:5432/cognitive_monitoring"


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.setattr(conftest, "_DEV_DATABASE_URL", DEV)

    def check(url: str | None, database: str | None = None):
        monkeypatch.setattr(conftest, "_TEST_DATABASE_URL", url)
        return conftest.guarded_test_url(database)

    return check


def test_accepts_the_dedicated_instance_and_its_throwaway_databases(guard):
    assert guard(TEST).database == "cognuance_test"
    assert guard(TEST, "cognuance_test_races").database == "cognuance_test_races"


@pytest.mark.parametrize(
    "url",
    [
        None,  # no silent fallback to DATABASE_URL
        # the dev instance (same host:port), whatever the credentials or query string
        "postgresql+psycopg://cognuance_test:pw@127.0.0.1:5432/cognuance_test",
        "postgresql+psycopg://cognuance_test:different@localhost:5432/cognuance_test?sslmode=disable",
        "postgresql+psycopg://cognitive_app:pw@127.0.0.1:55432/cognuance_test",  # wrong role
        "postgresql+psycopg://cognuance_test:pw@127.0.0.1:55432/cognitive_monitoring",  # not disposable
        "postgresql+psycopg://cognuance_test:pw@127.0.0.1:55432/my_test",  # "test" in the name is not enough
    ],
)
def test_refuses_anything_else(guard, url):
    with pytest.raises(pytest.fail.Exception):
        guard(url)
