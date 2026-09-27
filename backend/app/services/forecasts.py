"""Issue and persist a forecast at session start, before any task content is returned (guide 04 §14).

Inputs are exactly the six prior-slot representatives already validated by
`schedule.evaluate_history` (same eligibility rules as guide 02/03), all available at the cutoff.
The feature transform is the guide-03 `preprocessing.feature_row`, identical to offline tensors.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.models import ENGINE_VERSION
from app.ml.models.postprocessing import POSTPROCESSING_VERSION, PredictionError, decimal3
from app.ml.serving import ForecastUnavailable, load_model, resolve_active_pair
from app.models import Assessment, AssessmentSession, Forecast, ForecastState


def history_ready(session: AssessmentSession) -> bool:
    """History/schedule/comparability all passed; only the model step remains."""
    return session.forecast_state == ForecastState.MODEL_UNAVAILABLE and session.forecast_reasons == [
        "MODEL_NOT_CONFIGURED"
    ]


def _float(v: Any) -> float | None:
    return None if v is None else float(v)


def history_row(a: Assessment) -> dict[str, Any]:
    """Allow-listed history values of one representative (+ provenance fields not fed to the model)."""
    ctx = a.context
    return {
        "assessment_id": str(a.id),
        "slot_index": a.slot_index,
        "observed_at": a.observed_at.isoformat(),
        "available_at": a.available_at.isoformat(),
        "memory_score": _float(a.memory_score),
        "attention_score": _float(a.attention_score),
        "reaction_time_ms": _float(a.reaction_time_ms),
        "sleep_hours": _float(ctx.sleep_hours) if ctx else None,
        "mood_score": ctx.mood_score if ctx else None,
        "medication_change": ctx.medication_change if ctx else None,
    }


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def issue_forecast(
    db: Session, session: AssessmentSession, reps: dict[int, Assessment], now: datetime
) -> Forecast | None:
    """Persist a READY forecast for `session`, or record a sanitized MODEL_UNAVAILABLE reason."""
    from app.ml.models.forecasting import predict_history

    if not history_ready(session):
        return None
    n = get_settings().SEQUENCE_LENGTH
    history = [reps[k] for k in range(session.slot_index - n, session.slot_index)]
    if any(a.available_at > session.history_cutoff_at for a in history):
        session.forecast_state, session.forecast_reasons = (
            ForecastState.INSUFFICIENT_DATA,
            ["LATE_AVAILABILITY"],
        )
        return None
    try:
        model_row, policy_row = resolve_active_pair(db)
        loaded = load_model(model_row)
        rows = [history_row(a) for a in history]
        prediction, x = predict_history(loaded.kind, rows, loaded.params, loaded.module)
    except ForecastUnavailable as exc:
        session.forecast_state = ForecastState.MODEL_UNAVAILABLE
        session.forecast_reasons = (
            ["MODEL_NOT_CONFIGURED"]
            if exc.code == "MODEL_NOT_CONFIGURED"
            else ["MODEL_UNAVAILABLE", exc.code]
        )
        return None
    except (PredictionError, ValueError):
        session.forecast_state, session.forecast_reasons = (
            ForecastState.MODEL_UNAVAILABLE,
            ["MODEL_UNAVAILABLE", "FORECAST_FAILED"],
        )
        return None

    snapshot = {
        "history": rows,
        "x_channels": loaded.params["x_channels"],
        "x": [[float(v) for v in r] for r in x.tolist()],
        "preprocessing_version": loaded.params["preprocessing_version"],
        "model_kind": loaded.kind,
        "uses_context": loaded.kind == "GRU",
    }
    forecast = Forecast(
        session_id=session.id,
        patient_id=session.patient_id,
        model_version_id=model_row.id,
        policy_id=policy_row.id,
        slot_index=session.slot_index,
        target_at=session.target_at,
        history_cutoff_at=session.history_cutoff_at,
        issued_at=now,
        predicted_memory_score=decimal3(prediction.memory),
        predicted_attention_score=decimal3(prediction.attention),
        predicted_reaction_time_ms=decimal3(prediction.reaction_time_ms),
        bounds_applied=dict(prediction.bounds),
        input_assessment_ids=[r["assessment_id"] for r in rows],
        feature_snapshot=snapshot,
        feature_sha256=canonical_sha256(snapshot),
        comparability_key=session.protocol_snapshot["comparability"]["key"],
        engine_version=ENGINE_VERSION,
        preprocessing_version=loaded.params["preprocessing_version"],
        postprocessing_version=POSTPROCESSING_VERSION,
    )
    db.add(forecast)
    session.forecast_state, session.forecast_reasons = ForecastState.READY, []
    db.flush()
    return forecast
