"""Patient assessment routes (guide 02, guide 05 §6–§9). Patient identity comes from the token's DB user."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, PatientDep
from app.core.config import get_settings
from app.core.errors import ApiError, error_responses, not_found
from app.models import AnalysisState, AssessmentSession, SessionStatus
from app.schemas.assessments import (
    AssessmentReceipt,
    AssessmentStatus,
    AssessmentSubmission,
    RenderProtocolOut,
    SessionRecoveryResponse,
    SessionSchedule,
    StartAssessmentResponse,
    StartSessionRequest,
)
from app.services.analyses import analyze_after_commit
from app.services.assessment_sessions import (
    AssessmentConflict,
    SessionNotFound,
    abandon_session,
    effective_status,
    get_owned_session,
    start_session,
)
from app.services.assessment_submissions import (
    SubmissionInvalid,
    assessment_status,
    build_receipt,
    find_by_key,
    get_receipt,
    payload_digest,
    submit_assessment,
)
from app.services.scoring import ScoringInputError

router = APIRouter(prefix="/patient", tags=["patient assessments"])


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(exc: AssessmentConflict) -> ApiError:
    # Details carry only the caller's own recovery identifiers (session id, expiry, next window).
    return ApiError(409, exc.code, exc.message, details=exc.extra)


def _receipt_path(assessment_id: uuid.UUID) -> str:
    return f"{get_settings().API_PREFIX}/patient/assessments/{assessment_id}/receipt"


def _schedule(session: AssessmentSession) -> SessionSchedule:
    snap = session.protocol_snapshot
    sched = snap["schedule"]
    eligible = (
        session.assessment.longitudinal_eligible
        if session.assessment is not None
        else bool(sched["eligible_for_longitudinal_use"])
    )
    return SessionSchedule(
        anchor_at=datetime.fromisoformat(sched["anchor_at"]),
        slot_index=session.slot_index,
        target_at=session.target_at,
        purpose=session.schedule_purpose,  # type: ignore[arg-type]
        longitudinal_eligible=eligible,
        reason_codes=[sched["reason"], *snap["comparability"]["flags"]],
    )


def _session_fields(session: AssessmentSession, now: datetime) -> dict:
    return {
        "session_id": session.id,
        "status": effective_status(session, now),
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "target_at": session.target_at,
        "protocol_version": session.protocol_version,
        "scoring_version": session.scoring_version,
        "input_mode": session.input_mode,
        "schedule": _schedule(session),
    }


@router.get(
    "/assessment-status",
    response_model=AssessmentStatus,
    operation_id="getAssessmentStatus",
    responses=error_responses(401, 403),
)
def get_assessment_status(patient: PatientDep, db: DbDep) -> AssessmentStatus:
    """Schedule, last receipt and unfinished-session recovery. Read-only (never mutates)."""
    return assessment_status(db, patient.id, _now())


@router.post(
    "/assessment-sessions",
    response_model=StartAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="startAssessmentSession",
    responses={
        200: {"description": "Idempotent replay of the same start_key", "model": StartAssessmentResponse},
        **error_responses(401, 403, 409, 413, 415, 422),
    },
)
def create_session(
    req: StartSessionRequest, patient: PatientDep, db: DbDep, response: Response
) -> StartAssessmentResponse:
    """Start and freeze one session (protocol, schedule, comparability, forecast) before any task runs.

    409 codes: ACTIVE_SESSION_EXISTS, IDEMPOTENCY_CONFLICT, OUTSIDE_SCHEDULE_WINDOW,
    ATTEMPT_LIMIT_REACHED, SLOT_COMPLETED.
    """
    now = _now()
    try:
        session, created = start_session(db, patient.id, req, now)
        db.commit()
    except AssessmentConflict as exc:
        db.rollback()
        raise _conflict(exc) from None
    except IntegrityError:  # concurrent start with the same key: reread the canonical row
        db.rollback()
        try:
            session, created = start_session(db, patient.id, req, now)
        except AssessmentConflict as exc:
            raise _conflict(exc) from None
        db.commit()
    except Exception:
        db.rollback()  # e.g. a failed commit: no half-created session may linger
        raise
    if not created:
        response.status_code = status.HTTP_200_OK
    live = effective_status(session, now) == SessionStatus.STARTED
    return StartAssessmentResponse(
        **_session_fields(session, now),
        protocol=RenderProtocolOut.model_validate(session.protocol_snapshot) if live else None,
        replayed=not created,
    )


@router.get(
    "/assessment-sessions/{session_id}",
    response_model=SessionRecoveryResponse,
    operation_id="getAssessmentSession",
    responses=error_responses(401, 403, 404, 422),
)
def get_session(session_id: uuid.UUID, patient: PatientDep, db: DbDep) -> SessionRecoveryResponse:
    """Owned session metadata. Task material and raw answers are never re-exposed."""
    try:
        session = get_owned_session(db, patient.id, session_id)
    except SessionNotFound:
        raise not_found() from None
    assessment_id = session.assessment.id if session.assessment else None
    return SessionRecoveryResponse(
        **_session_fields(session, _now()),
        assessment_id=assessment_id,
        receipt_path=_receipt_path(assessment_id) if assessment_id else None,
    )


@router.post(
    "/assessment-sessions/{session_id}/submissions",
    response_model=AssessmentReceipt,
    status_code=status.HTTP_201_CREATED,
    operation_id="submitAssessment",
    responses={
        200: {"description": "Idempotent replay (same key and body)", "model": AssessmentReceipt},
        **error_responses(401, 403, 404, 409, 413, 415, 422, 503),
    },
)
def submit(
    session_id: uuid.UUID, payload: AssessmentSubmission, patient: PatientDep, db: DbDep, response: Response
) -> AssessmentReceipt:
    """Phase A (score + durable receipt) then a short bounded phase-B analysis attempt.

    A committed receipt is returned even if analysis fails (analysis shows ANALYSIS_ERROR/PENDING).
    409 codes: IDEMPOTENCY_CONFLICT, SESSION_EXPIRED, SESSION_ALREADY_SUBMITTED, SESSION_ABANDONED.
    """
    try:
        assessment, created = submit_assessment(db, patient.id, session_id, payload, _now())
        db.commit()  # phase A: nothing below may undo this receipt
    except SessionNotFound:
        db.rollback()
        raise not_found() from None
    except AssessmentConflict as exc:
        db.rollback()
        raise _conflict(exc) from None
    except (SubmissionInvalid, ScoringInputError):
        db.rollback()
        raise ApiError(
            422, "INVALID_SUBMISSION", "The submission does not match this session's activities."
        ) from None
    except IntegrityError:
        # A concurrent request committed first: compare against the canonical stored row.
        db.rollback()
        existing = find_by_key(db, patient.id, payload.submission_key)
        if existing is None or existing.payload_sha256 != payload_digest(session_id, payload):
            raise ApiError(
                409,
                "SESSION_ALREADY_SUBMITTED" if existing is None else "IDEMPOTENCY_CONFLICT",
                "This check-in was already saved.",
            ) from None
        assessment, created = existing, False
    except Exception:
        # Anything else (e.g. the commit itself failed): nothing from this attempt may linger.
        db.rollback()
        raise

    if assessment.analysis_state in (AnalysisState.PENDING, AnalysisState.ANALYSIS_ERROR):
        # Bounded foreground attempt; a replay retries only unfinished work, never a finalized result.
        analyze_after_commit(db, assessment.id, _now())
        db.refresh(assessment)
    if created:
        response.headers["Location"] = _receipt_path(assessment.id)
    else:
        response.status_code = status.HTTP_200_OK
    return build_receipt(assessment, replayed=not created)


@router.post(
    "/assessment-sessions/{session_id}/abandon",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="abandonAssessmentSession",
    responses=error_responses(401, 403, 404, 409, 422),
)
def abandon(session_id: uuid.UUID, patient: PatientDep, db: DbDep) -> Response:
    """STARTED → ABANDONED (+ audit event). Already abandoned/expired → 204; submitted → 409."""
    try:
        abandon_session(db, patient.id, session_id, _now())
        db.commit()
    except SessionNotFound:
        db.rollback()
        raise not_found() from None
    except AssessmentConflict as exc:
        db.rollback()
        raise _conflict(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/assessments/{assessment_id}/receipt",
    response_model=AssessmentReceipt,
    operation_id="getAssessmentReceipt",
    responses=error_responses(401, 403, 404, 422),
)
def receipt(assessment_id: uuid.UUID, patient: PatientDep, db: DbDep) -> AssessmentReceipt:
    """Safe persisted receipt with the current analysis availability. GET never processes work."""
    assessment = get_receipt(db, patient.id, assessment_id)
    if assessment is None:
        raise not_found()
    return build_receipt(assessment, replayed=False)
