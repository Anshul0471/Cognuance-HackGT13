"""Infrastructure readiness checks: database connectivity and migration revision.

Failures are logged server-side and returned as sanitized messages; raw SQL errors and
connection URLs never reach API responses.
"""

import logging
from dataclasses import dataclass

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import BACKEND_DIR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class MigrationCheckResult(CheckResult):
    current: str | None = None
    head: str | None = None


@dataclass(frozen=True)
class ReadinessResult:
    """Internal only: the HTTP response exposes status/error codes, not these details."""

    database: CheckResult
    migrations: MigrationCheckResult

    @property
    def database_ok(self) -> bool:
        return self.database.ok

    @property
    def migrations_ok(self) -> bool:
        return self.migrations.ok


ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
STATEMENT_TIMEOUT_MS = 3000


def get_head_revision() -> str | None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return script.get_current_head()


def check_database(engine: Engine) -> CheckResult:
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
            conn.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as exc:
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        return CheckResult(ok=False, detail="Database unreachable or authentication failed")
    return CheckResult(ok=True, detail="Connected")


def check_migrations(engine: Engine) -> MigrationCheckResult:
    try:
        head = get_head_revision()
    except Exception:
        logger.exception("Could not read Alembic head revision")
        return MigrationCheckResult(ok=False, detail="Migration scripts could not be read")

    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    except SQLAlchemyError as exc:
        logger.warning("Migration revision check failed: %s", type(exc).__name__)
        return MigrationCheckResult(ok=False, detail="Could not read current revision", head=head)

    if head is None:
        return MigrationCheckResult(ok=False, detail="No migration revisions exist", current=current)
    if current != head:
        return MigrationCheckResult(
            ok=False,
            detail=f"Database at {current or 'no revision'}; expected {head}. Run `alembic upgrade head`.",
            current=current,
            head=head,
        )
    return MigrationCheckResult(ok=True, detail=f"At head ({head})", current=current, head=head)


def run_readiness_checks(engine: Engine) -> ReadinessResult:
    database = check_database(engine)
    if database.ok:
        migrations = check_migrations(engine)
    else:
        migrations = MigrationCheckResult(ok=False, detail="Skipped: database unavailable")
    return ReadinessResult(database=database, migrations=migrations)
