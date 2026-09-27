"""Original setup-phase model boundaries (FEATURE_ORDER is still the allow-listed source-field order).

The implementation lives in `app/ml/models/` (guide 04) and `app/ml/serving.py`; `Forecast` /
`Forecaster` below are the setup-phase sketch and are not used by the serving path.

Conventions the implementations must follow (see docs/setup.md section 11):
- Inputs are the prior `sequence_length` observations (settings.SEQUENCE_LENGTH, default 6) in
  FEATURE_ORDER, with timestamps and an explicit missingness mask. Missing values are never
  imputed as zero performance.
- Outputs are separate predictions for each of FORECAST_TARGETS.
- Lower memory/attention and higher reaction time are worse. Unusual improvement is never a
  decline alert.
- A forecast is frozen before its target assessment arrives; context reported with that
  assessment (sleep/mood/medication) accompanies the alert but is not fed back into the
  already-issued forecast.
- Scalers are fit on training data only; synthetic patients are split across
  train/validation/test with chronological order preserved inside each sequence.
- Artifacts persist model version, preprocessing version, feature order, training seed, and
  calibration metadata. A missing or unfitted artifact raises ModelNotReadyError instead of
  returning fabricated predictions.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

FEATURE_ORDER: tuple[str, ...] = (
    "memory_score",
    "attention_score",
    "reaction_time_ms",
    "sleep_hours",
    "mood_score",
    "medication_change",
)

FORECAST_TARGETS: tuple[str, ...] = ("memory_score", "attention_score", "reaction_time_ms")

# Direction in which a target gets *worse*.
WORSE_DIRECTION: dict[str, Literal["lower", "higher"]] = {
    "memory_score": "lower",
    "attention_score": "lower",
    "reaction_time_ms": "higher",
}


class ModelNotReadyError(RuntimeError):
    """Raised when no fitted model artifact is available for inference."""


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    # None marks a missing value; never substitute 0.
    values: dict[str, float | None]


@dataclass(frozen=True)
class Forecast:
    model_version: str
    issued_at: datetime
    predictions: dict[str, float]
    # Calibrated spread per target, used by the anomaly rules.
    uncertainty: dict[str, float]


@dataclass(frozen=True)
class ArtifactMetadata:
    model_version: str
    preprocessing_version: str
    feature_order: tuple[str, ...]
    sequence_length: int
    training_seed: int
    calibration: dict[str, float]


class Forecaster(Protocol):
    metadata: ArtifactMetadata

    def predict(self, history: list[Observation]) -> Forecast:
        """Forecast the next assessment. Raises ModelNotReadyError if not fitted."""
        ...
