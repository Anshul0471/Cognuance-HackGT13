"""Verify the local development setup.

Run from backend/:  uv run --extra ml python -m app.scripts.check_setup

Exits nonzero if any required check fails. Never prints secrets or connection URLs.
"""

import importlib
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

REQUIRED_IMPORTS = [
    "fastapi",
    "uvicorn",
    "pydantic_settings",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pwdlib",
    "jwt",
    "email_validator",
    "multipart",
    "numpy",
    "pandas",
    "sklearn",
    "joblib",
    "torch",
]


class CheckFailed(Exception):
    pass


def check_settings() -> str:
    from app.core.config import get_settings

    settings = get_settings()
    return f"env={settings.APP_ENV}, model_mode={settings.MODEL_MODE}, device={settings.ML_DEVICE}"


def check_database() -> str:
    from app.db.session import get_engine
    from app.services.readiness import check_database as db_check

    result = db_check(get_engine())
    if not result.ok:
        raise CheckFailed(result.detail)
    return "SELECT 1 succeeded"


def check_migrations() -> str:
    from app.db.session import get_engine
    from app.services.readiness import check_migrations as migration_check

    result = migration_check(get_engine())
    if not result.ok:
        raise CheckFailed(result.detail)
    return result.detail


def check_directories() -> str:
    from app.core.config import get_settings

    settings = get_settings()
    checked = []
    for directory in (settings.SYNTHETIC_DATA_DIR, settings.MODEL_ARTIFACT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".write-check-"):
            pass
        checked.append(
            str(directory.relative_to(Path.cwd()) if directory.is_relative_to(Path.cwd()) else directory)
        )
    return "writable: " + ", ".join(checked)


def check_imports() -> str:
    missing = []
    for module in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(module)
    if missing:
        raise CheckFailed("missing: " + ", ".join(missing) + " (install with `uv sync --locked --extra ml`)")
    return f"{len(REQUIRED_IMPORTS)} packages importable"


def check_auth_primitives() -> str:
    import jwt as pyjwt

    from app.core.config import get_settings
    from app.core.security import create_access_token, decode_access_token, hash_password, verify_password

    hashed = hash_password("setup-check-password")
    if not hashed.startswith("$argon2") or not verify_password("setup-check-password", hashed):
        raise CheckFailed("Argon2 hash/verify round trip failed")
    if verify_password("wrong-password", hashed):
        raise CheckFailed("Argon2 accepted a wrong password")

    settings = get_settings()
    claims = decode_access_token(create_access_token("setup-check", settings, "setup-session"), settings)
    if claims.get("sub") != "setup-check":
        raise CheckFailed("JWT round trip returned wrong subject")
    try:
        decode_access_token("not-a-token", settings)
    except pyjwt.PyJWTError:
        pass
    else:
        raise CheckFailed("JWT decode accepted an invalid token")
    return "Argon2 hash/verify and JWT encode/decode OK"


def check_torch_cpu() -> str:
    import torch

    from app.core.config import get_settings
    from app.ml.reproducibility import seed_everything

    seed_everything(get_settings().RANDOM_SEED)
    total = torch.ones(2, 3, device="cpu").sum().item()
    if total != 6.0:
        raise CheckFailed(f"expected tensor sum 6.0, got {total}")
    return f"torch {torch.__version__}, CPU tensor sum = {total}"


def check_model_status_honest() -> str:
    from app.core.config import get_settings
    from app.db.session import get_sessionmaker
    from app.ml.status import get_model_status

    settings = get_settings()
    with get_sessionmaker()() as db:
        status = get_model_status(settings, db)
    if settings.MODEL_MODE == "unconfigured" and (status.forecast_ready or status.model_loaded):
        raise CheckFailed("model reported ready while MODEL_MODE=unconfigured")
    if status.forecast_ready and not (status.model_loaded and status.policy_ready):
        raise CheckFailed("forecast_ready without a loaded model and a ready policy")
    if status.forecast_ready:
        return f"forecast ready: {status.model_kind} {status.model_version} / {status.policy_version}"
    return f"forecasting unavailable ({status.reason_code})"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("settings", check_settings),
    ("database", check_database),
    ("migrations", check_migrations),
    ("directories", check_directories),
    ("imports", check_imports),
    ("auth primitives", check_auth_primitives),
    ("torch cpu", check_torch_cpu),
    ("model status honest", check_model_status_honest),
]


def main() -> int:
    failures = 0
    for name, check in CHECKS:
        try:
            detail = check()
        except CheckFailed as exc:
            failures += 1
            print(f"FAIL  {name}: {exc}")
        except Exception as exc:  # report sanitized type only; details may contain secrets
            failures += 1
            print(f"FAIL  {name}: {type(exc).__name__}")
        else:
            print(f"PASS  {name}: {detail}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
