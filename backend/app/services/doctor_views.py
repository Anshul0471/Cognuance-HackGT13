"""Assignment-scoped doctor read models (guide 05 §11–§14). GETs never process work or mark anything read.

Scope first (current active assignments), then filters, then keyset pagination; related rows are
batch-loaded per page (no N+1). Cursors pin the first page's upper-bound time so later inserts do
not shift a traversal; mutable review state is not a repeatable snapshot (refresh = new view).
"""

import uuid
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, selectinload

from app.core import cursors
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.models import (
    Alert,
    AlertStatus,
    Analysis,
    AnalysisState,
    AnomalyPolicy,
    Assessment,
    Forecast,
    ModelVersion,
    PatientProfile,
    User,
)
from app.schemas.doctor import (
    AlertDetail,
    AlertListItem,
    AlertPage,
    AlertRef,
    AnalysisDetails,
    AnalysisSummary,
    AssessmentDetail,
    CognitiveIndex,
    CognitiveIndexComponents,
    CognitiveIndexMetadata,
    ContextOut,
    DoctorPatientDetail,
    DoctorSummary,
    ForecastSummary,
    InsightAlert,
    InsightAssessment,
    InsightsFilters,
    InsightsResponse,
    PatientHeader,
    PatientListItem,
    PatientPage,
    QualityDetails,
    Scores,
    TaskEvidence,
    TimelineItem,
    TimelinePage,
)
from app.services import cognitive_index
from app.services.access import active_assignment, assigned_patient_ids, get_assigned_patient

UNRESOLVED = (AlertStatus.OPEN.value, AlertStatus.ACKNOWLEDGED.value)
_DOMAINS = ("memory", "attention", "reaction_time_ms")
# Insights returns one bounded snapshot: overflow is an explicit error, never a partial answer.
MAX_INSIGHTS_RECORDS = 500
MAX_INSIGHTS_WINDOW = timedelta(days=366)


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _page_state(cursor: str | None, endpoint: str, filters: dict[str, Any], caller: User, now: datetime):
    if cursor is None:
        return now, None
    state = cursors.decode(cursor, endpoint, filters, caller.id)
    return state.upper_bound, state.last


def _next(
    rows: list, limit: int, endpoint: str, filters: dict[str, Any], caller: User, ub: datetime, key
) -> tuple[list, str | None]:
    if len(rows) <= limit:
        return rows, None
    page = rows[:limit]
    return page, cursors.encode(endpoint, filters, caller.id, ub, key(page[-1]))


# --- summary -------------------------------------------------------------------------------------


def summary(db: Session, doctor: User, now: datetime) -> DoctorSummary:
    ids = assigned_patient_ids(doctor)
    alerts = (
        select(Alert.status, func.count(), func.count(func.distinct(Alert.patient_id)))
        .where(Alert.patient_id.in_(ids))
        .group_by(Alert.status)
    )
    counts = {status: (n, patients) for status, n, patients in db.execute(alerts)}
    unresolved_patients = db.scalar(
        select(func.count(func.distinct(Alert.patient_id))).where(
            Alert.patient_id.in_(ids), Alert.status.in_(UNRESOLVED)
        )
    )
    analyses = dict(
        db.execute(
            select(Analysis.availability, func.count())
            .where(
                Analysis.patient_id.in_(ids),
                Analysis.availability.in_([AnalysisState.PENDING.value, AnalysisState.ANALYSIS_ERROR.value]),
            )
            .group_by(Analysis.availability)
        ).all()
    )
    return DoctorSummary(
        assigned_patient_count=db.scalar(select(func.count()).select_from(ids.subquery())) or 0,
        patients_with_open_alerts=unresolved_patients or 0,
        open_alert_count=counts.get(AlertStatus.OPEN.value, (0, 0))[0],
        acknowledged_alert_count=counts.get(AlertStatus.ACKNOWLEDGED.value, (0, 0))[0],
        pending_analysis_count=analyses.get(AnalysisState.PENDING.value, 0),
        analysis_error_count=analyses.get(AnalysisState.ANALYSIS_ERROR.value, 0),
        generated_at=now,
    )


# --- patients ------------------------------------------------------------------------------------


def _latest(db: Session, patient_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[datetime, str, str | None]]:
    if not patient_ids:
        return {}
    rows = db.execute(
        select(
            Assessment.patient_id, Assessment.observed_at, Assessment.analysis_state, Analysis.deviation_level
        )
        .outerjoin(Analysis, Analysis.assessment_id == Assessment.id)
        .where(Assessment.patient_id.in_(patient_ids))
        .ext(distinct_on(Assessment.patient_id))
        .order_by(Assessment.patient_id, Assessment.observed_at.desc(), Assessment.id.desc())
    )
    return {pid: (at, state, level) for pid, at, state, level in rows}


def _alert_counts(db: Session, patient_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    out: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"OPEN": 0, "ACKNOWLEDGED": 0})
    if patient_ids:
        for pid, status, n in db.execute(
            select(Alert.patient_id, Alert.status, func.count())
            .where(Alert.patient_id.in_(patient_ids), Alert.status.in_(UNRESOLVED))
            .group_by(Alert.patient_id, Alert.status)
        ):
            out[pid][status] = n
    return out


def _header(profile: PatientProfile, user: User) -> PatientHeader:
    return PatientHeader(
        patient_id=profile.id,
        display_name=user.display_name,
        is_demo=profile.provenance == "synthetic_seed",
        timezone=profile.timezone,
        account_active=user.is_active,
    )


def list_patients(
    db: Session,
    doctor: User,
    *,
    limit: int,
    cursor: str | None,
    q: str | None,
    has_unresolved_alerts: bool | None,
    now: datetime,
) -> PatientPage:
    filters = {"q": q, "has_unresolved_alerts": has_unresolved_alerts}
    ub, last = _page_state(cursor, "doctor.patients", filters, doctor, now)
    query = (
        select(PatientProfile, User)
        .join(User, User.id == PatientProfile.user_id)
        .where(PatientProfile.id.in_(assigned_patient_ids(doctor)), PatientProfile.created_at <= ub)
    )
    if q:
        pattern = _like(q)
        query = query.where(
            or_(
                User.display_name.ilike(pattern, escape="\\"),
                PatientProfile.demo_scenario.ilike(pattern, escape="\\"),
            )
        )
    if has_unresolved_alerts is not None:
        unresolved = exists().where(Alert.patient_id == PatientProfile.id, Alert.status.in_(UNRESOLVED))
        query = query.where(unresolved if has_unresolved_alerts else ~unresolved)
    if last:
        query = query.where(
            tuple_(PatientProfile.created_at, PatientProfile.id)
            < tuple_(literal(datetime.fromisoformat(last[0])), literal(uuid.UUID(last[1])))
        )
    rows = db.execute(
        query.order_by(PatientProfile.created_at.desc(), PatientProfile.id.desc()).limit(limit + 1)
    ).all()
    page, nxt = _next(
        rows,
        limit,
        "doctor.patients",
        filters,
        doctor,
        ub,
        lambda r: [r[0].created_at.isoformat(), str(r[0].id)],
    )
    ids = [p.id for p, _ in page]
    latest, counts = _latest(db, ids), _alert_counts(db, ids)
    items = []
    for profile, user in page:
        at, state, level = latest.get(profile.id, (None, None, None))
        items.append(
            PatientListItem(
                patient_id=profile.id,
                display_name=user.display_name,
                is_demo=profile.provenance == "synthetic_seed",
                account_active=user.is_active,
                latest_assessment_at=at,
                latest_analysis_availability=state,
                latest_deviation_level=level,
                unresolved_alert_count=sum(counts[profile.id].values()),
            )
        )
    return PatientPage(items=items, next_cursor=nxt)


def patient_detail(db: Session, doctor: User, patient_id: uuid.UUID) -> DoctorPatientDetail:
    assignment = active_assignment(db, doctor, patient_id)
    if assignment is None:
        raise not_found()
    profile = db.get(PatientProfile, patient_id)
    assert profile is not None
    user = db.get(User, profile.user_id)
    at, state, level = _latest(db, [patient_id]).get(patient_id, (None, None, None))
    counts = _alert_counts(db, [patient_id])[patient_id]
    return DoctorPatientDetail(
        patient=_header(profile, user),
        assigned_at=assignment.created_at,
        latest_assessment_at=at,
        latest_analysis_availability=state,
        latest_deviation_level=level,
        open_alert_count=counts["OPEN"],
        acknowledged_alert_count=counts["ACKNOWLEDGED"],
        score_metadata=CognitiveIndexMetadata(**cognitive_index.metadata()),
    )


# --- timeline / detail ----------------------------------------------------------------------------


def _related(db: Session, assessments: list[Assessment]):
    ids = [a.id for a in assessments]
    analyses = {
        r.assessment_id: r for r in db.scalars(select(Analysis).where(Analysis.assessment_id.in_(ids)))
    }
    alerts = {r.assessment_id: r for r in db.scalars(select(Alert).where(Alert.assessment_id.in_(ids)))}
    forecasts: dict[uuid.UUID, tuple[Forecast, ModelVersion, AnomalyPolicy]] = {}
    for f, m, p in db.execute(
        select(Forecast, ModelVersion, AnomalyPolicy)
        .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
        .join(AnomalyPolicy, AnomalyPolicy.id == Forecast.policy_id)
        .where(Forecast.session_id.in_([a.session_id for a in assessments]))
    ):
        forecasts[f.session_id] = (f, m, p)
    return analyses, alerts, forecasts


def _index_components(result: cognitive_index.IndexResult) -> CognitiveIndexComponents | None:
    c = result.components
    return None if c is None else CognitiveIndexComponents(**asdict(c))


def _cognitive_index(
    a: Assessment, fc: tuple[Forecast, ModelVersion, AnomalyPolicy] | None
) -> CognitiveIndex:
    """Derived on read from immutable stored task outcomes and the frozen forecast (never cached)."""
    observed = cognitive_index.observed_index(
        quality=a.quality,
        memory_score=a.memory_score,
        attention_score=a.attention_score,
        reaction_time_ms=a.reaction_time_ms,
        protocol_version=a.protocol_version,
        scoring_version=a.scoring_version,
    )
    if fc is None:
        forecast = cognitive_index.missing_forecast()
    else:
        f = fc[0]
        # Provenance comes from the forecast's own frozen key (protocol|scoring|input mode|epoch).
        parts = f.comparability_key.split("|")
        forecast = cognitive_index.forecast_index(
            predicted_memory_score=f.predicted_memory_score,
            predicted_attention_score=f.predicted_attention_score,
            predicted_reaction_time_ms=f.predicted_reaction_time_ms,
            protocol_version=parts[0] if parts else "",
            scoring_version=parts[1] if len(parts) > 1 else "",
        )
    return CognitiveIndex(
        version=cognitive_index.COGNITIVE_INDEX_VERSION,
        observed_value=observed.value,
        forecast_value=forecast.value,
        observed_components=_index_components(observed),
        forecast_components=_index_components(forecast),
        observed_unavailable_reasons=list(observed.reasons),
        forecast_unavailable_reasons=list(forecast.reasons),
        forecast_response_speed_clipped=forecast.response_speed_clipped,
    )


def _item_fields(
    a: Assessment,
    analysis: Analysis | None,
    alert: Alert | None,
    fc: tuple[Forecast, ModelVersion, AnomalyPolicy] | None,
) -> dict[str, Any]:
    forecast = None
    if fc is not None:
        f, m, p = fc
        forecast = ForecastSummary(
            forecast_id=f.id,
            issued_at=f.issued_at,
            history_cutoff_at=f.history_cutoff_at,
            model_kind=m.kind,
            model_version=m.version,
            policy_version=p.version,
            predicted_memory_score=float(f.predicted_memory_score),
            predicted_attention_score=float(f.predicted_attention_score),
            predicted_reaction_time_ms=float(f.predicted_reaction_time_ms),
        )
    availability = analysis.availability if analysis else a.analysis_state
    reasons = analysis.reasons if analysis else a.analysis_reasons
    return {
        "assessment_id": a.id,
        "observed_at": a.observed_at,
        "target_at": a.target_at,
        "source": a.source,
        "schedule_purpose": a.schedule_purpose,
        "quality_status": a.quality,
        "longitudinal_eligible": a.longitudinal_eligible,
        "scores": Scores(
            memory_score=_f(a.memory_score),
            attention_score=_f(a.attention_score),
            reaction_time_ms=_f(a.reaction_time_ms),
        ),
        "forecast": forecast,
        "analysis": AnalysisSummary(
            availability=availability,
            deviation_level=analysis.deviation_level if analysis else None,
            aggregate_deviation=analysis.aggregate_deviation if analysis else None,
            persistent_count=analysis.persistent_count if analysis else None,
            reason_codes=list(reasons),
        ),
        "alert": AlertRef(alert_id=alert.id, workflow_status=alert.status, lock_version=alert.lock_version)
        if alert
        else None,
        "cognitive_index": _cognitive_index(a, fc),
    }


def timeline(
    db: Session,
    doctor: User,
    patient_id: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
    frm: datetime | None,
    to: datetime | None,
    now: datetime,
) -> TimelinePage:
    if frm is not None and to is not None and frm >= to:
        raise ApiError(400, "INVALID_QUERY", "`from` must be earlier than `to`.")
    if get_assigned_patient(db, doctor, patient_id) is None:
        raise not_found()
    filters = {
        "patient_id": str(patient_id),
        "from": frm.isoformat() if frm else None,
        "to": to.isoformat() if to else None,
    }
    ub, last = _page_state(cursor, "doctor.timeline", filters, doctor, now)
    query = select(Assessment).where(Assessment.patient_id == patient_id, Assessment.created_at <= ub)
    if frm is not None:
        query = query.where(Assessment.observed_at >= frm)
    if to is not None:
        query = query.where(Assessment.observed_at < to)
    if last:
        query = query.where(
            tuple_(Assessment.observed_at, Assessment.id)
            < tuple_(literal(datetime.fromisoformat(last[0])), literal(uuid.UUID(last[1])))
        )
    rows = list(
        db.scalars(query.order_by(Assessment.observed_at.desc(), Assessment.id.desc()).limit(limit + 1))
    )
    page, nxt = _next(
        rows, limit, "doctor.timeline", filters, doctor, ub, lambda a: [a.observed_at.isoformat(), str(a.id)]
    )
    analyses, alerts, forecasts = _related(db, page)
    items = [
        TimelineItem(**_item_fields(a, analyses.get(a.id), alerts.get(a.id), forecasts.get(a.session_id)))
        for a in page
    ]
    return TimelinePage(items=items, next_cursor=nxt)


def _medication(value: str | None) -> bool | None:
    return {"YES": True, "NO": False}.get(value or "")


def _context_out(ctx: Any) -> ContextOut | None:
    """Exact saved check-in fields; unknown medication stays unknown (never coerced to "no")."""
    if ctx is None:
        return None
    return ContextOut(
        sleep_hours=_f(ctx.sleep_hours),
        mood_score=ctx.mood_score,
        medication_change=_medication(ctx.medication_change),
        reported_by=ctx.reported_by,
        missing_fields={m["field"]: m["reason"] for m in ctx.missing_fields}
        | ({"medication_change": "UNKNOWN"} if ctx.medication_change == "NOT_SURE" else {}),
    )


def _streak_ids(db: Session, a: Assessment, analysis: Analysis | None) -> list[uuid.UUID]:
    if analysis is None or not analysis.persistent_count or analysis.persistent_count < 2:
        return []
    earlier = db.scalars(
        select(Assessment.id)
        .where(
            Assessment.patient_id == a.patient_id,
            Assessment.longitudinal_eligible.is_(True),
            Assessment.slot_index.between(a.slot_index - analysis.persistent_count + 1, a.slot_index - 1),
        )
        .order_by(Assessment.slot_index)
    ).all()
    return list(earlier)


def _detail(db: Session, a: Assessment) -> AssessmentDetail:
    analyses, alerts, forecasts = _related(db, [a])
    analysis, fc = analyses.get(a.id), forecasts.get(a.session_id)
    qd = a.quality_details
    tasks = {
        name: TaskEvidence(
            completion=t["completion"],
            status=t["status"],
            low_flags=t["low_flags"],
            warnings=t["warnings"],
            counters=t["counters"],
        )
        for name, t in qd.get("tasks", {}).items()
    }
    quality = QualityDetails(
        overall=a.quality,
        tasks=tasks,
        initial_input_mode=qd.get("input_mode", ""),
        final_input_mode=qd.get("final_input_mode"),
        assistance=qd.get("assistance", {}),
        comparability_key=qd.get("comparability", {}).get("key", ""),
        comparability_flags=qd.get("comparability_flags", []),
        practice_repeated=bool(qd.get("practice", {}).get("warnings")),
    )
    context = _context_out(a.context)
    model = fc[1] if fc else None
    policy = fc[2] if fc else None
    details = AnalysisDetails(
        computed_at=analysis.computed_at if analysis else None,
        aggregate_method=policy.configuration["rules"]["aggregate_method"] if policy else None,
        max_deviation=analysis.max_deviation if analysis else None,
        moderate_signal=analysis.moderate_signal if analysis else None,
        high_signal=analysis.high_signal if analysis else None,
        persistent_count=analysis.persistent_count if analysis else None,
        streak_evidence_assessment_ids=_streak_ids(db, a, analysis),
        domain_deviations=analysis.domain_deviations if analysis else None,
        model_kind=model.kind if model else None,
        model_version=model.version if model else None,
        policy_version=policy.version if policy else None,
        preprocessing_version=model.preprocessing_version if model else None,
        explanation=analysis.explanation if analysis else None,
    )
    return AssessmentDetail(
        **_item_fields(a, analysis, alerts.get(a.id), fc),
        protocol_version=a.protocol_version,
        scoring_version=a.scoring_version,
        quality_details=quality,
        context=context,
        analysis_details=details,
    )


def assessment_detail(
    db: Session, doctor: User, patient_id: uuid.UUID, assessment_id: uuid.UUID
) -> AssessmentDetail:
    if get_assigned_patient(db, doctor, patient_id) is None:
        raise not_found()
    a = db.scalar(
        select(Assessment).where(Assessment.id == assessment_id, Assessment.patient_id == patient_id)
    )
    if a is None:  # someone else's assessment under this patient path is indistinguishable from missing
        raise not_found()
    return _detail(db, a)


# --- alerts -------------------------------------------------------------------------------------


def _affected(analysis: Analysis) -> list[str]:
    facts = (analysis.explanation or {}).get("facts", {})
    at_r = facts.get("domains_at_or_above_r") or []
    if at_r:
        return [d for d in _DOMAINS if d in at_r]
    z = {d: (analysis.domain_deviations or {}).get(d, {}).get("z", 0.0) for d in _DOMAINS}
    return [d for d in sorted(_DOMAINS, key=lambda d: -z[d]) if z[d] > 0][:2]


def _alert_item(alert: Alert, analysis: Analysis, assessment: Assessment, user: User) -> AlertListItem:
    sentences = (analysis.explanation or {}).get("sentences", [])
    return AlertListItem(
        alert_id=alert.id,
        patient_id=alert.patient_id,
        patient_display_name=user.display_name,
        assessment_id=assessment.id,
        observed_at=assessment.observed_at,
        created_at=alert.created_at,
        workflow_status=alert.status,
        lock_version=alert.lock_version,
        deviation_level=alert.deviation_level,
        affected_domains=_affected(analysis),
        summary=" ".join(sentences[:2]),
    )


def _alert_query() -> Select:
    return (
        select(Alert, Analysis, Assessment, User)
        .join(Analysis, Analysis.id == Alert.analysis_id)
        .join(Assessment, Assessment.id == Alert.assessment_id)
        .join(PatientProfile, PatientProfile.id == Alert.patient_id)
        .join(User, User.id == PatientProfile.user_id)
    )


def list_alerts(
    db: Session,
    doctor: User,
    *,
    limit: int,
    cursor: str | None,
    patient_id: uuid.UUID | None,
    workflow_status: str | None,
    deviation_level: str | None,
    include_resolved: bool,
    now: datetime,
) -> AlertPage:
    if include_resolved and workflow_status is not None:
        raise ApiError(400, "INVALID_QUERY", "Use either workflow_status or include_resolved, not both.")
    if patient_id is not None and get_assigned_patient(db, doctor, patient_id) is None:
        raise not_found()
    filters = {
        "patient_id": str(patient_id) if patient_id else None,
        "workflow_status": workflow_status,
        "deviation_level": deviation_level,
        "include_resolved": include_resolved,
    }
    ub, last = _page_state(cursor, "doctor.alerts", filters, doctor, now)
    query = _alert_query().where(Alert.patient_id.in_(assigned_patient_ids(doctor)), Alert.created_at <= ub)
    if patient_id is not None:
        query = query.where(Alert.patient_id == patient_id)
    if workflow_status is not None:
        query = query.where(Alert.status == workflow_status)
    elif not include_resolved:
        query = query.where(Alert.status.in_(UNRESOLVED))
    if deviation_level is not None:
        query = query.where(Alert.deviation_level == deviation_level)
    if last:
        query = query.where(
            and_(
                tuple_(Alert.created_at, Alert.id)
                < tuple_(literal(datetime.fromisoformat(last[0])), literal(uuid.UUID(last[1])))
            )
        )
    rows = db.execute(query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit + 1)).all()
    page, nxt = _next(
        rows,
        limit,
        "doctor.alerts",
        filters,
        doctor,
        ub,
        lambda r: [r[0].created_at.isoformat(), str(r[0].id)],
    )
    return AlertPage(items=[_alert_item(*r) for r in page], next_cursor=nxt)


def get_alert_scoped(db: Session, doctor: User, alert_id: uuid.UUID):
    row = db.execute(
        _alert_query().where(Alert.id == alert_id, Alert.patient_id.in_(assigned_patient_ids(doctor)))
    ).first()
    if row is None:
        raise not_found()
    return row


def _segment_key(a: Assessment) -> str | None:
    return a.quality_details.get("comparability", {}).get("key") or None


def _link_predecessors(records: list[InsightAssessment]) -> None:
    """Fill `previous_comparable_assessment_id` using only records inside this filtered range.

    A pair qualifies when both are eligible weekly representatives with an available composite, in
    consecutive canonical slots, under the same comparability segment and the same source. Gaps,
    ineligible interruptions and segment/source changes leave the predecessor null, so the UI
    cannot manufacture continuity across them.
    """
    last: dict[tuple[str, str], tuple[int, uuid.UUID]] = {}
    for record in records:  # already ordered observed_at ASC
        if not (
            record.is_representative
            and record.cognitive_index.observed_value is not None
            and record.comparison_segment_key
            and record.slot_index is not None
        ):
            continue
        group = (record.comparison_segment_key, record.source, record.cognitive_index.version)
        previous = last.get(group)
        if previous is not None and previous[0] == record.slot_index - 1:
            record.previous_comparable_assessment_id = previous[1]
        last[group] = (record.slot_index, record.assessment_id)


def insights(
    db: Session,
    doctor: User,
    patient_id: uuid.UUID,
    *,
    frm: datetime,
    to: datetime,
    source: str,
    now: datetime,
) -> InsightsResponse:
    """One complete bounded snapshot for the Insights panels (read-only; no pagination)."""
    if frm >= to:
        raise ApiError(400, "INVALID_QUERY", "`from` must be earlier than `to`.")
    if to - frm > MAX_INSIGHTS_WINDOW:
        raise ApiError(400, "INVALID_QUERY", "The date range must not exceed 366 days.", {"max_days": 366})
    if get_assigned_patient(db, doctor, patient_id) is None:
        raise not_found()
    profile = db.get(PatientProfile, patient_id)
    assert profile is not None

    query = (
        select(Assessment)
        .options(selectinload(Assessment.context))
        .where(
            Assessment.patient_id == patient_id,
            Assessment.observed_at >= frm,
            Assessment.observed_at < to,
        )
    )
    if source != "ALL":
        query = query.where(Assessment.source == source)
    rows = list(
        db.scalars(query.order_by(Assessment.observed_at, Assessment.id).limit(MAX_INSIGHTS_RECORDS + 1))
    )
    if len(rows) > MAX_INSIGHTS_RECORDS:
        # Never truncate or sample: a partial snapshot would produce misleading aggregates.
        raise ApiError(
            422,
            "INSIGHTS_RANGE_TOO_LARGE",
            f"This range has more than {MAX_INSIGHTS_RECORDS} assessments. Select a shorter range.",
            {"limit": MAX_INSIGHTS_RECORDS},
        )

    analyses, alerts, forecasts = _related(db, rows)
    records = [
        InsightAssessment(
            **_item_fields(a, analyses.get(a.id), alerts.get(a.id), forecasts.get(a.session_id)),
            protocol_version=a.protocol_version,
            scoring_version=a.scoring_version,
            context=_context_out(a.context),
            comparison_segment_key=_segment_key(a),
            slot_index=a.slot_index,
            is_representative=a.longitudinal_eligible,
            previous_comparable_assessment_id=None,
            linked_alert=_insight_alert(alerts.get(a.id)),
        )
        for a in rows
    ]
    _link_predecessors(records)
    return InsightsResponse(
        patient_id=patient_id,
        timezone=profile.timezone,
        generated_at=now,
        filters=InsightsFilters(**{"from": frm, "to": to, "source": source}),
        complete=True,
        assessment_count=len(records),
        score_metadata=CognitiveIndexMetadata(**cognitive_index.metadata()),
        records=records,
    )


def _insight_alert(alert: Alert | None) -> InsightAlert | None:
    if alert is None:
        return None
    return InsightAlert(
        alert_id=alert.id,
        created_at=alert.created_at,
        deviation_level=alert.deviation_level,
        workflow_status=alert.status,
    )


def alert_detail(db: Session, doctor: User, alert_id: uuid.UUID) -> AlertDetail:
    alert, analysis, assessment, user = get_alert_scoped(db, doctor, alert_id)
    item = _alert_item(alert, analysis, assessment, user)
    return AlertDetail(
        **item.model_dump(),
        assessment=_detail(db, assessment),
        events_path=f"{get_settings().API_PREFIX}/doctor/alerts/{alert.id}/events",
    )
