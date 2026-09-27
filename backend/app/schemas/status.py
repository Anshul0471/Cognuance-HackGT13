from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


class ModelStatus(BaseModel):
    """Sanitized model/policy readiness. No artifact paths, training identities or patient data.

    `model_loaded` alone is not `forecast_ready`: a verified bundle, its active calibrated policy and
    a compatible MODEL_MODE are all required.
    """

    model_kind: Literal["LAST_VALUE", "LINEAR_TREND", "GRU"] | None
    model_version: str | None
    policy_version: str | None
    model_loaded: bool
    policy_ready: bool
    forecast_ready: bool
    reason_code: str | None = Field(
        description="Sanitized reason when forecasting is not ready; null when ready"
    )
