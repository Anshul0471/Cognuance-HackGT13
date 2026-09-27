"""Patient assessment API against PostgreSQL (rolled back per test): ownership, frozen protocol,
persistence, idempotency, expiry, and weekly scheduling (guide 02 §16)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Assessment, AssessmentSession, AuditEvent, ContextCheckin, PatientProfile, User
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION
from app.services.schedule import comparability_key
from tests.factories import build_payload

ELEANOR = "eleanor.park@demo.test"
IRIS = "iris.novak@demo.test"
RIVERA = "dr.rivera@demo.test"
BASE = "/api/v1/patient"


def start_body(**overrides):
    body = {
        "start_key": str(uuid.uuid4()),
        "input_mode": "keyboard",
        "device_changed": False,
        "navigation_assistance": False,
        "allow_unscheduled": False,
    }
    return {**body, **overrides}


@pytest.fixture
def eleanor(seeded, login_as):
    return login_as(ELEANOR)


def start(client, headers, **overrides):
    return client.post(f"{BASE}/assessment-sessions", json=start_body(**overrides), headers=headers)


def full_protocol(db, session_id):
    return db.get(AssessmentSession, uuid.UUID(session_id)).protocol_snapshot


def submit(client, headers, db, session_id, **payload_kwargs):
    payload = build_payload(full_protocol(db, session_id), **payload_kwargs)
    response = client.post(
        f"{BASE}/assessment-sessions/{session_id}/submissions", json=payload, headers=headers
    )
    return response, payload


def patient_id(db, email):
    return db.scalar(select(PatientProfile.id).join(User).where(User.email == email))


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def insert_history(db, email, anchor, slots, input_mode="keyboard"):
    """Controlled-backend import of SYNTHETIC_HISTORY representatives (what guide 03 tooling will do)."""
    pid = patient_id(db, email)
    key = comparability_key(PROTOCOL_VERSION, SCORING_VERSION, input_mode, 0)
    for slot in slots:
        target = anchor + timedelta(days=7 * slot)
        session = AssessmentSession(
            patient_id=pid,
            start_key=uuid.uuid4(),
            status="SUBMITTED",
            source="SYNTHETIC_HISTORY",
            protocol_version=PROTOCOL_VERSION,
            scoring_version=SCORING_VERSION,
            input_mode=input_mode,
            schedule_purpose="SCHEDULED",
            slot_index=slot,
            target_at=target,
            forecast_state="BUILDING_BASELINE",
            forecast_reasons=["BUILDING_BASELINE"],
            history_cutoff_at=target,
            protocol_snapshot={"schedule": {"anchor_at": anchor.isoformat()}},
            started_at=target,
            expires_at=target + timedelta(minutes=20),
            ended_at=target + timedelta(minutes=10),
        )
        db.add(session)
        db.flush()
        db.add(
            Assessment(
                session_id=session.id,
                patient_id=pid,
                submission_key=uuid.uuid4(),
                payload_sha256="0" * 64,
                source="SYNTHETIC_HISTORY",
                protocol_version=PROTOCOL_VERSION,
                scoring_version=SCORING_VERSION,
                raw_responses={},
                memory_score=83.333,
                attention_score=90,
                reaction_time_ms=410,
                quality="VALID",
                quality_details={
                    "input_mode": input_mode,
                    "comparability": {"epoch": 0, "key": key, "flags": []},
                    "tasks": {},
                },
                longitudinal_eligible=True,
                schedule_purpose="SCHEDULED",
                slot_index=slot,
                target_at=target,
                observed_at=target + timedelta(minutes=10),
                available_at=target + timedelta(minutes=10),
                analysis_state="BUILDING_BASELINE",
                analysis_reasons=["BUILDING_BASELINE"],
                processing_status="ANALYZED",
            )
        )
    db.commit()  # a savepoint in tests: survives a route's rollback of its own failed request


# --- session start ------------------------------------------------------------------------------


def test_start_freezes_protocol_and_is_idempotent(client, eleanor, db_session):
    body = start_body()
    first = client.post(f"{BASE}/assessment-sessions", json=body, headers=eleanor)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["schedule"]["purpose"] == "SCHEDULED" and data["replayed"] is False
    assert data["started_at"].endswith("Z") and data["schedule"]["anchor_at"].endswith("Z")
    assert data["protocol"]["attention"]["trials"][0]["trial_id"] == "att-01"
    assert data["protocol"]["memory"]["words"] == ["apple", "chair", "river", "candle", "garden", "spoon"]
    assert len(data["protocol"]["attention"]["trials"]) == 30
    assert "is_target" not in data["protocol"]["attention"]["trials"][0]
    assert "forecast" not in first.text.lower()

    replay = client.post(f"{BASE}/assessment-sessions", json=body, headers=eleanor)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["session_id"] == data["session_id"]
    assert replay.json()["protocol"] == data["protocol"]  # never regenerated

    changed = client.post(
        f"{BASE}/assessment-sessions", json={**body, "input_mode": "pointer"}, headers=eleanor
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    other = start(client, eleanor)
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "ACTIVE_SESSION_EXISTS"
    assert other.json()["error"]["details"]["session_id"] == data["session_id"]

    session = db_session.get(AssessmentSession, uuid.UUID(data["session_id"]))
    assert session.source == "LIVE_DEMO"
    assert session.forecast_state == "BUILDING_BASELINE"


def test_start_rejects_client_supplied_extras(client, eleanor):
    response = client.post(
        f"{BASE}/assessment-sessions", json={**start_body(), "source": "SCENARIO_REPLAY"}, headers=eleanor
    )
    assert response.status_code == 422


def test_doctor_cannot_use_patient_endpoints(client, seeded, login_as):
    rivera = login_as(RIVERA)
    assert client.get(f"{BASE}/assessment-status", headers=rivera).status_code == 403
    assert start(client, rivera).status_code == 403


# --- submission ---------------------------------------------------------------------------------


def test_valid_submission_scored_on_server_and_persisted(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    response, _ = submit(client, eleanor, db_session, session_id)
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert set(receipt) == {
        "assessment_id",
        "session_id",
        "received_at",
        "saved",
        "quality",
        "analysis",
        "replayed",
    }
    assert receipt["saved"] is True and receipt["replayed"] is False
    assert receipt["quality"] == {
        "status": "VALID",
        "reason_codes": [],
        "message": "Your check-in was saved.",
    }
    assert receipt["analysis"]["availability"] == "BUILDING_BASELINE"
    assert receipt["analysis"]["reason_codes"] == ["BUILDING_BASELINE"]
    assert response.headers["location"] == f"/api/v1/patient/assessments/{receipt['assessment_id']}/receipt"
    assert response.headers["cache-control"] == "no-store"
    assert "apple" not in response.text  # no answer key in receipts

    a = db_session.get(Assessment, uuid.UUID(receipt["assessment_id"]))
    assert (str(a.memory_score), str(a.attention_score), str(a.reaction_time_ms)) == (
        "100.000",
        "100.000",
        "390.000",
    )
    assert a.longitudinal_eligible is True
    assert a.source == "LIVE_DEMO"
    assert a.available_at == a.observed_at
    assert a.raw_responses["memory"]["recall_entries"][0] == "apple"
    assert a.context.sleep_hours == pytest.approx(7.25) and a.context.mood_score == 7
    assert a.context.medication_change == "NO" and a.processing_status == "ANALYZED"
    assert a.analysis_state == "BUILDING_BASELINE"
    replay_start = client.post(
        f"{BASE}/assessment-sessions",
        json={**start_body(), "start_key": str(db_session.get(AssessmentSession, a.session_id).start_key)},
        headers=eleanor,
    )
    assert replay_start.status_code == 200 and replay_start.json()["status"] == "SUBMITTED"
    assert replay_start.json()["protocol"] is None  # no task-launch material for a finished session
    recovery = client.get(f"{BASE}/assessment-sessions/{session_id}", headers=eleanor).json()
    assert recovery["assessment_id"] == receipt["assessment_id"] and recovery["receipt_path"].endswith(
        "/receipt"
    )
    assert "words" not in str(recovery) and "recall_entries" not in str(recovery)
    assert db_session.get(AssessmentSession, a.session_id).status == "SUBMITTED"


def test_same_key_and_body_is_idempotent(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    first, payload = submit(client, eleanor, db_session, session_id)
    url = f"{BASE}/assessment-sessions/{session_id}/submissions"
    second = client.post(url, json=payload, headers=eleanor)
    assert second.status_code == 200 and second.json()["replayed"] is True
    assert second.json()["assessment_id"] == first.json()["assessment_id"]
    assert second.json()["received_at"] == first.json()["received_at"]
    assert count(db_session, Assessment) == 1 and count(db_session, ContextCheckin) == 1

    payload["context"]["mood_score"] = 2
    changed = client.post(url, json=payload, headers=eleanor)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    new_key = {**payload, "submission_key": str(uuid.uuid4())}
    conflict = client.post(url, json=new_key, headers=eleanor)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SESSION_ALREADY_SUBMITTED"


def test_other_patients_session_and_receipt_are_404(client, eleanor, login_as, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    receipt_id = submit(client, eleanor, db_session, session_id)[0].json()["assessment_id"]
    iris = login_as(IRIS)
    assert client.get(f"{BASE}/assessment-sessions/{session_id}", headers=iris).status_code == 404
    assert client.post(f"{BASE}/assessment-sessions/{session_id}/abandon", headers=iris).status_code == 404
    other_submit, _ = submit(client, iris, db_session, session_id)
    assert other_submit.status_code == 404
    response = client.get(f"{BASE}/assessments/{receipt_id}/receipt", headers=iris)
    assert response.status_code == 404
    assert "score" not in response.text


def test_first_submission_after_expiry_is_409_without_backdating(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    session = db_session.get(AssessmentSession, uuid.UUID(session_id))
    session.started_at -= timedelta(minutes=30)
    session.expires_at -= timedelta(minutes=30)
    db_session.flush()
    response, _ = submit(client, eleanor, db_session, session_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    assert count(db_session, Assessment) == 0
    db_session.refresh(session)
    assert session.status == "EXPIRED"


def test_accepted_receipt_replay_after_expiry(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    first, payload = submit(client, eleanor, db_session, session_id)
    session = db_session.get(AssessmentSession, uuid.UUID(session_id))
    session.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.started_at = session.expires_at - timedelta(minutes=20)
    db_session.flush()
    replay = client.post(
        f"{BASE}/assessment-sessions/{session_id}/submissions", json=payload, headers=eleanor
    )
    assert replay.status_code == 200
    assert replay.json()["assessment_id"] == first.json()["assessment_id"]
    assert count(db_session, Assessment) == 1


def test_structural_errors_are_rejected_not_stored(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    payload = build_payload(full_protocol(db_session, session_id))
    url = f"{BASE}/assessment-sessions/{session_id}/submissions"

    bad_id = {
        **payload,
        "attention": {**payload["attention"], "trials": [dict(payload["attention"]["trials"][0])]},
    }
    bad_id["attention"]["trials"][0]["trial_id"] = "att-99"
    assert client.post(url, json=bad_id, headers=eleanor).status_code == 422

    assert (
        client.post(url, json={**payload, "protocol_version": "forged_v9"}, headers=eleanor).status_code
        == 422
    )
    extra = client.post(url, json={**payload, "memory_score": 100}, headers=eleanor)
    assert extra.status_code == 422 and extra.json()["error"]["code"] == "VALIDATION_ERROR"
    assert count(db_session, Assessment) == 0


def test_oversized_body_is_413(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    payload = build_payload(full_protocol(db_session, session_id))
    payload["padding"] = "x" * (257 * 1024)
    response = client.post(
        f"{BASE}/assessment-sessions/{session_id}/submissions", json=payload, headers=eleanor
    )
    assert response.status_code == 413 and response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert count(db_session, Assessment) == 0


def test_low_quality_saved_with_insufficient_data_and_frozen_forecast_untouched(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    response, _ = submit(
        client,
        eleanor,
        db_session,
        session_id,
        answer_assistance={"memory": "PROVIDED", "attention": "NONE", "reaction": "NONE"},
    )
    receipt = response.json()
    assert receipt["quality"]["status"] == "LOW"
    assert receipt["analysis"]["availability"] == "INSUFFICIENT_DATA"
    assert receipt["analysis"]["reason_codes"][0] == "LOW_QUALITY_TARGET"
    assert "ANSWER_ASSISTANCE" in receipt["quality"]["reason_codes"]
    session = db_session.get(AssessmentSession, uuid.UUID(session_id))
    assert session.forecast_state == "BUILDING_BASELINE"
    assert db_session.get(Assessment, uuid.UUID(receipt["assessment_id"])).longitudinal_eligible is False


def test_save_partial_is_incomplete(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    response, _ = submit(
        client,
        eleanor,
        db_session,
        session_id,
        attention_trials=12,
        attention_completion="STOPPED",
        reaction=[],
        reaction_completion="SKIPPED",
    )
    receipt = response.json()
    assert response.status_code == 201
    assert receipt["quality"]["status"] == "INCOMPLETE"
    assert receipt["quality"]["reason_codes"] == ["ATTENTION_STOPPED", "REACTION_SKIPPED"]
    assert receipt["quality"]["message"].startswith("Your check-in was saved, but not every activity")
    assert receipt["analysis"] == {
        "availability": "INSUFFICIENT_DATA",
        "reason_codes": ["INCOMPLETE_TARGET", "BUILDING_BASELINE"],
        "message": "There is not enough reliable task data for a comparison. Not every activity was "
        "finished, so this check-in can't be compared with others.",
    }
    a = db_session.get(Assessment, uuid.UUID(receipt["assessment_id"]))
    assert a.memory_score is not None and a.attention_score is None and a.reaction_time_ms is None


def test_missing_context_stored_as_nulls_with_reasons(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    context = {
        "sleep_hours": 0,
        "mood_score": None,
        "medication_change": None,
        "reported_by": "CAREGIVER_ASSISTED",
        "missing_fields": {"medication_change": "UNKNOWN"},  # mood's reason omitted → SKIPPED
    }
    receipt = submit(client, eleanor, db_session, session_id, context=context)[0].json()
    assert receipt["quality"]["status"] == "VALID"
    ctx = db_session.get(Assessment, uuid.UUID(receipt["assessment_id"])).context
    assert ctx.sleep_hours == 0 and ctx.mood_score is None and ctx.medication_change is None
    assert ctx.reported_by == "CAREGIVER_ASSISTED"
    assert ctx.missing_fields == [
        {"field": "mood_score", "reason": "SKIPPED"},
        {"field": "medication_change", "reason": "UNKNOWN"},
    ]


# --- abandon ------------------------------------------------------------------------------------


def test_abandon_lifecycle(client, eleanor, db_session):
    session_id = start(client, eleanor).json()["session_id"]
    url = f"{BASE}/assessment-sessions/{session_id}/abandon"
    first = client.post(url, headers=eleanor)
    assert first.status_code == 204 and first.content == b""
    assert client.post(url, headers=eleanor).status_code == 204  # no-op repeat
    events = db_session.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "SESSION_ABANDONED", AuditEvent.entity_id == uuid.UUID(session_id)
        )
    ).all()
    assert len(events) == 1  # the repeat emits no second event
    assert (
        client.get(f"{BASE}/assessment-sessions/{session_id}", headers=eleanor).json()["status"]
        == "ABANDONED"
    )
    late = submit(client, eleanor, db_session, session_id)[0]
    assert late.status_code == 409 and late.json()["error"]["code"] == "SESSION_ABANDONED"

    submitted = start(client, eleanor).json()["session_id"]
    submit(client, eleanor, db_session, submitted)
    after = client.post(f"{BASE}/assessment-sessions/{submitted}/abandon", headers=eleanor)
    assert after.status_code == 409 and after.json()["error"]["code"] == "SESSION_ALREADY_SUBMITTED"


# --- weekly schedule ----------------------------------------------------------------------------


def test_same_day_extra_attempt_requires_opt_in_and_is_not_history(client, eleanor, db_session):
    first = start(client, eleanor).json()["session_id"]
    submit(client, eleanor, db_session, first)

    blocked = start(client, eleanor)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SLOT_COMPLETED"

    extra = start(client, eleanor, allow_unscheduled=True)
    assert extra.status_code == 201
    assert extra.json()["schedule"]["purpose"] == "EXTRA_ATTEMPT"
    assert extra.json()["schedule"]["longitudinal_eligible"] is False
    assert extra.json()["protocol"]["memory"]["word_set_id"] == "B"
    receipt = submit(client, eleanor, db_session, extra.json()["session_id"])[0].json()
    assert receipt["quality"]["status"] == "VALID"
    assert receipt["analysis"]["availability"] == "INSUFFICIENT_DATA"
    assert receipt["analysis"]["reason_codes"][0] == "EXTRA_ATTEMPT"
    assert db_session.get(Assessment, uuid.UUID(receipt["assessment_id"])).longitudinal_eligible is False


def test_retake_after_low_then_limit(client, eleanor, db_session):
    first = start(client, eleanor).json()
    submit(
        client,
        eleanor,
        db_session,
        first["session_id"],
        answer_assistance={"memory": "UNKNOWN", "attention": "NONE", "reaction": "NONE"},
    )

    retake = start(client, eleanor).json()
    assert retake["schedule"]["purpose"] == "RETAKE_AFTER_UNRELIABLE"
    assert retake["protocol"]["memory"]["word_set_id"] != first["protocol"]["memory"]["word_set_id"]
    receipt = submit(client, eleanor, db_session, retake["session_id"])[0].json()
    assert db_session.get(Assessment, uuid.UUID(receipt["assessment_id"])).longitudinal_eligible is True


def test_two_abandoned_starts_exhaust_the_slot(client, eleanor):
    for _ in range(2):
        sid = start(client, eleanor).json()["session_id"]
        client.post(f"{BASE}/assessment-sessions/{sid}/abandon", headers=eleanor)
    third = start(client, eleanor)
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "ATTEMPT_LIMIT_REACHED"


def test_off_schedule_requires_opt_in(client, eleanor, db_session):
    anchor = datetime.now(UTC) - timedelta(days=10, hours=12)  # midway between slots 1 and 2
    insert_history(db_session, ELEANOR, anchor, [0, 1])
    blocked = start(client, eleanor)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "OUTSIDE_SCHEDULE_WINDOW"
    assert blocked.json()["error"]["details"]["next_target_at"]
    off = start(client, eleanor, allow_unscheduled=True).json()
    assert off["schedule"]["purpose"] == "OFF_SCHEDULE"
    receipt = submit(client, eleanor, db_session, off["session_id"])[0].json()
    assert receipt["analysis"]["availability"] == "INSUFFICIENT_DATA"
    assert receipt["analysis"]["reason_codes"][0] == "OFF_SCHEDULE"


def test_history_gap_is_not_compressed(client, eleanor, db_session):
    anchor = datetime.now(UTC) - timedelta(days=56)  # now is slot 8's target
    insert_history(db_session, ELEANOR, anchor, [0, 1, 2, 3, 4, 5, 6])  # seven reps, slot 7 missing
    session = start(client, eleanor).json()
    assert session["schedule"]["slot_index"] == 8
    frozen = db_session.get(AssessmentSession, uuid.UUID(session["session_id"]))
    assert frozen.forecast_state == "INSUFFICIENT_DATA"
    assert frozen.forecast_reasons == ["HISTORY_GAP"]


def test_six_consecutive_reps_reach_model_unavailable_not_normal(client, eleanor, db_session):
    anchor = datetime.now(UTC) - timedelta(days=56)
    insert_history(db_session, ELEANOR, anchor, [2, 3, 4, 5, 6, 7])
    session = start(client, eleanor).json()
    frozen = db_session.get(AssessmentSession, uuid.UUID(session["session_id"]))
    assert frozen.forecast_state == "MODEL_UNAVAILABLE"
    receipt = submit(client, eleanor, db_session, session["session_id"])[0].json()
    assert receipt["analysis"]["availability"] == "MODEL_UNAVAILABLE"
    assert "NORMAL" not in str(receipt)


@pytest.mark.parametrize("change", [{"input_mode": "pointer"}, {"device_changed": True}])
def test_comparability_change_blocks_comparison(client, eleanor, db_session, change):
    anchor = datetime.now(UTC) - timedelta(days=56)
    insert_history(db_session, ELEANOR, anchor, [2, 3, 4, 5, 6, 7])
    session = start(client, eleanor, **change).json()
    frozen = db_session.get(AssessmentSession, uuid.UUID(session["session_id"]))
    assert frozen.forecast_state == "INSUFFICIENT_DATA"
    assert "COMPARABILITY_CHANGE" in frozen.forecast_reasons
    receipt = submit(client, eleanor, db_session, session["session_id"], input_mode=session["input_mode"])[
        0
    ].json()
    assert receipt["analysis"]["availability"] == "INSUFFICIENT_DATA"


# --- status -------------------------------------------------------------------------------------


def test_assessment_status_flow(client, eleanor, db_session):
    status = client.get(f"{BASE}/assessment-status", headers=eleanor).json()
    assert status["patient_id"] == str(patient_id(db_session, ELEANOR))
    assert status["server_time"].endswith("Z")
    assert status["current_session"] is None and status["last_receipt"] is None
    assert status["schedule"] == {
        "anchor_at": None,
        "next_target_at": None,
        "window_opens_at": None,
        "window_closes_at": None,
        "scheduled_start_allowed": True,
        "reason_codes": ["FIRST_CHECKIN"],
    }
    assert count(db_session, AssessmentSession) == 0  # GET never invents an anchor

    session_id = start(client, eleanor).json()["session_id"]
    in_progress = client.get(f"{BASE}/assessment-status", headers=eleanor).json()
    assert in_progress["current_session"]["session_id"] == session_id
    assert in_progress["schedule"]["scheduled_start_allowed"] is False
    assert in_progress["schedule"]["reason_codes"][0] == "ACTIVE_SESSION_EXISTS"

    submit(client, eleanor, db_session, session_id)
    done = client.get(f"{BASE}/assessment-status", headers=eleanor).json()
    assert done["current_session"] is None
    assert done["last_receipt"]["quality"]["status"] == "VALID"
    assert done["schedule"]["scheduled_start_allowed"] is False
    assert done["schedule"]["reason_codes"] == ["SLOT_COMPLETED"]
    anchor = datetime.fromisoformat(done["schedule"]["anchor_at"])
    assert datetime.fromisoformat(done["schedule"]["next_target_at"]) - anchor == timedelta(days=7)
