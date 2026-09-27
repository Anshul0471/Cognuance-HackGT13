"""Hosted-demo provisioning opt-in and docs exposure (guide 07 §10–§11)."""

import pytest

from app.core.config import get_settings
from app.core.provisioning import ProvisioningRefused, check_provisioning


@pytest.fixture
def env(monkeypatch):
    def set_env(**values):
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return get_settings()

    yield set_env
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("app_env", "demo_mode", "hosted_flag", "allowed"),
    [
        ("development", "true", False, True),
        ("test", "true", False, True),
        ("demo", "true", True, True),
        ("demo", "true", False, False),  # hosted demo needs the deliberate opt-in
        ("development", "true", True, False),  # the opt-in cannot disguise another environment
        ("production", "true", True, False),
        ("production", "true", False, False),
        ("development", "false", False, False),
        ("demo", "false", True, False),
    ],
)
def test_provisioning_guard(env, app_env, demo_mode, hosted_flag, allowed):
    env(APP_ENV=app_env, DEMO_MODE=demo_mode)
    if allowed:
        check_provisioning(hosted_flag)
    else:
        with pytest.raises(ProvisioningRefused):
            check_provisioning(hosted_flag)


def test_docs_are_deliberate(env):
    assert env(APP_ENV="development").docs_enabled
    assert not env(APP_ENV="demo").docs_enabled
    assert not env(APP_ENV="production").docs_enabled
    assert env(APP_ENV="demo", API_DOCS_ENABLED="true").docs_enabled
