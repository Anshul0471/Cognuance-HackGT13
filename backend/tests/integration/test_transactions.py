"""Transaction boundaries (guide 07 §4.3): a failed commit leaves no partial business record and
no saved claim; a model activated after session start never changes that session's frozen pair."""

import random
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.ml.models import registry
from app.models import Analysis, Assessment, AssessmentSession, ContextCheckin, Forecast, ModelVersion
from app.schemas.assessments import AssessmentSubmission, StartSessionRequest
from app.services.analyses import analyze_after_commit
from app.services.assessment_sessions import start_session
from app.services.assessment_submissions import submit_assessment
from tests.factories import build_payload
from tests.integration.test_anomaly_workflow import ANCHOR, BASE, active, model_env, patient_id  # noqa: F401
from tests.integration.test_assessments_api import eleanor, full_protocol, start  # noqa: F401
from tests.model_fixtures import checkin, make_bundle, payload_for, register_bundle, week


def test_database_failure_before_receipt_commit_saves_nothing(client, eleanor, db_session, monkeypatch):  # noqa: F811
    session_id = start(client, eleanor).json()["session_id"]
    payload = build_payload(full_protocol(db_session, session_id))
    real_commit = db_session.commit
    calls = {"n": 0}

    def failing_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, Exception("connection lost"))
        return real_commit()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    url = f"/api/v1/patient/assessment-sessions/{session_id}/submissions"
    failed = client.post(url, json=payload, headers=eleanor)
    assert failed.status_code == 503 and failed.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    for model in (Assessment, ContextCheckin, Analysis):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0, model.__name__
    assert db_session.get(AssessmentSession, uuid.UUID(session_id)).status == "STARTED"

    # The client retries the identical frozen body: now it is saved exactly once.
    ok = client.post(url, json=payload, headers=eleanor)
    assert ok.status_code == 201 and ok.json()["replayed"] is False
    assert db_session.scalar(select(func.count()).select_from(Assessment)) == 1


def test_model_activated_after_session_start_keeps_the_frozen_pair(active, model_env):  # noqa: F811
    db = active
    root, _ = model_env
    pid = patient_id(db)
    for k in range(6):
        checkin(db, pid, week(ANCHOR, k), **BASE)
    req = StartSessionRequest(
        start_key=uuid.uuid4(),
        input_mode="keyboard",
        device_changed=False,
        navigation_assistance=False,
        allow_unscheduled=False,
    )
    when = week(ANCHOR, 6)
    session, _ = start_session(db, pid, req, when, rng=random.Random(3))
    db.commit()
    forecast = db.scalar(select(Forecast).where(Forecast.session_id == session.id))
    assert forecast is not None
    original_model = forecast.model_version_id

    # A different model/policy pair is activated between start and submission.
    register_bundle(db, root, make_bundle(root, version="test-model-b", policy_versions=("test-policy-b2",)))
    registry.activate(db, "test-model-b", "test-policy-b2", root)
    db.commit()

    payload = AssessmentSubmission.model_validate(payload_for(session.protocol_snapshot, **BASE))
    assessment, _ = submit_assessment(db, pid, session.id, payload, when + timedelta(minutes=10))
    db.commit()
    analyze_after_commit(db, assessment.id, when + timedelta(minutes=10))
    analysis = db.scalar(select(Analysis).where(Analysis.assessment_id == assessment.id))
    db.refresh(forecast)
    assert analysis.availability == "COMPLETE"
    assert analysis.model_version_id == original_model == forecast.model_version_id
    assert analysis.policy_id == forecast.policy_id
    assert db.scalar(select(ModelVersion.version).where(ModelVersion.is_active.is_(True))) == "test-model-b"
