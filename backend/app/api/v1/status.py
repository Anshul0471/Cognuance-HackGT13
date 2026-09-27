from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError, error_responses
from app.db.session import get_db, get_engine
from app.ml.status import get_model_status
from app.schemas.status import HealthResponse, ModelStatus, ReadyResponse
from app.services.readiness import ReadinessResult, run_readiness_checks

router = APIRouter(tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
ReadinessChecker = Callable[[], ReadinessResult]


def get_readiness_checker() -> ReadinessChecker:
    return lambda: run_readiness_checks(get_engine())


@router.get("/health", response_model=HealthResponse, operation_id="getHealth")
async def health() -> HealthResponse:
    """Process liveness only: no database or model call."""
    return HealthResponse()


@router.get(
    "/ready", response_model=ReadyResponse, operation_id="getReadiness", responses=error_responses(503)
)
def ready(checker: Annotated[ReadinessChecker, Depends(get_readiness_checker)]) -> ReadyResponse:
    """Bounded database connectivity check + migration head verification (never applies migrations)."""
    result = checker()
    if not result.database_ok:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not reachable.")
    if not result.migrations_ok:
        raise ApiError(503, "MIGRATIONS_NOT_CURRENT", "The database schema is not at the expected version.")
    return ReadyResponse()


@router.get(
    "/model/status", response_model=ModelStatus, operation_id="getModelStatus", responses=error_responses(503)
)
def model_status(settings: SettingsDep, db: Annotated[Session, Depends(get_db)]) -> ModelStatus:
    """Model unavailability is a valid 200 document; 503 only when the status cannot be served."""
    try:
        return get_model_status(settings, db)
    except SQLAlchemyError:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "Model status is temporarily unavailable.") from None
