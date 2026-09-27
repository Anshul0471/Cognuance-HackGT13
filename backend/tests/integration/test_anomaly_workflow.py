"""Real database workflow: forecast at session start → analysis → persistence → alert.

Guide 04 §11, §14, §16, §19.
"""

import json
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.ml import serving
from app.ml.data.preprocessing import feature_row
from app.ml.models import registry
from app.ml.models.forecasting import predict_batch
from app.models import Alert, AlertEvent, Analysis, AnomalyPolicy, Forecast, PatientProfile, User
from app.services import analyses as analyses_service
from tests.model_fixtures import checkin, fake_params, make_bundle, register_bundle, week

ANCHOR = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
BASE = {"words": 4, "attention_misses": 0, "rt_ms": 390.0}  # 66.667 / 100 / 390 ms


@pytest.fixture
def model_env(monkeypatch, tmp_path):
    def configure(mode: str = "baseline") -> None:
        monkeypatch.setenv("MODEL_MODE", mode)
        monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path))
        get_settings.cache_clear()
        serving.clear_cache()

    configure()
    yield tmp_path, configure
    get_settings.cache_clear()
    serving.clear_cache()


@pytest.fixture
def active(seeded, model_env):
    root, _ = model_env
    register_bundle(seeded, root, make_bundle(root, policy_versions=("test-policy", "test-policy-b")))
    registry.activate(seeded, "test-model", "test-policy", root)
    seeded.commit()
    return seeded


def patient_id(db, email="eleanor.park@demo.test"):
    return db.scalar(select(PatientProfile.id).join(User).where(User.email == email))


def baseline_history(db, pid, slots=6):
    for k in range(slots):
        checkin(db, pid, week(ANCHOR, k), **BASE)


def analysis_of(db, assessment):
    return db.scalar(select(Analysis).where(Analysis.assessment_id == assessment.id))


def test_normal_review_persistent_high_paths(active, client, login_as):
    db, pid = active, patient_id(active)
    baseline_history(db, pid)

    s6, a6 = checkin(db, pid, week(ANCHOR, 6), **BASE)
    f6 = db.scalar(select(Forecast).where(Forecast.session_id == s6.id))
    assert s6.forecast_state == "READY" and f6 is not None
    assert (
        float(f6.predicted_memory_score),
        float(f6.predicted_attention_score),
        float(f6.predicted_reaction_time_ms),
    ) == (66.667, 100.0, 390.0)  # LAST_VALUE
    assert len(f6.input_assessment_ids) == 6 and f6.issued_at <= s6.history_cutoff_at
    an6 = analysis_of(db, a6)
    assert (an6.availability, an6.deviation_level, an6.persistent_count) == ("COMPLETE", "NORMAL", 0)
    assert a6.analysis_state == "COMPLETE"

    _, a7 = checkin(db, pid, week(ANCHOR, 7), words=2, attention_misses=0, rt_ms=390.0)  # memory −33.3
    an7 = analysis_of(db, a7)
    assert (an7.deviation_level, an7.persistent_count) == ("REVIEW", 1)
    assert an7.domain_deviations["memory"]["z"] == pytest.approx(3.3334)
    assert an7.aggregate_deviation == pytest.approx(3.3334 / 2)
    assert "Memory was 33.3 points below the stored forecast" in an7.explanation["summary"]
    alert7 = db.scalar(select(Alert).where(Alert.assessment_id == a7.id))
    assert alert7.deviation_level == "REVIEW" and alert7.status == "OPEN"
    events = db.scalars(select(AlertEvent).where(AlertEvent.alert_id == alert7.id)).all()
    assert [e.action for e in events] == ["CREATED"]

    _, a8 = checkin(db, pid, week(ANCHOR, 8), words=0, rt_ms=390.0)  # forecast 33.3 → observed 0
    assert (analysis_of(db, a8).deviation_level, analysis_of(db, a8).persistent_count) == (
        "PERSISTENT_DEVIATION",
        2,
    )

    _, a9 = checkin(db, pid, week(ANCHOR, 9), words=0, attention_misses=2, rt_ms=540.0)  # att z=2, RT z=3
    an9 = analysis_of(db, a9)
    assert (an9.deviation_level, an9.persistent_count, an9.high_signal) == ("HIGH_DEVIATION", 3, True)
    assert set(an9.explanation["facts"]["domains_at_or_above_r"]) == {"attention", "reaction_time_ms"}

    _, a10 = checkin(db, pid, week(ANCHOR, 10), words=0, attention_misses=2, rt_ms=540.0)
    assert (analysis_of(db, a10).deviation_level, analysis_of(db, a10).persistent_count) == ("NORMAL", 0)
    assert db.scalar(select(Alert).where(Alert.assessment_id == a10.id)) is None
    assert len(db.scalars(select(Alert).where(Alert.patient_id == pid)).all()) == 3

    # The patient's receipt reports completion only — no scores, levels or thresholds.
    receipt = client.get(
        f"/api/v1/patient/assessments/{a9.id}/receipt", headers=login_as("eleanor.park@demo.test")
    )
    body = receipt.json()
    assert receipt.status_code == 200 and body["analysis"]["availability"] == "COMPLETE"
    assert body["analysis"]["message"] == "Your check-in has been processed."
    assert "HIGH" not in receipt.text and "deviation" not in receipt.text.lower()


def test_low_quality_and_extra_attempts_get_no_category(active):
    db, pid = active, patient_id(active)
    baseline_history(db, pid)
    s6, a6 = checkin(
        db,
        pid,
        week(ANCHOR, 6),
        words=0,
        rt_ms=900.0,
        answer_assistance={"memory": "PROVIDED", "attention": "NONE", "reaction": "NONE"},
    )
    assert s6.forecast_state == "READY" and a6.quality == "LOW"
    an6 = analysis_of(db, a6)
    assert an6.availability == "INSUFFICIENT_DATA" and an6.deviation_level is None
    # Retake in the same week (still scheduled) is the representative; then an extra attempt.
    s6b, a6b = checkin(db, pid, week(ANCHOR, 6).replace(minute=40), **BASE)
    assert (
        s6b.schedule_purpose == "RETAKE_AFTER_UNRELIABLE" and analysis_of(db, a6b).deviation_level == "NORMAL"
    )
    s6c, a6c = checkin(
        db, pid, week(ANCHOR, 6).replace(minute=59), allow_unscheduled=True, words=0, rt_ms=900.0
    )
    assert s6c.schedule_purpose == "EXTRA_ATTEMPT" and s6c.forecast_state == "INSUFFICIENT_DATA"
    an6c = analysis_of(db, a6c)  # every submission has an analysis row; no forecast → no comparison
    assert (
        an6c.forecast_id is None and an6c.availability == "INSUFFICIENT_DATA" and an6c.deviation_level is None
    )
    assert "EXTRA_ATTEMPT" in an6c.reasons and a6c.processing_status == "ANALYZED"
    assert db.scalars(select(Alert).where(Alert.patient_id == pid)).all() == []


def test_missing_slot_and_policy_change_reset_persistence(active, model_env):
    db, pid = active, patient_id(active)
    root, _ = model_env
    baseline_history(db, pid, slots=7)
    _, a7 = checkin(db, pid, week(ANCHOR, 7), words=2, rt_ms=390.0)
    assert analysis_of(db, a7).persistent_count == 1
    # New policy for the same model: the next moderate signal starts a new streak.
    registry.activate(db, "test-model", "test-policy-b", root)
    db.commit()
    s8, a8 = checkin(db, pid, week(ANCHOR, 8), words=0, rt_ms=390.0)
    an8 = analysis_of(db, a8)
    assert an8.policy_id != analysis_of(db, a7).policy_id
    assert (an8.deviation_level, an8.persistent_count) == ("REVIEW", 1)
    # Existing session kept its original pair.
    assert (
        db.scalar(select(Forecast.policy_id).where(Forecast.session_id == a7.session_id))
        == analysis_of(db, a7).policy_id
    )
    # Skip slot 9 entirely: slot 10 has a history gap → no forecast, no analysis row.
    s10, a10 = checkin(db, pid, week(ANCHOR, 10), words=0, rt_ms=390.0)
    assert s10.forecast_state == "INSUFFICIENT_DATA" and "HISTORY_GAP" in s10.forecast_reasons
    an10 = analysis_of(db, a10)
    assert (
        an10.forecast_id is None
        and an10.availability == "INSUFFICIENT_DATA"
        and "HISTORY_GAP" in an10.reasons
    )


def test_stored_forecast_cannot_see_target_answers_or_context(active):
    db, pid = active, patient_id(active)
    baseline_history(db, pid)
    s6, _ = checkin(db, pid, week(ANCHOR, 6), **BASE)
    f = db.scalar(select(Forecast).where(Forecast.session_id == s6.id))
    snapshot, sha, values = f.feature_snapshot, f.feature_sha256, f.predicted_memory_score
    # Different answers/context for the next week leave the earlier forecast untouched.
    s7, _ = checkin(
        db,
        pid,
        week(ANCHOR, 7),
        words=0,
        rt_ms=1200.0,
        context={
            "sleep_hours": 2.0,
            "mood_score": 1,
            "medication_change": True,
            "reported_by": "PATIENT",
            "missing_fields": {},
        },
    )
    db.refresh(f)
    assert (f.feature_snapshot, f.feature_sha256, f.predicted_memory_score) == (snapshot, sha, values)
    assert all(h["slot_index"] < 6 for h in snapshot["history"])
    f7 = db.scalar(select(Forecast).where(Forecast.session_id == s7.id))
    assert all(h["slot_index"] < 7 for h in f7.feature_snapshot["history"])


def test_analysis_error_retry_is_idempotent_and_receipt_survives(active, client, login_as):
    db, pid = active, patient_id(active)
    baseline_history(db, pid)
    headers = login_as("eleanor.park@demo.test")
    policy = db.scalar(select(AnomalyPolicy).where(AnomalyPolicy.is_active.is_(True)))
    good = dict(policy.configuration)
    # Simulate a corrupt stored policy (bypassing immutability, test only).
    db.execute(
        text("UPDATE anomaly_policies SET configuration = '{}'::jsonb WHERE id = :i"), {"i": policy.id}
    )
    db.commit()
    db.expire_all()

    from tests.model_fixtures import payload_for

    with pytest.MonkeyPatch.context() as mp:
        from app.api.v1 import patient_assessments as routes

        mp.setattr(routes, "_now", lambda: week(ANCHOR, 6))
        start = client.post(
            "/api/v1/patient/assessment-sessions",
            headers=headers,
            json={
                "start_key": "00000000-0000-4000-8000-000000000006",
                "input_mode": "keyboard",
                "device_changed": False,
                "navigation_assistance": False,
                "allow_unscheduled": False,
            },
        )
        assert start.status_code == 201, start.text
        body = payload_for(_snapshot(db, start.json()["session_id"]), words=2, rt_ms=390.0)
        first = client.post(
            f"/api/v1/patient/assessment-sessions/{start.json()['session_id']}/submissions",
            headers=headers,
            json=body,
        )
        assert first.status_code == 201 and first.json()["analysis"]["availability"] == "ANALYSIS_ERROR"
        assert first.headers["location"].endswith(
            f"/patient/assessments/{first.json()['assessment_id']}/receipt"
        )
        assert "POLICY_INVALID" not in first.text  # internal failure codes never reach the patient
        assessment_id = first.json()["assessment_id"]
        an = db.scalar(select(Analysis).where(Analysis.assessment_id == assessment_id))
        assert an.last_error_code == "POLICY_INVALID" and an.deviation_level is None
        assert db.scalars(select(Alert).where(Alert.patient_id == pid)).all() == []

        db.execute(
            text("UPDATE anomaly_policies SET configuration = CAST(:c AS jsonb) WHERE id = :i"),
            {"c": json.dumps(good), "i": policy.id},
        )
        db.commit()
        db.expire_all()
        replay = client.post(
            f"/api/v1/patient/assessment-sessions/{start.json()['session_id']}/submissions",
            headers=headers,
            json=body,
        )
        assert replay.status_code == 200 and replay.json()["analysis"]["availability"] == "COMPLETE"
        assert replay.json()["replayed"] is True
        again = client.post(
            f"/api/v1/patient/assessment-sessions/{start.json()['session_id']}/submissions",
            headers=headers,
            json=body,
        )
        assert again.status_code == 200
    alerts = db.scalars(select(Alert).where(Alert.assessment_id == assessment_id)).all()
    assert len(alerts) == 1 and alerts[0].deviation_level == "REVIEW"
    an = db.scalar(select(Analysis).where(Analysis.assessment_id == assessment_id))
    assert an.attempts == 2  # one failure, one success; the second replay found COMPLETE and did nothing


def _snapshot(db, session_id):
    from app.models import AssessmentSession

    return db.get(AssessmentSession, session_id).protocol_snapshot


def test_pending_prior_analysis_is_handled_before_streak(active, monkeypatch):
    db, pid = active, patient_id(active)
    baseline_history(db, pid, slots=7)
    _, a7 = checkin(db, pid, week(ANCHOR, 7), analyze=False, words=2, rt_ms=390.0)  # left PENDING
    assert analysis_of(db, a7).availability == "PENDING"
    # Prior still failing → current waits instead of finalizing against a temporary gap.
    real = analyses_service._compute

    def failing(db_, analysis, *a, **k):
        if analysis.assessment_id == a7.id:
            raise analyses_service.AnalysisFailure("CALCULATION_FAILED")
        return real(db_, analysis, *a, **k)

    monkeypatch.setattr(analyses_service, "_compute", failing)
    _, a8 = checkin(db, pid, week(ANCHOR, 8), words=0, rt_ms=390.0)
    an8 = analysis_of(db, a8)
    assert an8.availability == "PENDING" and an8.reasons == ["WAITING_FOR_PREVIOUS_ANALYSIS"]
    assert analysis_of(db, a7).availability == "ANALYSIS_ERROR"
    monkeypatch.setattr(analyses_service, "_compute", real)
    # Bounded chronological recovery completes the prior first, then the current streak.
    results = analyses_service.recover_analyses(db, week(ANCHOR, 8), patient_id=pid)
    db.commit()
    assert [s for _, s, _ in results] == ["COMPLETE", "COMPLETE"]
    assert (analysis_of(db, a7).deviation_level, analysis_of(db, a7).persistent_count) == ("REVIEW", 1)
    assert (analysis_of(db, a8).deviation_level, analysis_of(db, a8).persistent_count) == (
        "PERSISTENT_DEVIATION",
        2,
    )
    assert analyses_service.needing_recovery(db) == 0


def test_unavailable_states_and_model_status(seeded, model_env, client):
    db, pid = seeded, patient_id(seeded)
    root, configure = model_env
    configure("unconfigured")
    assert client.get("/api/v1/model/status").json()["reason_code"] == "MODEL_NOT_CONFIGURED"
    configure("baseline")
    status = client.get("/api/v1/model/status").json()
    assert status["reason_code"] == "NO_ACTIVE_MODEL" and status["forecast_ready"] is False
    baseline_history(db, pid)
    s6, a6 = checkin(db, pid, week(ANCHOR, 6), **BASE)
    assert s6.forecast_state == "MODEL_UNAVAILABLE" and s6.forecast_reasons == [
        "MODEL_UNAVAILABLE",
        "NO_ACTIVE_MODEL",
    ]
    assert analysis_of(db, a6).forecast_id is None and a6.analysis_state == "MODEL_UNAVAILABLE"

    register_bundle(db, root, make_bundle(root))
    registry.activate(db, "test-model", "test-policy", root)
    db.commit()
    status = client.get("/api/v1/model/status").json()
    assert status == {
        "model_kind": "LAST_VALUE",
        "model_version": "test-model",
        "policy_version": "test-policy",
        "model_loaded": True,
        "policy_ready": True,
        "forecast_ready": True,
        "reason_code": None,
    }

    configure("gru")  # a baseline must never be served under a GRU label
    status = client.get("/api/v1/model/status").json()
    assert status["reason_code"] == "MODEL_MODE_MISMATCH" and not status["forecast_ready"]

    configure("baseline")
    (root / "test-model" / "model_config.json").write_text('{"tampered": true}')
    status = client.get("/api/v1/model/status").json()
    assert status["reason_code"] == "ARTIFACT_CHECKSUM_MISMATCH" and not status["model_loaded"]
    s7, a7 = checkin(db, pid, week(ANCHOR, 7), **BASE)
    assert s7.forecast_state == "MODEL_UNAVAILABLE" and "ARTIFACT_CHECKSUM_MISMATCH" in s7.forecast_reasons
    assert db.scalar(select(Forecast).where(Forecast.session_id == s7.id)) is None  # no silent fallback
    from app.services.assessment_submissions import build_receipt

    # The patient sees one friendly reason; the technical artifact code stays server-side.
    assert build_receipt(a7, replayed=False).analysis.reason_codes == ["MODEL_UNAVAILABLE"]


def test_activation_requires_activatable_verified_pair(seeded, model_env):
    db = seeded
    root, _ = model_env
    register_bundle(
        db,
        root,
        make_bundle(root, version="fixture-model", policy_versions=("fixture-policy",), activatable=False),
    )
    with pytest.raises(registry.RegistryError) as exc:
        registry.activate(db, "fixture-model", "fixture-policy", root)
    assert exc.value.code == "NOT_ACTIVATABLE"
    register_bundle(db, root, make_bundle(root, version="m2", policy_versions=("p2",)))
    with pytest.raises(registry.RegistryError) as exc:
        registry.activate(db, "m2", "fixture-policy", root)  # policy bound to another model
    assert exc.value.code in ("NOT_ACTIVATABLE", "POLICY_MODEL_MISMATCH")
    # Registered policy content is immutable: a different payload under the same version is refused.
    with pytest.raises(registry.RegistryError):
        make_bundle(root, version="m2", policy_versions=("p2",), r=3.0)


def test_gru_serving_matches_offline_transform_and_prediction(seeded, model_env):
    db, pid = seeded, patient_id(seeded)
    root, configure = model_env
    configure("gru")
    register_bundle(db, root, make_bundle(root, "GRU", version="gru-test", policy_versions=("gru-policy",)))
    registry.activate(db, "gru-test", "gru-policy", root)
    db.commit()
    baseline_history(db, pid)
    s6, _ = checkin(db, pid, week(ANCHOR, 6), **BASE)
    f = db.scalar(select(Forecast).where(Forecast.session_id == s6.id))
    params = fake_params()
    x = np.array([[feature_row(h, params) for h in f.feature_snapshot["history"]]], dtype=np.float32)
    assert np.allclose(x[0], np.array(f.feature_snapshot["x"], dtype=np.float32))
    loaded = serving.load_model(
        db.scalar(select(registry.ModelVersion).where(registry.ModelVersion.version == "gru-test"))
    )
    offline = predict_batch("GRU", x, np.zeros((1, 6, 3)), loaded.params, loaded.module)[0]
    assert offline.values() == (
        float(f.predicted_memory_score),
        float(f.predicted_attention_score),
        float(f.predicted_reaction_time_ms),
    )
    assert f.feature_snapshot["uses_context"] is True
