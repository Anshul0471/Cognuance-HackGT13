"""Assessment session lifecycle: start (frozen protocol + schedule + forecast state), abandon,
expiry, and the patient's status view (guide 02 §4, §5, §13, §14).

All state-changing operations lock the patient's row first so concurrent starts/submissions
serialize (anchor creation, slot attempt limits, representative selection).
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Assessment,
    AssessmentSession,
    AssessmentSource,
    ForecastState,
    PatientProfile,
    SchedulePurpose,
    SessionStatus,
)
from app.models.assessment import REPRESENTATIVE_PURPOSES
from app.schemas.assessments import StartSessionRequest
from app.services import schedule
from app.services.audit import audit
from app.services.forecasts import issue_forecast
from app.services.protocol import (
    PROTOCOL_VERSION,
    SCORING_VERSION,
    SESSION_EXPIRY_MINUTES,
    build_task_protocol,
    word_set_for,
)

MAX_SCHEDULED_STARTS_PER_SLOT = 2


class AssessmentConflict(Exception):
    """A 409 with a machine-readable code and safe extra fields."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


class SessionNotFound(Exception):
    pass


def lock_patient(db: Session, patient_id: uuid.UUID) -> PatientProfile:
    return db.execute(
        select(PatientProfile).where(PatientProfile.id == patient_id).with_for_update()
    ).scalar_one()


def expire_stale_sessions(db: Session, patient_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(AssessmentSession)
        .where(
            AssessmentSession.patient_id == patient_id,
            AssessmentSession.status == SessionStatus.STARTED,
            AssessmentSession.expires_at <= now,
        )
        .values(status=SessionStatus.EXPIRED, ended_at=AssessmentSession.expires_at)
    )


def effective_status(session: AssessmentSession, now: datetime) -> str:
    if session.status == SessionStatus.STARTED and session.expires_at <= now:
        return SessionStatus.EXPIRED
    return session.status


def get_owned_session(db: Session, patient_id: uuid.UUID, session_id: uuid.UUID) -> AssessmentSession:
    session = db.scalar(
        select(AssessmentSession).where(
            AssessmentSession.id == session_id, AssessmentSession.patient_id == patient_id
        )
    )
    if session is None:
        raise SessionNotFound
    return session


def schedule_anchor(db: Session, patient_id: uuid.UUID) -> datetime | None:
    """Every session copies the anchor established by the patient's first scheduling session."""
    first = db.scalar(
        select(AssessmentSession)
        .where(AssessmentSession.patient_id == patient_id)
        .order_by(AssessmentSession.started_at, AssessmentSession.id)
        .limit(1)
    )
    if first is None:
        return None
    return datetime.fromisoformat(first.protocol_snapshot["schedule"]["anchor_at"])


def representatives(db: Session, patient_id: uuid.UUID) -> dict[int, Assessment]:
    rows = db.scalars(
        select(Assessment)
        .where(Assessment.patient_id == patient_id, Assessment.longitudinal_eligible.is_(True))
        .order_by(Assessment.available_at, Assessment.id)
    )
    reps: dict[int, Assessment] = {}
    for row in rows:
        reps.setdefault(row.slot_index, row)
    return reps


def _as_rep(a: Assessment) -> schedule.Representative:
    return schedule.Representative(
        slot_index=a.slot_index,
        protocol_version=a.protocol_version,
        scoring_version=a.scoring_version,
        comparability_key=a.quality_details["comparability"]["key"],
    )


def scheduled_starts(db: Session, patient_id: uuid.UUID, slot: int) -> int:
    return len(
        db.scalars(
            select(AssessmentSession.id).where(
                AssessmentSession.patient_id == patient_id,
                AssessmentSession.slot_index == slot,
                AssessmentSession.schedule_purpose.in_([p.value for p in REPRESENTATIVE_PURPOSES]),
            )
        ).all()
    )


def _normalized_request(req: StartSessionRequest) -> dict[str, Any]:
    return req.model_dump(mode="json")


def decide_purpose(
    in_window: bool, slot_has_rep: bool, starts: int, allow_unscheduled: bool, next_target: datetime
) -> tuple[SchedulePurpose, str]:
    if in_window and not slot_has_rep and starts == 0:
        return SchedulePurpose.SCHEDULED, "IN_WINDOW"
    if in_window and not slot_has_rep and starts < MAX_SCHEDULED_STARTS_PER_SLOT:
        return SchedulePurpose.RETAKE_AFTER_UNRELIABLE, "RETAKE_AFTER_UNRELIABLE"
    if in_window:
        code = "SLOT_COMPLETED" if slot_has_rep else "ATTEMPT_LIMIT_REACHED"
        if allow_unscheduled:
            return SchedulePurpose.EXTRA_ATTEMPT, code
        raise AssessmentConflict(
            code,
            "This week's check-in is already done." if slot_has_rep else "This week's attempts are used.",
            next_target_at=next_target.isoformat(),
        )
    if allow_unscheduled:
        return SchedulePurpose.OFF_SCHEDULE, "OUTSIDE_SCHEDULE_WINDOW"
    raise AssessmentConflict(
        "OUTSIDE_SCHEDULE_WINDOW",
        "The weekly check-in window is not open.",
        next_target_at=next_target.isoformat(),
    )


def start_session(
    db: Session,
    patient_id: uuid.UUID,
    req: StartSessionRequest,
    now: datetime,
    rng: random.Random | None = None,
) -> tuple[AssessmentSession, bool]:
    """Create a frozen session, or return the existing one for an identical start_key (created=False)."""
    lock_patient(db, patient_id)
    expire_stale_sessions(db, patient_id, now)

    existing = db.scalar(
        select(AssessmentSession).where(
            AssessmentSession.patient_id == patient_id, AssessmentSession.start_key == req.start_key
        )
    )
    if existing is not None:
        if existing.protocol_snapshot["initial_request"] != _normalized_request(req):
            raise AssessmentConflict(
                "IDEMPOTENCY_CONFLICT", "This start key was used with different choices."
            )
        return existing, False

    active = db.scalar(
        select(AssessmentSession).where(
            AssessmentSession.patient_id == patient_id, AssessmentSession.status == SessionStatus.STARTED
        )
    )
    if active is not None:
        raise AssessmentConflict(
            "ACTIVE_SESSION_EXISTS",
            "A check-in was started and not finished.",
            session_id=str(active.id),
            expires_at=active.expires_at.isoformat(),
        )

    anchor = schedule_anchor(db, patient_id) or now
    slot, target = schedule.nearest_slot(anchor, now)
    window_open = schedule.in_window(target, now)
    reps = representatives(db, patient_id)
    starts = scheduled_starts(db, patient_id, slot)
    next_target = target if now < target else schedule.target_for(anchor, slot + 1)
    purpose, schedule_reason = decide_purpose(
        window_open, slot in reps, starts, req.allow_unscheduled, next_target
    )

    previous_sessions = len(
        db.scalars(select(AssessmentSession.id).where(AssessmentSession.patient_id == patient_id)).all()
    )
    session = build_frozen_session(
        patient_id=patient_id,
        req=req,
        started_at=now,
        anchor=anchor,
        slot=slot,
        target=target,
        purpose=purpose,
        schedule_reason=schedule_reason,
        starts=starts,
        reps=reps,
        task_protocol=build_task_protocol(word_set_for(previous_sessions), rng or random.SystemRandom()),
        source=AssessmentSource.LIVE_DEMO,
    )
    db.add(session)
    db.flush()
    # Forecast (or a sanitized unavailability reason) is persisted before task content is returned.
    issue_forecast(db, session, reps, now)
    profile = db.get(PatientProfile, patient_id)
    audit(
        db,
        "SESSION_STARTED",
        "assessment_session",
        session.id,
        patient_id=patient_id,
        actor_user_id=profile.user_id if profile else None,
        details={"purpose": purpose.value, "forecast_state": session.forecast_state},
    )
    return session, True


def build_frozen_session(
    *,
    patient_id: uuid.UUID,
    req: StartSessionRequest,
    started_at: datetime,
    anchor: datetime,
    slot: int,
    target: datetime,
    purpose: SchedulePurpose,
    schedule_reason: str,
    starts: int,
    reps: dict[int, Assessment],
    task_protocol: dict[str, Any],
    source: AssessmentSource,
    session_id: uuid.UUID | None = None,
) -> AssessmentSession:
    """Freeze comparability, forecast availability and the protocol snapshot before any answers.

    Shared by live starts and controlled synthetic-history import, so both follow one rule set.
    `reps` must contain only representatives available before `started_at`.
    """
    # Comparability relative to the most recent earlier representative.
    prior_reps = [r for k, r in sorted(reps.items()) if k < slot]
    latest = prior_reps[-1] if prior_reps else None
    epoch = latest.quality_details["comparability"]["epoch"] if latest else 0
    comparability_flags: list[str] = []
    if latest is not None:
        if latest.protocol_version != PROTOCOL_VERSION or latest.scoring_version != SCORING_VERSION:
            comparability_flags.append("PROTOCOL_MISMATCH")
        if latest.quality_details["input_mode"] != req.input_mode or req.device_changed:
            comparability_flags.append("COMPARABILITY_CHANGE")
    if req.device_changed:
        epoch += 1
    key = schedule.comparability_key(PROTOCOL_VERSION, SCORING_VERSION, req.input_mode, epoch)

    # Forecast availability, frozen now (schedule/comparability first, then history, then model).
    reasons: list[str] = []
    if purpose in (SchedulePurpose.EXTRA_ATTEMPT, SchedulePurpose.OFF_SCHEDULE):
        reasons.append(purpose.value)
    reasons += comparability_flags
    history_state, history_reasons = schedule.evaluate_history(
        slot,
        {k: _as_rep(r) for k, r in reps.items()},
        key,
        PROTOCOL_VERSION,
        SCORING_VERSION,
        get_settings().SEQUENCE_LENGTH,
    )
    # A known schedule/comparability problem outranks history; all reasons are kept.
    forecast_state = ForecastState.INSUFFICIENT_DATA if reasons else history_state
    reasons += [r for r in history_reasons if r not in reasons]

    snapshot = {
        **task_protocol,
        "input_mode": req.input_mode.value,
        "initial_request": _normalized_request(req),
        "schedule": {
            "version": schedule.SCHEDULE_VERSION,
            "anchor_at": anchor.isoformat(),
            "slot_index": slot,
            "target_at": target.isoformat(),
            "purpose": purpose.value,
            "reason": schedule_reason,
            "attempt_number": starts + 1 if purpose in REPRESENTATIVE_PURPOSES else None,
            "eligible_for_longitudinal_use": purpose
            in REPRESENTATIVE_PURPOSES,  # provisional until submission
        },
        "comparability": {"epoch": epoch, "key": key, "flags": comparability_flags},
        "session": {"expiry_minutes": SESSION_EXPIRY_MINUTES},
    }

    session = AssessmentSession(
        id=session_id or uuid.uuid4(),
        patient_id=patient_id,
        start_key=req.start_key,
        status=SessionStatus.STARTED,
        source=source,
        protocol_version=PROTOCOL_VERSION,
        scoring_version=SCORING_VERSION,
        input_mode=req.input_mode.value,
        schedule_purpose=purpose.value,
        slot_index=slot,
        target_at=target,
        forecast_state=forecast_state.value,
        forecast_reasons=reasons,
        history_cutoff_at=started_at,
        protocol_snapshot=snapshot,
        started_at=started_at,
        expires_at=started_at + timedelta(minutes=SESSION_EXPIRY_MINUTES),
    )
    return session


def abandon_session(
    db: Session, patient_id: uuid.UUID, session_id: uuid.UUID, now: datetime
) -> AssessmentSession:
    lock_patient(db, patient_id)
    expire_stale_sessions(db, patient_id, now)
    session = get_owned_session(db, patient_id, session_id)
    db.refresh(session)
    if session.status == SessionStatus.SUBMITTED:
        raise AssessmentConflict("SESSION_ALREADY_SUBMITTED", "A submitted check-in can't be discarded.")
    if session.status == SessionStatus.STARTED:
        session.status = SessionStatus.ABANDONED
        session.ended_at = now
        profile = db.get(PatientProfile, patient_id)
        audit(
            db,
            "SESSION_ABANDONED",
            "assessment_session",
            session.id,
            patient_id=patient_id,
            actor_user_id=profile.user_id if profile else None,
        )
    return session  # ABANDONED / EXPIRED: repeat is a no-op without another event
