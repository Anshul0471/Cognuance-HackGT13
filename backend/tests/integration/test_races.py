"""Real concurrency (guide 07 §4.3–§4.4): separate committed connections, two HTTP clients released
together by a barrier. Runs in a throwaway `cognuance_test_races` database, never the shared one."""

import threading
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.session import get_db
from app.main import app
from app.ml.models import registry
from app.models import (
    Alert,
    AlertEvent,
    Analysis,
    Assessment,
    AssessmentSession,
    ContextCheckin,
    DoctorPatientAssignment,
    PatientProfile,
    User,
)
from app.scripts.seed_demo import seed_demo
from tests.conftest import DEMO_PASSWORD
from tests.factories import build_payload
from tests.integration.test_anomaly_workflow import model_env  # noqa: F401  (fixture)
from tests.integration.throwaway import throwaway_database, upgrade
from tests.model_fixtures import checkin, make_bundle, register_bundle, week

ANCHOR = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
ELEANOR, RIVERA, OKAFOR = "eleanor.park@demo.test", "dr.rivera@demo.test", "dr.okafor@demo.test"


@pytest.fixture
def race_db():
    with throwaway_database("cognuance_test_races") as url:
        upgrade(url)
        engine = create_engine(url, pool_size=10)
        maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        def per_request_session():
            session = maker()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = per_request_session
        with maker() as db:
            seed_demo(db, DEMO_PASSWORD)
        try:
            yield maker
        finally:
            app.dependency_overrides.pop(get_db, None)
            engine.dispose()


def _token(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _together(*calls):
    """Run each call in its own thread, released at the same moment; return responses in order."""
    barrier = threading.Barrier(len(calls))
    results: list = [None] * len(calls)

    def run(i, call):
        barrier.wait()
        results[i] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def test_concurrent_identical_starts_and_submissions_create_one_record(race_db):
    with TestClient(app) as a, TestClient(app) as b:
        headers = _token(a, ELEANOR)
        body = {
            "start_key": str(uuid.uuid4()),
            "input_mode": "keyboard",
            "device_changed": False,
            "navigation_assistance": False,
            "allow_unscheduled": False,
        }
        r1, r2 = _together(
            lambda: a.post("/api/v1/patient/assessment-sessions", json=body, headers=headers),
            lambda: b.post("/api/v1/patient/assessment-sessions", json=body, headers=headers),
        )
        assert sorted([r1.status_code, r2.status_code]) in ([200, 201], [201, 201]), (r1.text, r2.text)
        assert r1.json()["session_id"] == r2.json()["session_id"]
        session_id = r1.json()["session_id"]
        with race_db() as db:
            assert db.scalar(select(func.count()).select_from(AssessmentSession)) == 1
            protocol = db.get(AssessmentSession, uuid.UUID(session_id)).protocol_snapshot

        payload = build_payload(protocol)
        url = f"/api/v1/patient/assessment-sessions/{session_id}/submissions"
        s1, s2 = _together(
            lambda: a.post(url, json=payload, headers=headers),
            lambda: b.post(url, json=payload, headers=headers),
        )
        assert sorted([s1.status_code, s2.status_code]) == [200, 201], (s1.text, s2.text)
        assert s1.json()["assessment_id"] == s2.json()["assessment_id"]
        assert {s1.json()["replayed"], s2.json()["replayed"]} == {True, False}
        with race_db() as db:
            for model in (Assessment, ContextCheckin, Analysis):
                assert db.scalar(select(func.count()).select_from(model)) == 1, model.__name__
            assert db.scalar(select(func.count()).select_from(Alert)) <= 1


@pytest.fixture
def alert_world(race_db, model_env):  # noqa: F811
    root, _ = model_env
    with race_db() as db:
        register_bundle(db, root, make_bundle(root))
        registry.activate(db, "test-model", "test-policy", root)
        db.commit()
        eleanor = db.scalar(select(PatientProfile.id).join(User).where(User.email == ELEANOR))
        okafor = db.scalar(select(User.id).where(User.email == OKAFOR))
        db.add(DoctorPatientAssignment(doctor_user_id=okafor, patient_id=eleanor))  # second reviewer
        db.commit()
        for k in range(6):
            checkin(db, eleanor, week(ANCHOR, k), words=4, rt_ms=390.0)
        _, flagged = checkin(db, eleanor, week(ANCHOR, 6), words=1, rt_ms=390.0)
        alert = db.scalar(select(Alert).where(Alert.assessment_id == flagged.id))
        assert alert is not None
        return race_db, alert.id


def _event(client, headers, alert_id, action, version, key, note=None):
    body = {"request_key": key, "expected_lock_version": version, "action": action, "note": note}
    return client.post(f"/api/v1/doctor/alerts/{alert_id}/events", json=body, headers=headers)


def test_two_reviewers_racing_on_one_version_exactly_one_wins(alert_world):
    maker, alert_id = alert_world
    with TestClient(app) as a, TestClient(app) as b:
        rivera, okafor = _token(a, RIVERA), _token(b, OKAFOR)
        k1, k2 = str(uuid.uuid4()), str(uuid.uuid4())
        r1, r2 = _together(
            lambda: _event(a, rivera, alert_id, "ACKNOWLEDGED", 1, k1),
            lambda: _event(b, okafor, alert_id, "ACKNOWLEDGED", 1, k2),
        )
        codes = sorted([r1.status_code, r2.status_code])
        assert codes == [200, 409], (r1.text, r2.text)
        loser = r1 if r1.status_code == 409 else r2
        assert loser.json()["error"]["code"] == "STALE_ALERT_VERSION"
        winner_client, winner_headers, winner_key = (
            (a, rivera, k1) if r1.status_code == 200 else (b, okafor, k2)
        )

        # Another event, then the winner's frozen request again: replayed, no duplicate, current summary.
        assert (
            _event(
                winner_client, winner_headers, alert_id, "NOTE_ADDED", 2, str(uuid.uuid4()), "Seen."
            ).status_code
            == 200
        )
        again = _event(winner_client, winner_headers, alert_id, "ACKNOWLEDGED", 1, winner_key)
        assert again.status_code == 200 and again.json()["replayed"] is True
        assert again.json()["alert"]["lock_version"] == 3
    with maker() as db:
        assert (
            db.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.alert_id == alert_id))
            == 3
        )


def test_same_reviewer_same_key_in_parallel_records_one_event(alert_world):
    maker, alert_id = alert_world
    with TestClient(app) as a, TestClient(app) as b:
        headers = _token(a, RIVERA)
        key = str(uuid.uuid4())
        r1, r2 = _together(
            lambda: _event(a, headers, alert_id, "ACKNOWLEDGED", 1, key),
            lambda: _event(b, headers, alert_id, "ACKNOWLEDGED", 1, key),
        )
        assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
        assert {r1.json()["replayed"], r2.json()["replayed"]} == {True, False}
    with maker() as db:
        assert (
            db.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.alert_id == alert_id))
            == 2
        )
