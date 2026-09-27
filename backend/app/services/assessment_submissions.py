"""Submission phase A (durable receipt), receipt and patient status (guide 02 §5/§11/§13, guide 05 §6–§9).

Phase A scores the raw payload against the session's frozen protocol and, in one transaction,
stores the assessment, its context, a PENDING analysis row and an audit event, and marks the
session SUBMITTED. Phase B (`services/analyses.process_assessment`) runs afterwards in its own
transaction, so an analysis failure can never undo a committed receipt.
"""

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AnalysisState,
    Assessment,
    AssessmentSession,
    AssessmentSource,
    ContextCheckin,
    PatientProfile,
    ProcessingStatus,
    Quality,
    SessionStatus,
)
from app.models.assessment import REPRESENTATIVE_PURPOSES
from app.schemas.assessments import (
    AnalysisSummary,
    AssessmentReceipt,
    AssessmentStatus,
    AssessmentSubmission,
    CurrentSession,
    PatientSchedule,
    QualitySummary,
)
from app.services import schedule
from app.services.analyses import create_analysis_record
from app.services.assessment_sessions import (
    MAX_SCHEDULED_STARTS_PER_SLOT,
    AssessmentConflict,
    get_owned_session,
    lock_patient,
    representatives,
    schedule_anchor,
    scheduled_starts,
)
from app.services.audit import audit
from app.services.messages import MESSAGES
from app.services.scoring import ScoringResult, score_submission


class SubmissionInvalid(Exception):
    """Structural/request error (422), never stored as an assessment."""


def payload_digest(session_id: uuid.UUID, payload: AssessmentSubmission) -> str:
    """SHA-256 of {session_id, validated canonical payload without submission_key} (guide 05 §9)."""
    body = payload.canonical()
    body.pop("submission_key")
    canonical = json.dumps(
        {"session_id": str(session_id), "payload": body}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def find_by_key(db: Session, patient_id: uuid.UUID, submission_key: uuid.UUID) -> Assessment | None:
    return db.scalar(
        select(Assessment).where(
            Assessment.patient_id == patient_id, Assessment.submission_key == submission_key
        )
    )


def submit_assessment(
    db: Session, patient_id: uuid.UUID, session_id: uuid.UUID, payload: AssessmentSubmission, now: datetime
) -> tuple[Assessment, bool]:
    """Phase A. Returns (assessment, created); caller commits. Same key + same body → replay."""
    lock_patient(db, patient_id)
    session = get_owned_session(db, patient_id, session_id)
    digest = payload_digest(session.id, payload)

    # Idempotent replay is checked before expiry: an accepted result stays retrievable.
    prior = find_by_key(db, patient_id, payload.submission_key)
    if prior is not None:
        if prior.payload_sha256 == digest:
            return prior, False
        raise AssessmentConflict(
            "IDEMPOTENCY_CONFLICT", "This submission key was already used with different data."
        )
    if session.assessment is not None:
        raise AssessmentConflict("SESSION_ALREADY_SUBMITTED", "This check-in was already saved.")
    if session.status == SessionStatus.ABANDONED:
        raise AssessmentConflict("SESSION_ABANDONED", "This check-in was discarded.")
    if session.status == SessionStatus.EXPIRED or session.expires_at <= now:
        if session.status == SessionStatus.STARTED:
            session.status, session.ended_at = SessionStatus.EXPIRED, session.expires_at
            db.commit()
        raise AssessmentConflict("SESSION_EXPIRED", "This check-in session has expired.")
    if payload.protocol_version != session.protocol_version:
        raise SubmissionInvalid("protocol_version does not match the session")

    scoring = score_submission(session.protocol_snapshot, payload, session.input_mode)
    assessment = record_submission(db, session, payload, digest, scoring, received_at=now)
    return assessment, True


def record_submission(
    db: Session,
    session: AssessmentSession,
    payload: AssessmentSubmission,
    digest: str,
    scoring: ScoringResult,
    received_at: datetime,
) -> Assessment:
    """Persist a scored submission + context + PENDING analysis + audit event; session → SUBMITTED.

    Shared by live submissions (received_at = server now) and controlled synthetic-history import
    (received_at = simulated receipt time). Caller holds the patient lock and has checked idempotency.
    """
    patient_id = session.patient_id
    # Final eligibility: rechecked under the patient lock (another attempt may have become the rep).
    slot_rep_exists = session.slot_index in representatives(db, patient_id)
    eligible = (
        session.schedule_purpose in REPRESENTATIVE_PURPOSES
        and scoring.quality == Quality.VALID
        and not slot_rep_exists
    )
    extra_reasons = (
        ["REPRESENTATIVE_ALREADY_EXISTS"]
        if slot_rep_exists and session.schedule_purpose in REPRESENTATIVE_PURPOSES
        else []
    )
    snapshot = session.protocol_snapshot
    quality_details = {
        **scoring.details,
        "quality_reasons": scoring.quality_reasons,
        "longitudinal_eligible": eligible,
        "schedule": {**snapshot["schedule"], "final_eligible": eligible, "extra_reasons": extra_reasons},
        "comparability": snapshot["comparability"],
        "comparability_flags": snapshot["comparability"]["flags"],
        "navigation_assistance_declared_at_start": snapshot["initial_request"]["navigation_assistance"],
        "device_changed_declared": snapshot["initial_request"]["device_changed"],
    }

    assessment = Assessment(
        session_id=session.id,
        patient_id=patient_id,
        submission_key=payload.submission_key,
        payload_sha256=digest,
        source=session.source,
        protocol_version=session.protocol_version,
        scoring_version=session.scoring_version,
        raw_responses=payload.canonical(),
        memory_score=scoring.memory.score,
        attention_score=scoring.attention.score,
        reaction_time_ms=scoring.reaction.score,
        quality=scoring.quality.value,
        quality_details=quality_details,
        longitudinal_eligible=eligible,
        schedule_purpose=session.schedule_purpose,
        slot_index=session.slot_index,
        target_at=session.target_at,
        observed_at=received_at,
        available_at=received_at,
        analysis_state=AnalysisState.PENDING.value,
        analysis_reasons=[],
        processing_status=ProcessingStatus.RECEIVED.value,
    )
    ctx = payload.context
    assessment.context = ContextCheckin(
        patient_id=patient_id,
        sleep_hours=ctx.sleep_hours,
        mood_score=ctx.mood_score,
        # Stored as YES/NO (guide 02 enum); the API boolean maps true→YES, false→NO, null→NULL.
        medication_change=None
        if ctx.medication_change is None
        else ("YES" if ctx.medication_change else "NO"),
        reported_by=ctx.reported_by.value,
        missing_fields=[{"field": f, "reason": r} for f, r in ctx.missing_fields.items()],
    )
    db.add(assessment)
    session.status, session.ended_at = SessionStatus.SUBMITTED, received_at
    db.flush()
    create_analysis_record(db, session, assessment)
    live = session.source == AssessmentSource.LIVE_DEMO
    audit(
        db,
        "ASSESSMENT_SUBMITTED",
        "assessment",
        assessment.id,
        patient_id=patient_id,
        # Imported synthetic history has no human actor.
        actor_user_id=db.get(PatientProfile, patient_id).user_id if live else None,  # type: ignore[union-attr]
        details={"session_id": str(session.id), "quality": scoring.quality.value, "source": session.source},
    )
    return assessment


# --- receipt ------------------------------------------------------------------------------------

_TASK_LABEL = {"memory": "MEMORY", "attention": "ATTENTION", "reaction": "REACTION"}
_LOW_ORDER = (
    "INTERRUPTION",
    "TRIAL_INTERRUPTED",
    "ANSWER_ASSISTANCE",
    "ASSISTANCE_UNCERTAIN",
    "INPUT_MODE_CHANGED",
    "RT_TIMEOUT_PRESENT",
    "INSUFFICIENT_USABLE_TRIALS",
    "EXPOSURE_TIMING_DEVIATION",
    "DISTRACTOR_TIMING_DEVIATION",
    "RECALL_TIMING_DEVIATION",
    "TIMING_DEVIATION",
    "TIMER_INTERRUPTION",
    "RESPONSE_OVERFLOW",
    "TELEMETRY_OVERFLOW",
)
_QUALITY_MESSAGE = {
    Quality.VALID: "Your check-in was saved.",
    Quality.INCOMPLETE: "Your check-in was saved, but not every activity was completed.",
    Quality.LOW: "Your check-in was saved, but something during it means it can't be compared reliably.",
}
_ANALYSIS_MESSAGE = {
    AnalysisState.PENDING: "Your check-in was saved. It is still being processed.",
    AnalysisState.COMPLETE: "Your check-in has been processed.",
    AnalysisState.BUILDING_BASELINE: "More weekly check-ins are needed before changes can be compared.",
    AnalysisState.INSUFFICIENT_DATA: "There is not enough reliable task data for a comparison.",
    AnalysisState.MODEL_UNAVAILABLE: "Automatic comparison isn't available right now.",
    AnalysisState.ANALYSIS_ERROR: "Processing could not finish yet and can be retried.",
}


def quality_reason_codes(assessment: Assessment) -> list[str]:
    tasks = assessment.quality_details["tasks"]
    codes: list[str] = []
    for name in ("memory", "attention", "reaction"):  # fixed order (JSONB does not keep key order)
        t = tasks[name]
        if t["completion"] in ("SKIPPED", "STOPPED"):
            codes.append(f"{_TASK_LABEL[name]}_{t['completion']}")
        elif t["status"] == Quality.INCOMPLETE:
            codes.append(f"{_TASK_LABEL[name]}_NOT_ALL_TRIALS_PRESENTED")
    flags = {f for t in tasks.values() for f in t["low_flags"]}
    return codes + [f for f in _LOW_ORDER if f in flags]


def _message(base: str, codes: list[str]) -> str:
    specific = next((MESSAGES[c] for c in codes if c in MESSAGES), None)
    return f"{base} {specific}" if specific and specific not in base else base


def build_receipt(assessment: Assessment, replayed: bool) -> AssessmentReceipt:
    quality = Quality(assessment.quality)
    q_codes = quality_reason_codes(assessment)
    state = AnalysisState(assessment.analysis_state)
    # Patient-visible reason codes only; technical model/artifact codes stay server-side.
    a_codes = [c for c in assessment.analysis_reasons if c in MESSAGES and c != "ANALYSIS_ERROR"]
    return AssessmentReceipt(
        assessment_id=assessment.id,
        session_id=assessment.session_id,
        received_at=assessment.available_at,
        quality=QualitySummary(
            status=quality.value, reason_codes=q_codes, message=_message(_QUALITY_MESSAGE[quality], q_codes)
        ),
        analysis=AnalysisSummary(
            availability=state.value,
            reason_codes=a_codes,
            message=_ANALYSIS_MESSAGE[state]
            if state in (AnalysisState.COMPLETE, AnalysisState.ANALYSIS_ERROR)
            else _message(_ANALYSIS_MESSAGE[state], a_codes),
        ),
        replayed=replayed,
    )


def get_receipt(db: Session, patient_id: uuid.UUID, assessment_id: uuid.UUID) -> Assessment | None:
    return db.scalar(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.patient_id == patient_id)
    )


# --- status -------------------------------------------------------------------------------------


def assessment_status(db: Session, patient_id: uuid.UUID, now: datetime) -> AssessmentStatus:
    """Read-only: never creates an anchor, expires rows, or starts analysis."""
    last = db.scalar(
        select(Assessment)
        .where(Assessment.patient_id == patient_id)
        .order_by(Assessment.available_at.desc(), Assessment.id.desc())
        .limit(1)
    )
    active = db.scalar(
        select(AssessmentSession).where(
            AssessmentSession.patient_id == patient_id,
            AssessmentSession.status == SessionStatus.STARTED,
            AssessmentSession.expires_at > now,
        )
    )
    current = (
        CurrentSession(
            session_id=active.id,
            status="STARTED",
            started_at=active.started_at,
            expires_at=active.expires_at,
            target_at=active.target_at,
        )
        if active
        else None
    )

    anchor = schedule_anchor(db, patient_id)
    if anchor is None:
        sched = PatientSchedule(
            anchor_at=None,
            next_target_at=None,
            window_opens_at=None,
            window_closes_at=None,
            scheduled_start_allowed=current is None,
            reason_codes=["FIRST_CHECKIN"],
        )
    else:
        slot, target = schedule.nearest_slot(anchor, now)
        open_now = schedule.in_window(target, now)
        reps = representatives(db, patient_id)
        blocked = slot in reps or scheduled_starts(db, patient_id, slot) >= MAX_SCHEDULED_STARTS_PER_SLOT
        if open_now and not blocked:
            next_slot, codes = slot, ["IN_WINDOW"]
        else:
            next_slot = slot if (not open_now and now < target) else slot + 1
            if open_now:
                codes = ["SLOT_COMPLETED" if slot in reps else "ATTEMPT_LIMIT_REACHED"]
            else:
                codes = ["OUTSIDE_SCHEDULE_WINDOW"]
        next_target = schedule.target_for(anchor, next_slot)
        sched = PatientSchedule(
            anchor_at=anchor,
            next_target_at=next_target,
            window_opens_at=next_target - schedule.WINDOW,
            window_closes_at=next_target + schedule.WINDOW,
            scheduled_start_allowed=open_now and not blocked and current is None,
            reason_codes=codes,
        )
    if current is not None:
        sched.reason_codes = ["ACTIVE_SESSION_EXISTS", *sched.reason_codes]
    return AssessmentStatus(
        patient_id=patient_id,
        server_time=now,
        current_session=current,
        last_receipt=build_receipt(last, replayed=False) if last else None,
        schedule=sched,
    )
