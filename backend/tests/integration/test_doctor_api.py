"""Doctor API against PostgreSQL (guide 05 §11–§14, §18 checks 7–13). Rolled back per test."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.ml.models import registry
from app.models import Alert, DoctorPatientAssignment, PatientProfile, User
from tests.integration.test_anomaly_workflow import model_env  # noqa: F401  (fixture)
from tests.model_fixtures import checkin, make_bundle, register_bundle, week

ANCHOR = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
BASE = {"words": 4, "attention_misses": 0, "rt_ms": 390.0}
RIVERA, OKAFOR = "dr.rivera@demo.test", "dr.okafor@demo.test"
ELEANOR, IRIS = "eleanor.park@demo.test", "iris.novak@demo.test"
D = "/api/v1/doctor"


def pid(db, email):
    return db.scalar(select(PatientProfile.id).join(User).where(User.email == email))


def user(db, email):
    return db.scalar(select(User).where(User.email == email))


@pytest.fixture
def world(seeded, model_env):  # noqa: F811
    """Eleanor: 6 normal weeks, a NORMAL week 6, a REVIEW alert in week 7, a LOW week-8 retake pair."""
    db = seeded
    root, _ = model_env
    register_bundle(db, root, make_bundle(root))
    registry.activate(db, "test-model", "test-policy", root)
    db.commit()
    e = pid(db, ELEANOR)
    for k in range(7):
        checkin(db, e, week(ANCHOR, k), **BASE)
    _, a7 = checkin(db, e, week(ANCHOR, 7), words=2, rt_ms=390.0)  # memory −33.3 → z 3.33 (REVIEW)
    _, low = checkin(
        db,
        e,
        week(ANCHOR, 8),
        answer_assistance={"memory": "PROVIDED", "attention": "NONE", "reaction": "NONE"},
        **BASE,
    )
    alert = db.scalar(select(Alert).where(Alert.assessment_id == a7.id))
    assert alert is not None
    return {"db": db, "eleanor": e, "alert": alert, "a7": a7, "low": low}


def review(client, headers, alert_id, action, version, note=None, key=None):
    body = {
        "request_key": key or str(uuid.uuid4()),
        "expected_lock_version": version,
        "action": action,
        "note": note,
    }
    return client.post(f"{D}/alerts/{alert_id}/events", json=body, headers=headers)


# --- scope ---------------------------------------------------------------------------------------


def test_patient_list_scope_pagination_and_cursor_integrity(client, seeded, login_as):
    rivera, okafor = login_as(RIVERA), login_as(OKAFOR)
    names = [p["display_name"] for p in client.get(f"{D}/patients?limit=100", headers=rivera).json()["items"]]
    assert sorted(names) == ["Eleanor Park", "Henry Lin", "Rosa Delgado", "Walter Hughes"]
    assert [p["display_name"] for p in client.get(f"{D}/patients", headers=okafor).json()["items"]] == [
        "Iris Novak"
    ]
    assert client.get(f"{D}/patients", headers=login_as(ELEANOR)).status_code == 403

    first = client.get(f"{D}/patients?limit=3", headers=rivera).json()
    assert len(first["items"]) == 3 and first["next_cursor"]
    second = client.get(f"{D}/patients?limit=3&cursor={first['next_cursor']}", headers=rivera).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    seen = [p["patient_id"] for p in first["items"] + second["items"]]
    assert len(set(seen)) == 4
    item = first["items"][0]
    assert set(item) == {
        "patient_id",
        "display_name",
        "is_demo",
        "account_active",
        "latest_assessment_at",
        "latest_analysis_availability",
        "latest_deviation_level",
        "unresolved_alert_count",
    }
    assert item["latest_assessment_at"] is None and item["is_demo"] is True

    cursor = first["next_cursor"]
    tampered = cursor[:-2] + ("AA" if not cursor.endswith("AA") else "BB")
    for bad in (tampered, "garbage", cursor):
        url = f"{D}/patients?limit=3&cursor={bad}" + ("&q=a" if bad == cursor else "")  # filter change
        response = client.get(url, headers=rivera)
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_CURSOR"
        assert response.json()["error"]["details"] == {}
    other_doctor = client.get(f"{D}/patients?limit=3&cursor={cursor}", headers=okafor)
    assert other_doctor.status_code == 400  # cursors are bound to their caller

    assert [
        p["display_name"] for p in client.get(f"{D}/patients?q=rosa", headers=rivera).json()["items"]
    ] == ["Rosa Delgado"]
    assert client.get(f"{D}/patients?q=" + "x" * 101, headers=rivera).status_code == 422


def test_deactivated_login_stays_visible_but_ended_assignment_removes_access(client, seeded, login_as):
    rivera = login_as(RIVERA)
    e = pid(seeded, ELEANOR)
    user(seeded, ELEANOR).is_active = False
    seeded.commit()
    items = client.get(f"{D}/patients", headers=rivera).json()["items"]
    assert next(p for p in items if p["patient_id"] == str(e))["account_active"] is False
    assert client.get(f"{D}/patients/{e}", headers=rivera).json()["patient"]["account_active"] is False

    assignment = seeded.scalar(select(DoctorPatientAssignment).where(DoctorPatientAssignment.patient_id == e))
    assignment.ended_at = datetime.now(UTC)
    seeded.commit()
    assert client.get(f"{D}/patients/{e}", headers=rivera).status_code == 404
    assert client.get(f"{D}/patients/{e}/timeline", headers=rivera).status_code == 404
    assert str(e) not in client.get(f"{D}/patients", headers=rivera).text


def test_unknown_and_foreign_ids_are_404(client, seeded, login_as):
    rivera = login_as(RIVERA)
    assert client.get(f"{D}/patients/{pid(seeded, IRIS)}", headers=rivera).status_code == 404
    assert client.get(f"{D}/patients/{uuid.uuid4()}", headers=rivera).status_code == 404
    assert client.get(f"{D}/patients/not-a-uuid", headers=rivera).status_code == 422
    assert client.get(f"{D}/alerts/{uuid.uuid4()}", headers=rivera).status_code == 404
    assert client.get(f"{D}/alerts?patient_id={pid(seeded, IRIS)}", headers=rivera).status_code == 404


# --- timeline / detail / summary ------------------------------------------------------------------


def test_summary_timeline_and_detail(client, world, login_as):
    db, e = world["db"], world["eleanor"]
    rivera = login_as(RIVERA)
    summary = client.get(f"{D}/summary", headers=rivera).json()
    assert summary["assigned_patient_count"] == 4 and summary["open_alert_count"] == 1
    assert summary["patients_with_open_alerts"] == 1 and summary["acknowledged_alert_count"] == 0
    assert summary["pending_analysis_count"] == 0 and summary["analysis_error_count"] == 0
    assert summary["generated_at"].endswith("Z")
    assert client.get(f"{D}/summary", headers=login_as(OKAFOR)).json()["open_alert_count"] == 0

    page = client.get(f"{D}/patients/{e}/timeline?limit=4", headers=rivera).json()
    assert len(page["items"]) == 4 and page["next_cursor"]
    rest = client.get(
        f"{D}/patients/{e}/timeline?limit=50&cursor={page['next_cursor']}", headers=rivera
    ).json()
    items = page["items"] + rest["items"]
    assert len(items) == 9 and rest["next_cursor"] is None  # every observation, incl. LOW
    observed = [i["observed_at"] for i in items]
    assert observed == sorted(observed, reverse=True)
    low = next(i for i in items if i["assessment_id"] == str(world["low"].id))
    assert low["quality_status"] == "LOW" and low["longitudinal_eligible"] is False
    assert (
        low["analysis"]["availability"] == "INSUFFICIENT_DATA" and low["analysis"]["deviation_level"] is None
    )
    flagged = next(i for i in items if i["assessment_id"] == str(world["a7"].id))
    assert (
        flagged["analysis"]["deviation_level"] == "REVIEW" and flagged["alert"]["workflow_status"] == "OPEN"
    )
    assert (
        flagged["forecast"]["model_kind"] == "LAST_VALUE"
        and flagged["forecast"]["predicted_memory_score"] == 66.667
    )
    assert flagged["scores"]["memory_score"] == 33.333 and isinstance(
        flagged["scores"]["reaction_time_ms"], float
    )
    early = items[-1]
    assert early["forecast"] is None and early["analysis"]["availability"] == "BUILDING_BASELINE"

    frm, to = week(ANCHOR, 7).isoformat(), week(ANCHOR, 8).isoformat()
    window = client.get(f"{D}/patients/{e}/timeline", params={"from": frm, "to": to}, headers=rivera).json()
    assert [i["assessment_id"] for i in window["items"]] == [str(world["a7"].id)]
    bad = client.get(f"{D}/patients/{e}/timeline", params={"from": to, "to": frm}, headers=rivera)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_QUERY"

    detail = client.get(f"{D}/patients/{e}/assessments/{world['a7'].id}", headers=rivera)
    body = detail.json()
    assert detail.status_code == 200
    assert body["quality_details"]["tasks"]["memory"]["counters"] == {
        "correct": 2,
        "incorrect": 0,
        "duplicates": 0,
    }
    assert body["context"] == {
        "sleep_hours": 7.25,
        "mood_score": 7,
        "medication_change": False,
        "reported_by": "PATIENT",
        "missing_fields": {},
    }
    ad = body["analysis_details"]
    assert ad["domain_deviations"]["memory"]["z"] == pytest.approx(3.3334)
    assert ad["model_kind"] == "LAST_VALUE" and ad["policy_version"] == "test-policy"
    assert (
        ad["aggregate_method"] == "mean_top_two_v1"
        and "Memory was 33.3 points below" in ad["explanation"]["summary"]
    )
    assert (
        "apple" not in detail.text
        and "recall_entries" not in detail.text
        and "payload_sha256" not in detail.text
    )
    # Someone else's assessment under this patient path, and this assessment under another path → 404.
    assert (
        client.get(f"{D}/patients/{pid(db, IRIS)}/assessments/{world['a7'].id}", headers=rivera).status_code
        == 404
    )
    walter = pid(db, "walter.hughes@demo.test")
    assert (
        client.get(f"{D}/patients/{walter}/assessments/{world['a7'].id}", headers=rivera).status_code == 404
    )


# --- alerts and review --------------------------------------------------------------------------


def test_alert_queue_filters(client, world, login_as):
    rivera = login_as(RIVERA)
    queue = client.get(f"{D}/alerts", headers=rivera).json()
    assert len(queue["items"]) == 1
    item = queue["items"][0]
    assert item["deviation_level"] == "REVIEW" and item["affected_domains"] == ["memory"]
    assert item["patient_display_name"] == "Eleanor Park" and item["lock_version"] == 1
    assert "Memory was 33.3 points below" in item["summary"]
    assert client.get(f"{D}/alerts", headers=login_as(OKAFOR)).json()["items"] == []
    assert client.get(f"{D}/alerts?workflow_status=RESOLVED", headers=rivera).json()["items"] == []
    both = client.get(f"{D}/alerts?workflow_status=OPEN&include_resolved=true", headers=rivera)
    assert both.status_code == 400 and both.json()["error"]["code"] == "INVALID_QUERY"
    detail = client.get(f"{D}/alerts/{item['alert_id']}", headers=rivera).json()
    assert detail["assessment"]["assessment_id"] == item["assessment_id"]
    assert detail["events_path"] == f"/api/v1/doctor/alerts/{item['alert_id']}/events"


def test_review_idempotency_concurrency_and_transitions(client, world, login_as):
    db, e, alert = world["db"], world["eleanor"], world["alert"]
    rivera = login_as(RIVERA)
    # A second assigned doctor for the same patient.
    db.add(DoctorPatientAssignment(doctor_user_id=user(db, OKAFOR).id, patient_id=e))
    db.commit()
    okafor = login_as(OKAFOR)

    key = str(uuid.uuid4())
    ack = review(client, rivera, alert.id, "ACKNOWLEDGED", 1, key=key)
    assert ack.status_code == 200, ack.text
    body = ack.json()
    assert body["replayed"] is False and body["alert"] == {
        "alert_id": str(alert.id),
        "workflow_status": "ACKNOWLEDGED",
        "lock_version": 2,
    }
    assert (
        body["event"]["from_status"] == "OPEN" and body["event"]["actor"]["display_name"] == "Dr. Ana Rivera"
    )

    again = review(client, rivera, alert.id, "ACKNOWLEDGED", 1, key=key)  # same key, same payload
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["event"]["event_id"] == body["event"]["event_id"]
    changed = review(client, rivera, alert.id, "ACKNOWLEDGED", 1, note="different", key=key)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    stolen = review(client, okafor, alert.id, "ACKNOWLEDGED", 1, key=key)  # other actor, same key
    assert stolen.status_code == 409 and stolen.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    stale = review(client, okafor, alert.id, "RESOLVED", 1, note="done")  # loaded before the ack
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_ALERT_VERSION"
    assert stale.json()["error"]["details"] == {"workflow_status": "ACKNOWLEDGED", "lock_version": 2}
    twice = review(client, rivera, alert.id, "ACKNOWLEDGED", 2)
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "INVALID_ALERT_TRANSITION"
    empty = review(client, rivera, alert.id, "NOTE_ADDED", 2, note="   ")
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "NOTE_REQUIRED"
    assert review(client, rivera, alert.id, "NOTE_ADDED", 2, note="x" * 4001).status_code == 422

    note = review(client, okafor, alert.id, "NOTE_ADDED", 2, note="  Called the caregiver.\nWill recheck.  ")
    assert note.status_code == 200 and note.json()["alert"]["lock_version"] == 3
    assert note.json()["event"]["note"] == "Called the caregiver.\nWill recheck."  # outer trim only
    resolved = review(client, rivera, alert.id, "RESOLVED", 3, note="Reviewed; no change to plan.")
    assert resolved.json()["alert"] == {
        "alert_id": str(alert.id),
        "workflow_status": "RESOLVED",
        "lock_version": 4,
    }
    after = review(client, rivera, alert.id, "NOTE_ADDED", 4, note="Follow-up note")  # notes never reopen
    assert after.json()["alert"]["workflow_status"] == "RESOLVED"

    events = client.get(f"{D}/alerts/{alert.id}/events?limit=2", headers=rivera).json()
    more = client.get(f"{D}/alerts/{alert.id}/events?cursor={events['next_cursor']}", headers=rivera).json()
    actions = [ev["action"] for ev in events["items"] + more["items"]]
    assert actions == ["CREATED", "ACKNOWLEDGED", "NOTE_ADDED", "RESOLVED", "NOTE_ADDED"]
    assert events["items"][0]["actor"] is None and events["items"][0]["to_status"] == "OPEN"

    # Reviewing never rewrites the evidence.
    detail = client.get(f"{D}/patients/{e}/assessments/{world['a7'].id}", headers=rivera).json()
    assert detail["analysis"]["deviation_level"] == "REVIEW" and detail["scores"]["memory_score"] == 33.333
    # Queue default hides resolved alerts; include_resolved shows them.
    assert client.get(f"{D}/alerts", headers=rivera).json()["items"] == []
    assert len(client.get(f"{D}/alerts?include_resolved=true", headers=rivera).json()["items"]) == 1

    # A revoked assignment cannot replay a privileged mutation (even with an accepted key).
    assignment = db.scalar(
        select(DoctorPatientAssignment).where(
            DoctorPatientAssignment.patient_id == e,
            DoctorPatientAssignment.doctor_user_id == user(db, RIVERA).id,
        )
    )
    assignment.ended_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert review(client, rivera, alert.id, "ACKNOWLEDGED", 1, key=key).status_code == 404
    assert client.get(f"{D}/alerts/{alert.id}/events", headers=rivera).status_code == 404
    # The committed history remains for the still-assigned doctor, attributed to Dr. Rivera.
    history = client.get(f"{D}/alerts/{alert.id}/events?limit=10", headers=okafor).json()["items"]
    assert history[1]["actor"]["display_name"] == "Dr. Ana Rivera"


def test_patient_receipt_never_shows_doctor_notes(client, world, login_as):
    rivera = login_as(RIVERA)
    review(client, rivera, world["alert"].id, "NOTE_ADDED", 1, note="Private clinical note")
    receipt = client.get(f"/api/v1/patient/assessments/{world['a7'].id}/receipt", headers=login_as(ELEANOR))
    assert receipt.status_code == 200 and "Private clinical note" not in receipt.text
    assert "REVIEW" not in receipt.text
