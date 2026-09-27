"""Compare a submitted assessment with its session's stored forecast (guide 04 §10, §11, §14).

Reads only persisted values: the frozen forecast, the observed scores and the exact policy the
forecast was issued under. The active model is never re-run. One assessment → at most one
COMPLETE analysis and at most one alert; retries are idempotent. The data receipt is committed
before analysis, so a processing failure leaves a retryable ANALYSIS_ERROR, never a lost result.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.models.anomaly import PolicyError, PolicyRules, evaluate
from app.ml.models.explanations import EXPLANATION_VERSION, build_explanation
from app.models import (
    Alert,
    AlertAction,
    AlertEvent,
    AlertStatus,
    Analysis,
    AnalysisState,
    AnomalyPolicy,
    Assessment,
    AssessmentSession,
    Forecast,
    ForecastState,
    ModelVersion,
    ProcessingStatus,
    Quality,
)
from app.services.assessment_sessions import lock_patient

log = logging.getLogger(__name__)

RETRYABLE = (AnalysisState.PENDING, AnalysisState.ANALYSIS_ERROR)
MAX_PRIOR_RECOVERY_DEPTH = 6


class AnalysisFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Terminal availability by the frozen forecast state (READY → the anomaly comparison runs).
FORECAST_TO_ANALYSIS = {
    ForecastState.BUILDING_BASELINE: AnalysisState.BUILDING_BASELINE,
    ForecastState.INSUFFICIENT_DATA: AnalysisState.INSUFFICIENT_DATA,
    ForecastState.MODEL_UNAVAILABLE: AnalysisState.MODEL_UNAVAILABLE,
}
QUALITY_TARGET_REASON = {Quality.INCOMPLETE: "INCOMPLETE_TARGET", Quality.LOW: "LOW_QUALITY_TARGET"}
_PROCESSING = {
    AnalysisState.PENDING: ProcessingStatus.RECEIVED,
    AnalysisState.ANALYSIS_ERROR: ProcessingStatus.FAILED,
}


def create_analysis_record(db: Session, session: AssessmentSession, assessment: Assessment) -> Analysis:
    """Phase A: every submitted assessment gets one PENDING analysis row, linked to the session's
    preissued forecast when one exists (no forecast → the analysis can only end unavailable)."""
    forecast = db.scalar(select(Forecast).where(Forecast.session_id == session.id))
    row = Analysis(
        assessment_id=assessment.id,
        session_id=session.id,
        patient_id=session.patient_id,
        forecast_id=forecast.id if forecast else None,
        model_version_id=forecast.model_version_id if forecast else None,
        policy_id=forecast.policy_id if forecast else None,
        slot_index=session.slot_index,
        comparability_key=forecast.comparability_key if forecast else None,
        availability=AnalysisState.PENDING.value,
        reasons=[],
        attempts=0,
    )
    db.add(row)
    db.flush()
    return row


def terminal_analysis(
    assessment: Assessment, session: AssessmentSession
) -> tuple[AnalysisState, list[str]] | None:
    """Availability priority (guide 02): quality, then schedule/comparability, history, model.

    Returns None when a preissued forecast allows the anomaly comparison to run.
    """
    quality = Quality(assessment.quality)
    extra = assessment.quality_details["schedule"].get("extra_reasons", [])
    forecast_reasons = list(session.forecast_reasons)
    if quality != Quality.VALID:
        return AnalysisState.INSUFFICIENT_DATA, list(
            dict.fromkeys([QUALITY_TARGET_REASON[quality], *forecast_reasons])
        )
    if extra:
        return AnalysisState.INSUFFICIENT_DATA, list(dict.fromkeys([*extra, *forecast_reasons]))
    state = ForecastState(session.forecast_state)
    if state == ForecastState.READY:
        return None
    return FORECAST_TO_ANALYSIS[state], forecast_reasons


def _set_state(analysis: Analysis, assessment: Assessment, state: AnalysisState, reasons: list[str]) -> None:
    analysis.availability, analysis.reasons = state.value, reasons
    assessment.analysis_state, assessment.analysis_reasons = state.value, reasons
    assessment.processing_status = _PROCESSING.get(state, ProcessingStatus.ANALYZED).value


def _prior_count(db: Session, analysis: Analysis, now: datetime, depth: int) -> int | None:
    """Qualifying streak of the immediately previous weekly representative; None = must wait."""
    prev_rep = db.scalar(
        select(Assessment).where(
            Assessment.patient_id == analysis.patient_id,
            Assessment.slot_index == analysis.slot_index - 1,
            Assessment.longitudinal_eligible.is_(True),
        )
    )
    if prev_rep is None:
        return 0  # missing slot breaks the streak
    prev = db.scalar(select(Analysis).where(Analysis.assessment_id == prev_rep.id))
    if prev is None:
        return 0  # legacy row without an analysis: not a detected deviation
    if prev.availability in RETRYABLE:
        if depth >= MAX_PRIOR_RECOVERY_DEPTH:
            return None
        _process(db, prev, now, depth + 1)  # bounded chronological recovery of the prior
        if prev.availability in RETRYABLE:
            return None
    if prev.availability != AnalysisState.COMPLETE or not prev.moderate_signal:
        return 0
    if prev.policy_id != analysis.policy_id or prev.comparability_key != analysis.comparability_key:
        return 0  # model/policy/segment change breaks the streak
    return int(prev.persistent_count or 0)


def _compute(db: Session, analysis: Analysis, assessment: Assessment, prior: int, now: datetime) -> None:
    forecast = db.get(Forecast, analysis.forecast_id)
    policy = db.get(AnomalyPolicy, analysis.policy_id)
    model = db.get(ModelVersion, analysis.model_version_id)
    if forecast is None or policy is None or model is None:
        raise AnalysisFailure("POLICY_OR_FORECAST_MISSING")
    try:
        rules = PolicyRules.from_configuration(policy.configuration)
    except PolicyError:
        raise AnalysisFailure("POLICY_INVALID") from None
    values = (assessment.memory_score, assessment.attention_score, assessment.reaction_time_ms)
    if any(v is None for v in values):
        raise AnalysisFailure("STORED_VALUES_INVALID")
    predicted = (
        float(forecast.predicted_memory_score),
        float(forecast.predicted_attention_score),
        float(forecast.predicted_reaction_time_ms),
    )
    try:
        ev = evaluate(predicted, tuple(float(v) for v in values), rules, prior)  # type: ignore[arg-type]
    except PolicyError:
        raise AnalysisFailure("CALCULATION_FAILED") from None

    ctx = assessment.context
    current = {
        "sleep_hours": float(ctx.sleep_hours) if ctx and ctx.sleep_hours is not None else None,
        "mood_score": ctx.mood_score if ctx else None,
        "medication_change": ctx.medication_change if ctx else None,
        "missing_fields": ctx.missing_fields if ctx else [],
    }
    explanation = build_explanation(
        evaluation=ev,
        rules=rules,
        model_kind=model.kind,
        model_version=model.version,
        policy_version=policy.version,
        protocol_version=assessment.protocol_version,
        scoring_version=assessment.scoring_version,
        quality=assessment.quality,
        comparability_key=analysis.comparability_key,
        history=forecast.feature_snapshot["history"],
        current_context=current,
    )
    explanation["facts"]["forecast"] = {
        "forecast_id": str(forecast.id),
        "issued_at": forecast.issued_at.isoformat(),
        "history_cutoff_at": forecast.history_cutoff_at.isoformat(),
        "input_assessment_ids": forecast.input_assessment_ids,
        "feature_sha256": forecast.feature_sha256,
        "bounds_applied": forecast.bounds_applied,
    }
    analysis.domain_deviations = ev.domain_json()
    analysis.max_deviation = ev.max_deviation
    analysis.aggregate_deviation = ev.aggregate_deviation
    analysis.moderate_signal = ev.moderate_signal
    analysis.high_signal = ev.high_signal
    analysis.persistent_count = ev.persistent_count
    analysis.deviation_level = ev.level
    analysis.explanation = explanation
    analysis.explanation_version = EXPLANATION_VERSION
    analysis.computed_at = now
    analysis.last_error_code = None
    _set_state(analysis, assessment, AnalysisState.COMPLETE, [])
    db.flush()
    if ev.level != "NORMAL":
        existing = db.scalar(select(Alert).where(Alert.analysis_id == analysis.id))
        if existing is None:
            alert = Alert(
                analysis_id=analysis.id,
                assessment_id=assessment.id,
                patient_id=analysis.patient_id,
                deviation_level=ev.level,
                status=AlertStatus.OPEN,
            )
            db.add(alert)
            db.flush()
            db.add(
                AlertEvent(
                    alert_id=alert.id,
                    actor_user_id=None,
                    action=AlertAction.CREATED,
                    from_status=None,
                    to_status=AlertStatus.OPEN,
                    created_at=now,
                )
            )
            db.flush()


def _process(db: Session, analysis: Analysis, now: datetime, depth: int = 0) -> None:
    if analysis.availability not in RETRYABLE:
        return  # COMPLETE / terminal: never recomputed or rewritten
    assessment = db.get(Assessment, analysis.assessment_id)
    session = db.get(AssessmentSession, analysis.session_id)
    assert assessment is not None and session is not None
    terminal = terminal_analysis(assessment, session)
    if terminal is not None:  # terminal unavailability first; no forecast is ever created here
        _set_state(analysis, assessment, *terminal)
        analysis.computed_at = now
        db.flush()
        return
    if analysis.forecast_id is None:  # READY without a stored forecast cannot be compared honestly
        _set_state(
            analysis, assessment, AnalysisState.MODEL_UNAVAILABLE, ["MODEL_UNAVAILABLE", "FORECAST_MISSING"]
        )
        db.flush()
        return
    prior = _prior_count(db, analysis, now, depth)
    if prior is None:
        _set_state(analysis, assessment, AnalysisState.PENDING, ["WAITING_FOR_PREVIOUS_ANALYSIS"])
        db.flush()
        return
    analysis.attempts = (analysis.attempts or 0) + 1
    db.flush()
    try:
        with db.begin_nested():
            _compute(db, analysis, assessment, prior, now)
    except AnalysisFailure as exc:
        code = exc.code
    except Exception:  # calculation or storage failure → retryable, never NORMAL
        log.exception("analysis %s failed", analysis.id)
        code = "PROCESSING_FAILED"
    else:
        return
    db.refresh(analysis)
    db.refresh(assessment)
    analysis.last_error_code = code
    _set_state(analysis, assessment, AnalysisState.ANALYSIS_ERROR, ["ANALYSIS_ERROR"])
    db.flush()


def process_assessment(db: Session, assessment_id: uuid.UUID, now: datetime) -> Analysis | None:
    """Phase B for one assessment (caller commits)."""
    analysis = db.scalar(select(Analysis).where(Analysis.assessment_id == assessment_id))
    if analysis is None:
        return None
    lock_patient(db, analysis.patient_id)
    db.refresh(analysis)
    _process(db, analysis, now)
    return analysis


def analyze_after_commit(db: Session, assessment_id: uuid.UUID, now: datetime) -> None:
    """Run analysis in its own transaction after the receipt is committed."""
    try:
        process_assessment(db, assessment_id, now)
        db.commit()
    except Exception:
        log.exception("analysis transaction failed for assessment %s", assessment_id)
        db.rollback()
        # Expose the failure as a retryable error rather than an unexplained PENDING.
        try:
            analysis = db.scalar(select(Analysis).where(Analysis.assessment_id == assessment_id))
            assessment = db.get(Assessment, assessment_id)
            if (
                analysis is not None
                and assessment is not None
                and analysis.availability == AnalysisState.PENDING
            ):
                analysis.last_error_code = "PROCESSING_FAILED"
                _set_state(analysis, assessment, AnalysisState.ANALYSIS_ERROR, ["ANALYSIS_ERROR"])
                db.commit()
        except Exception:
            db.rollback()


def recover_analyses(
    db: Session, now: datetime, patient_id: uuid.UUID | None = None, limit: int = 200
) -> list[tuple[str, str, str]]:
    """Retry PENDING / ANALYSIS_ERROR analyses in patient/slot order: one bounded attempt per row.

    Returns (assessment_id, availability, sanitized reason). Caller commits. Never creates a forecast,
    never rewrites a finalized analysis, never duplicates alerts.
    """
    query = select(Analysis).where(Analysis.availability.in_([s.value for s in RETRYABLE]))
    if patient_id is not None:
        query = query.where(Analysis.patient_id == patient_id)
    rows = db.scalars(
        query.order_by(Analysis.patient_id, Analysis.slot_index, Analysis.created_at).limit(limit)
    ).all()
    results = []
    for row in rows:
        lock_patient(db, row.patient_id)
        db.refresh(row)
        _process(db, row, now)
        results.append(
            (str(row.assessment_id), row.availability, row.last_error_code or ",".join(row.reasons))
        )
    return results


def needing_recovery(db: Session) -> int:
    return len(
        db.scalars(select(Analysis.id).where(Analysis.availability.in_([s.value for s in RETRYABLE]))).all()
    )
