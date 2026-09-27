"""Doctor review events on alerts (guide 05 §13): append-only, versioned, idempotent.

Lock order: patient row, then the alert row. Replays are recognised by (alert_id, request_key)
before the stale-version check; the request hash includes the actor, so another doctor reusing a
key gets a conflict, never someone else's success. Reviewing never changes the assessment, scores,
analysis, deviation category or model identity.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import literal, select, tuple_
from sqlalchemy.orm import Session

from app.core import cursors
from app.core.errors import ApiError, not_found
from app.models import Alert, AlertAction, AlertEvent, AlertStatus, User
from app.schemas.doctor import (
    Actor,
    AlertEventOut,
    AlertEventPage,
    AlertEventRequest,
    AlertEventResponse,
    AlertRef,
)
from app.services.access import active_assignment
from app.services.assessment_sessions import lock_patient
from app.services.audit import audit
from app.services.doctor_views import get_alert_scoped

MAX_NOTE = 4000
_TRANSITIONS = {
    AlertAction.ACKNOWLEDGED: {AlertStatus.OPEN: AlertStatus.ACKNOWLEDGED},
    AlertAction.RESOLVED: {
        AlertStatus.OPEN: AlertStatus.RESOLVED,
        AlertStatus.ACKNOWLEDGED: AlertStatus.RESOLVED,
    },
}


def _event_out(event: AlertEvent, actor: User | None) -> AlertEventOut:
    return AlertEventOut(
        event_id=event.id,
        action=event.action,
        from_status=event.from_status,
        to_status=event.to_status,
        note=event.note,
        actor=Actor(user_id=actor.id, display_name=actor.display_name) if actor else None,
        created_at=event.created_at,
    )


def list_events(
    db: Session, doctor: User, alert_id: uuid.UUID, *, limit: int, cursor: str | None, now: datetime
) -> AlertEventPage:
    get_alert_scoped(db, doctor, alert_id)  # 404 unless currently assigned
    filters = {"alert_id": str(alert_id)}
    if cursor is None:
        ub, last = now, None
    else:
        state = cursors.decode(cursor, "doctor.alert_events", filters, doctor.id)
        ub, last = state.upper_bound, state.last
    query = (
        select(AlertEvent, User)
        .outerjoin(User, User.id == AlertEvent.actor_user_id)
        .where(AlertEvent.alert_id == alert_id, AlertEvent.created_at <= ub)
    )
    if last:
        query = query.where(
            tuple_(AlertEvent.created_at, AlertEvent.id)
            > tuple_(literal(datetime.fromisoformat(last[0])), literal(uuid.UUID(last[1])))
        )
    rows = db.execute(query.order_by(AlertEvent.created_at, AlertEvent.id).limit(limit + 1)).all()
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        e = rows[-1][0]
        nxt = cursors.encode(
            "doctor.alert_events", filters, doctor.id, ub, [e.created_at.isoformat(), str(e.id)]
        )
    # Historical actors stay attributed even if no longer assigned.
    return AlertEventPage(items=[_event_out(e, u) for e, u in rows], next_cursor=nxt)


def canonical_note(note: str | None) -> str | None:
    if note is None:
        return None
    trimmed = note.strip()  # outer whitespace only; internal content kept as typed
    return trimmed or None


def request_hash(actor_id: uuid.UUID, req: AlertEventRequest) -> str:
    body: dict[str, Any] = {
        "actor": str(actor_id),
        "action": req.action,
        "note": canonical_note(req.note),
        "expected_lock_version": req.expected_lock_version,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _current(alert: Alert) -> AlertRef:
    return AlertRef(alert_id=alert.id, workflow_status=alert.status, lock_version=alert.lock_version)


def record_event(
    db: Session, doctor: User, alert_id: uuid.UUID, req: AlertEventRequest, now: datetime
) -> tuple[AlertEventResponse, bool]:
    """Returns (response, created). Caller commits (and handles the unique-key race)."""
    alert, *_ = get_alert_scoped(db, doctor, alert_id)  # read-only preflight: 404 unless assigned
    lock_patient(db, alert.patient_id)
    # populate_existing: the preflight already loaded this alert into the identity map; without it the
    # locked re-select would keep that pre-lock copy, and a concurrent reviewer's committed change
    # (status, lock_version) would be silently overwritten (lost update found by the race test).
    alert = db.scalar(
        select(Alert).where(Alert.id == alert_id).with_for_update().execution_options(populate_existing=True)
    )
    if alert is None or active_assignment(db, doctor, alert.patient_id) is None:
        raise not_found()  # assignment rechecked inside the mutation transaction

    digest = request_hash(doctor.id, req)
    prior = db.scalar(
        select(AlertEvent).where(AlertEvent.alert_id == alert_id, AlertEvent.request_key == req.request_key)
    )
    if prior is not None:
        if prior.request_sha256 != digest:
            raise ApiError(
                409, "IDEMPOTENCY_CONFLICT", "This request key was already used for a different action."
            )
        return AlertEventResponse(
            event=_event_out(prior, doctor), alert=_current(alert), replayed=True
        ), False

    note = canonical_note(req.note)
    action = AlertAction(req.action)
    if action in (AlertAction.NOTE_ADDED, AlertAction.RESOLVED) and note is None:
        raise ApiError(
            422,
            "NOTE_REQUIRED",
            "A note is required for this action.",
            details={"fields": [{"path": "note", "type": "missing"}]},
        )
    if note is not None and len(note) > MAX_NOTE:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "The note is too long.",
            details={"fields": [{"path": "note", "type": "string_too_long"}]},
        )
    if req.expected_lock_version != alert.lock_version:
        raise ApiError(
            409,
            "STALE_ALERT_VERSION",
            "This alert changed since you loaded it. Refresh and try again.",
            details={"workflow_status": alert.status, "lock_version": alert.lock_version},
        )
    current = AlertStatus(alert.status)
    if action == AlertAction.NOTE_ADDED:
        target = current  # a note never reopens or moves the workflow
    else:
        target = _TRANSITIONS[action].get(current)
        if target is None:
            raise ApiError(
                409,
                "INVALID_ALERT_TRANSITION",
                f"An alert that is {current.value} cannot be {action.value.lower()}.",
                details={"workflow_status": current.value, "lock_version": alert.lock_version},
            )
    event = AlertEvent(
        alert_id=alert.id,
        actor_user_id=doctor.id,
        action=action.value,
        note=note,
        from_status=current.value,
        to_status=target.value,
        request_key=req.request_key,
        request_sha256=digest,
        created_at=now,
    )
    db.add(event)
    alert.status = target.value
    alert.lock_version += 1
    if target == AlertStatus.ACKNOWLEDGED and action == AlertAction.ACKNOWLEDGED:
        alert.acknowledged_at, alert.acknowledged_by = now, doctor.id
    if target == AlertStatus.RESOLVED and action == AlertAction.RESOLVED:
        alert.resolved_at, alert.resolved_by = now, doctor.id
    db.flush()
    audit(
        db,
        "ALERT_REVIEWED",
        "alert",
        alert.id,
        actor_user_id=doctor.id,
        patient_id=alert.patient_id,
        details={"action": action.value, "to_status": target.value, "lock_version": alert.lock_version},
    )
    return AlertEventResponse(event=_event_out(event, doctor), alert=_current(alert), replayed=False), True


def replay_after_race(
    db: Session, doctor: User, alert_id: uuid.UUID, req: AlertEventRequest
) -> AlertEventResponse:
    """After a unique (alert, request_key) violation: compare with the committed canonical event."""
    alert, *_ = get_alert_scoped(db, doctor, alert_id)
    prior = db.scalar(
        select(AlertEvent).where(AlertEvent.alert_id == alert_id, AlertEvent.request_key == req.request_key)
    )
    if prior is None:
        raise not_found()
    if prior.request_sha256 != request_hash(doctor.id, req):
        raise ApiError(
            409, "IDEMPOTENCY_CONFLICT", "This request key was already used for a different action."
        )
    return AlertEventResponse(event=_event_out(prior, doctor), alert=_current(alert), replayed=True)
