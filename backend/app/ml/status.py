"""Model availability for `/model/status` (guide 04 §16, guide 05 §5)."""

from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.schemas.status import ModelStatus


def torch_version() -> str | None:
    if find_spec("torch") is None:
        return None
    try:
        return version("torch")
    except PackageNotFoundError:
        return None


def get_model_status(settings: Settings, db: Session | None) -> ModelStatus:
    """Raises SQLAlchemyError if the database cannot be queried (the route maps that to 503)."""
    if settings.MODEL_MODE == "unconfigured" or db is None:
        return ModelStatus(
            model_kind=None,
            model_version=None,
            policy_version=None,
            model_loaded=False,
            policy_ready=False,
            forecast_ready=False,
            reason_code="MODEL_NOT_CONFIGURED",
        )
    from app.ml.serving import readiness

    state = readiness(db)
    return ModelStatus(
        model_kind=state["active_model_kind"],
        model_version=state["active_model_version"],
        policy_version=state["active_policy_version"],
        model_loaded=state["model_loaded"],
        policy_ready=state["policy_ready"],
        forecast_ready=state["forecast_ready"],
        reason_code=None if state["forecast_ready"] else state["failure_code"],
    )
