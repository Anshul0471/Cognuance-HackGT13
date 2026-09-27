"""Isolated E2E stack for Playwright (guide 07 §6): database `cognuance_test_e2e` on the disposable
test instance, private per-run secrets, and a workspace under backend/data/e2e (git-ignored).

Test-only tooling: never imported by the application, refuses anything but the guarded test URL.
"""

import json
import os
import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import BACKEND_DIR
from tests.isolation import check_test_url, configured_test_url, dev_database_url

E2E_DB = "cognuance_test_e2e"
WORKSPACE = BACKEND_DIR / "data" / "e2e"
SECRETS = WORKSPACE / "secrets.json"
ENV_OUT = BACKEND_DIR.parent / "frontend" / "e2e" / ".auth" / "env.json"
API_PORT = 8100
WEB_PORT = 4180


def e2e_url():
    return check_test_url(configured_test_url(dict(os.environ)), dev_database_url(), "test", E2E_DB)


def private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, default=str)


def run_secrets() -> dict[str, str]:
    """Fresh per-run secrets (a new stack every run); kept only in the private workspace."""
    data = {"jwt_secret": secrets.token_urlsafe(48), "demo_password": secrets.token_urlsafe(18)}
    private_write(SECRETS, data)
    return data


def app_environment(url, run: dict[str, str]) -> dict[str, str]:
    return {
        "APP_ENV": "test",
        "DEMO_MODE": "true",
        "DATABASE_URL": url.render_as_string(hide_password=False),
        "JWT_SECRET": run["jwt_secret"],
        "DEMO_ACCOUNT_PASSWORD": run["demo_password"],
        "MODEL_MODE": "gru",
        "MODEL_ARTIFACT_DIR": str(WORKSPACE / "artifacts"),
        "SYNTHETIC_DATA_DIR": str(WORKSPACE / "synthetic"),
        "CORS_ORIGINS": "[]",
        "LOG_LEVEL": "WARNING",
    }


def fresh_workspace() -> None:
    """Reset only the E2E workspace; copy (never mutate) the verified model bundle and its run."""
    for sub in ("synthetic", "showcase-private"):
        shutil.rmtree(WORKSPACE / sub, ignore_errors=True)
    artifacts = WORKSPACE / "artifacts"
    if not (artifacts / "forecast-run-v1-gru").exists():
        artifacts.mkdir(parents=True, exist_ok=True)
        shutil.copytree(BACKEND_DIR / "artifacts" / "forecast-run-v1-gru", artifacts / "forecast-run-v1-gru")
        shutil.copytree(
            BACKEND_DIR / "artifacts" / "runs" / "forecast-run-v1", artifacts / "runs" / "forecast-run-v1"
        )


def window_times(now: datetime | None = None) -> tuple[datetime, datetime]:
    """as_of one hour ago, live target one hour ahead: the ±12 h window is open for this run."""
    now = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    return now - timedelta(hours=1), now + timedelta(hours=1)
