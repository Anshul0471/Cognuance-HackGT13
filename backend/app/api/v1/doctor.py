"""Doctor routes (guide 05 §11–§13). Every route re-applies the caller's current assignments."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, DoctorDep
from app.core.errors import error_responses
from app.schemas.common import UtcDateTime
from app.schemas.doctor import (
    AlertDetail,
    AlertEventPage,
    AlertEventRequest,
    AlertEventResponse,
    AlertPage,
    AssessmentDetail,
    DoctorPatientDetail,
    DoctorSummary,
    InsightsResponse,
    PatientPage,
    TimelinePage,
)
from app.services import doctor_views, reviews

router = APIRouter(prefix="/doctor", tags=["doctor"])

Limit20 = Annotated[int, Query(ge=1, le=100, description="Page size (default 20, max 100)")]
Limit50 = Annotated[int, Query(ge=1, le=100, description="Page size (default 50, max 100)")]
Cursor = Annotated[
    str | None, Query(max_length=2048, description="Opaque next_cursor from the previous page")
]
_READ_ERRORS = error_responses(400, 401, 403, 404, 422)


def _now() -> datetime:
    return datetime.now(UTC)


@router.get(
    "/summary",
    response_model=DoctorSummary,
    operation_id="getDoctorSummary",
    responses=error_responses(401, 403),
)
def get_summary(doctor: DoctorDep, db: DbDep) -> DoctorSummary:
    """Counts over currently assigned patients only (operational categories, not risk estimates)."""
    return doctor_views.summary(db, doctor, _now())


@router.get(
    "/patients", response_model=PatientPage, operation_id="listDoctorPatients", responses=_READ_ERRORS
)
def list_patients(
    doctor: DoctorDep,
    db: DbDep,
    limit: Limit20 = 20,
    cursor: Cursor = None,
    q: Annotated[str | None, Query(max_length=100, description="Search display name / demo key")] = None,
    has_unresolved_alerts: bool | None = None,
) -> PatientPage:
    """Assigned patients, newest profile first (created_at DESC, patient_id DESC)."""
    return doctor_views.list_patients(
        db,
        doctor,
        limit=limit,
        cursor=cursor,
        q=q or None,
        has_unresolved_alerts=has_unresolved_alerts,
        now=_now(),
    )


@router.get(
    "/patients/{patient_id}",
    response_model=DoctorPatientDetail,
    operation_id="getDoctorPatient",
    responses=_READ_ERRORS,
)
def get_patient(patient_id: uuid.UUID, doctor: DoctorDep, db: DbDep) -> DoctorPatientDetail:
    return doctor_views.patient_detail(db, doctor, patient_id)


@router.get(
    "/patients/{patient_id}/timeline",
    response_model=TimelinePage,
    operation_id="getPatientTimeline",
    responses=_READ_ERRORS,
)
def get_timeline(
    patient_id: uuid.UUID,
    doctor: DoctorDep,
    db: DbDep,
    limit: Limit50 = 50,
    cursor: Cursor = None,
    frm: Annotated[UtcDateTime | None, Query(alias="from", description="Inclusive UTC lower bound")] = None,
    to: Annotated[UtcDateTime | None, Query(description="Exclusive UTC upper bound")] = None,
) -> TimelinePage:
    """Every observation (incl. LOW/INCOMPLETE/extra/off-schedule), observed_at DESC. Nulls stay null."""
    return doctor_views.timeline(
        db, doctor, patient_id, limit=limit, cursor=cursor, frm=frm, to=to, now=_now()
    )


@router.get(
    "/patients/{patient_id}/assessments/{assessment_id}",
    response_model=AssessmentDetail,
    operation_id="getPatientAssessment",
    responses=_READ_ERRORS,
)
def get_assessment(
    patient_id: uuid.UUID, assessment_id: uuid.UUID, doctor: DoctorDep, db: DbDep
) -> AssessmentDetail:
    """Scored evidence, context and grounded analysis details. No raw response payload."""
    return doctor_views.assessment_detail(db, doctor, patient_id, assessment_id)


@router.get(
    "/patients/{patient_id}/insights",
    response_model=InsightsResponse,
    operation_id="getPatientInsights",
    responses=_READ_ERRORS,
)
def get_insights(
    patient_id: uuid.UUID,
    doctor: DoctorDep,
    db: DbDep,
    frm: Annotated[UtcDateTime, Query(alias="from", description="Inclusive UTC lower bound")],
    to: Annotated[UtcDateTime, Query(description="Exclusive UTC upper bound")],
    source: Annotated[
        Literal["ALL", "LIVE_DEMO", "SYNTHETIC_HISTORY", "SCENARIO_REPLAY"],
        Query(description="`ALL` (default) or one assessment source"),
    ] = "ALL",
) -> InsightsResponse:
    """One complete bounded snapshot for the Visual Insights panels (refinement 01).

    Read-only; every record carries its `cognitive_index_v1` projection, context, comparability
    segment and linked alert. Ordered (observed_at ASC, assessment_id ASC). 400 `INVALID_QUERY`
    if `from >= to` or the window exceeds 366 days; 422 `INSIGHTS_RANGE_TOO_LARGE` above 500
    assessments (never truncated).
    """
    return doctor_views.insights(db, doctor, patient_id, frm=frm, to=to, source=source, now=_now())


@router.get("/alerts", response_model=AlertPage, operation_id="listDoctorAlerts", responses=_READ_ERRORS)
def list_alerts(
    doctor: DoctorDep,
    db: DbDep,
    limit: Limit20 = 20,
    cursor: Cursor = None,
    patient_id: uuid.UUID | None = None,
    workflow_status: Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"] | None = None,
    deviation_level: Literal["REVIEW", "PERSISTENT_DEVIATION", "HIGH_DEVIATION"] | None = None,
    include_resolved: bool = False,
) -> AlertPage:
    """Default: unresolved (OPEN or ACKNOWLEDGED). Ordered created_at DESC, alert_id DESC."""
    return doctor_views.list_alerts(
        db,
        doctor,
        limit=limit,
        cursor=cursor,
        patient_id=patient_id,
        workflow_status=workflow_status,
        deviation_level=deviation_level,
        include_resolved=include_resolved,
        now=_now(),
    )


@router.get(
    "/alerts/{alert_id}", response_model=AlertDetail, operation_id="getDoctorAlert", responses=_READ_ERRORS
)
def get_alert(alert_id: uuid.UUID, doctor: DoctorDep, db: DbDep) -> AlertDetail:
    return doctor_views.alert_detail(db, doctor, alert_id)


@router.get(
    "/alerts/{alert_id}/events",
    response_model=AlertEventPage,
    operation_id="listAlertEvents",
    responses=_READ_ERRORS,
)
def list_alert_events(
    alert_id: uuid.UUID, doctor: DoctorDep, db: DbDep, limit: Limit20 = 20, cursor: Cursor = None
) -> AlertEventPage:
    """Append-only review history, created_at ASC. Actor is null for the system CREATED event."""
    return reviews.list_events(db, doctor, alert_id, limit=limit, cursor=cursor, now=_now())


@router.post(
    "/alerts/{alert_id}/events",
    response_model=AlertEventResponse,
    operation_id="recordAlertEvent",
    responses=error_responses(401, 403, 404, 409, 413, 415, 422),
)
def post_alert_event(
    alert_id: uuid.UUID, body: AlertEventRequest, doctor: DoctorDep, db: DbDep
) -> AlertEventResponse:
    """Acknowledge, add a note, or resolve (200). Same request_key + same payload → replayed=true.

    409 codes: IDEMPOTENCY_CONFLICT, STALE_ALERT_VERSION (details: current status/version),
    INVALID_ALERT_TRANSITION.
    """
    try:
        response, _ = reviews.record_event(db, doctor, alert_id, body, _now())
        db.commit()
    except IntegrityError:  # concurrent same-key request committed first
        db.rollback()
        response = reviews.replay_after_race(db, doctor, alert_id, body)
    except Exception:
        db.rollback()
        raise
    return response
