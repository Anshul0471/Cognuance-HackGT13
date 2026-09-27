"""Composite score `cognitive_index_v1` and the Insights endpoint (refinement 01 §12)."""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from app.ml.models import registry
from app.models import Alert, Assessment, Forecast, PatientProfile, User
from app.services import cognitive_index, doctor_views
from tests.integration.test_anomaly_workflow import model_env  # noqa: F401  (fixture)
from tests.model_fixtures import checkin, make_bundle, register_bundle, week

ANCHOR = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)
BASE = {"words": 4, "attention_misses": 0, "rt_ms": 390.0}
RIVERA, OKAFOR = "dr.rivera@demo.test", "dr.okafor@demo.test"
ELEANOR, IRIS = "eleanor.park@demo.test", "iris.novak@demo.test"
D = "/api/v1/doctor"
PROTOCOL, SCORING = "cognitive_tasks_en_v1", "cognitive_scoring_v1"


def observed(memory, attention, rt, *, quality="VALID", protocol=PROTOCOL, scoring=SCORING):
    return cognitive_index.observed_index(
        quality=quality,
        memory_score=memory,
        attention_score=attention,
        reaction_time_ms=rt,
        protocol_version=protocol,
        scoring_version=scoring,
    )


def pid(db, email):
    return db.scalar(select(PatientProfile.id).join(User).where(User.email == email))


# --- pure formula (§12.1, §12.3) ------------------------------------------------------------------


def test_worked_example_and_component_normalization():
    result = observed(50, 75, 680)
    assert result.components is not None
    assert result.components.response_speed == pytest.approx(80.0)
    assert result.value == pytest.approx(68.333333, abs=1e-6)
    assert result.reasons == () and result.response_speed_clipped is False
    # Equal one-third weights, and the anchors map the window ends to 100 / 0.
    assert cognitive_index.response_speed(100.0) == (100.0, False)
    assert cognitive_index.response_speed(3000.0) == (0.0, False)
    assert cognitive_index.metadata()["weights"] == {
        "memory": pytest.approx(1 / 3),
        "attention": pytest.approx(1 / 3),
        "response_speed": pytest.approx(1 / 3),
    }


def test_monotonic_in_each_component():
    slower = [observed(50, 75, rt).value for rt in (400.0, 800.0, 1600.0)]
    assert slower == sorted(slower, reverse=True)  # slower responses lower the score
    assert observed(83.333, 75, 680).value > observed(50, 75, 680).value
    assert observed(50, 90, 680).value > observed(50, 75, 680).value


def test_missing_invalid_and_unsupported_inputs_return_null_with_reasons():
    assert observed(None, 75, 680) == cognitive_index.IndexResult(None, None, ("MISSING_DOMAIN",), False)
    assert observed(50, 75, None).reasons == ("MISSING_DOMAIN",)
    assert observed(float("nan"), 75, 680).reasons == ("INVALID_DOMAIN_VALUE",)
    assert observed(120, 75, 680).reasons == ("INVALID_DOMAIN_VALUE",)
    # A timeout is not a usable 3000 ms response, and below the floor is anticipatory.
    assert observed(50, 75, 3000).reasons == ("INVALID_DOMAIN_VALUE",)
    assert observed(50, 75, 99.9).reasons == ("INVALID_DOMAIN_VALUE",)
    assert observed(50, 75, 680, quality="LOW").reasons == ("LOW_QUALITY",)
    assert observed(50, 75, 680, quality="INCOMPLETE").reasons == ("INCOMPLETE_ASSESSMENT",)
    assert observed(50, 75, 680, protocol="other_v2").reasons == ("UNSUPPORTED_PROTOCOL",)
    # Never renormalized over two tasks and never zero-filled.
    for result in (observed(None, 75, 680), observed(50, 75, 3000)):
        assert result.value is None and result.components is None


def test_forecast_projection_clipping_and_missing():
    ready = cognitive_index.forecast_index(
        predicted_memory_score=70.2,
        predicted_attention_score=80.0,
        predicted_reaction_time_ms=600.0,
        protocol_version=PROTOCOL,
        scoring_version=SCORING,
    )
    assert ready.value == pytest.approx((70.2 + 80.0 + 100 * (2400 / 2900)) / 3)
    assert ready.response_speed_clipped is False
    # A continuous prediction beyond the window is clipped and reported, not rejected.
    clipped = cognitive_index.forecast_index(
        predicted_memory_score=70.0,
        predicted_attention_score=80.0,
        predicted_reaction_time_ms=4000.0,
        protocol_version=PROTOCOL,
        scoring_version=SCORING,
    )
    assert clipped.components is not None and clipped.components.response_speed == 0.0
    assert clipped.response_speed_clipped is True
    missing = cognitive_index.missing_forecast()
    assert missing.value is None and missing.reasons == ("FORECAST_MISSING",)
    assert missing.response_speed_clipped is False  # not a readiness flag


# --- projection over real scored data (§12.2, §12.4, §12.5) ---------------------------------------


@pytest.fixture
def world(seeded, model_env):  # noqa: F811
    """Eleanor: 7 normal weeks, a flagged week 7, then a LOW week-8 retake."""
    db = seeded
    root, _ = model_env
    register_bundle(db, root, make_bundle(root))
    registry.activate(db, "test-model", "test-policy", root)
    db.commit()
    eleanor = pid(db, ELEANOR)
    for k in range(7):
        checkin(db, eleanor, week(ANCHOR, k), **BASE)
    # Week 7 is the spec's worked example: 3/6 words, 5 hits, 680 ms median.
    _, flagged = checkin(db, eleanor, week(ANCHOR, 7), words=3, attention_misses=5, rt_ms=680.0)
    _, low = checkin(
        db,
        eleanor,
        week(ANCHOR, 8),
        answer_assistance={"memory": "PROVIDED", "attention": "NONE", "reaction": "NONE"},
        **BASE,
    )
    return {"db": db, "eleanor": eleanor, "flagged": flagged, "low": low}


def test_canonical_scorer_values_produce_the_documented_index(world, client, login_as):
    headers = login_as(RIVERA)
    item = client.get(
        f"{D}/patients/{world['eleanor']}/assessments/{world['flagged'].id}", headers=headers
    ).json()
    assert (item["scores"]["memory_score"], item["scores"]["attention_score"]) == (50.0, 75.0)
    assert item["scores"]["reaction_time_ms"] == 680.0
    index = item["cognitive_index"]
    assert index["version"] == "cognitive_index_v1"
    assert index["observed_value"] == pytest.approx(68.333333, abs=1e-5)
    assert index["observed_components"]["response_speed"] == pytest.approx(80.0)
    assert index["observed_unavailable_reasons"] == []
    # Raw units are untouched by the projection.
    assert item["forecast"]["predicted_reaction_time_ms"] > 0


def test_low_quality_assessment_has_no_composite_but_keeps_its_scores(world, client, login_as):
    item = client.get(
        f"{D}/patients/{world['eleanor']}/assessments/{world['low'].id}", headers=login_as(RIVERA)
    ).json()
    assert item["quality_status"] == "LOW"
    assert item["scores"]["memory_score"] == pytest.approx(66.667)  # evidence stays visible
    assert item["cognitive_index"]["observed_value"] is None
    assert item["cognitive_index"]["observed_unavailable_reasons"] == ["LOW_QUALITY"]


def test_projection_uses_the_frozen_forecast_and_never_the_observed_values(world, client, login_as):
    db, headers = world["db"], login_as(RIVERA)
    path = f"{D}/patients/{world['eleanor']}/assessments/{world['flagged'].id}"
    before = client.get(path, headers=headers).json()["cognitive_index"]
    assert before["forecast_value"] is not None and before["forecast_value"] != before["observed_value"]

    forecast = db.scalar(select(Forecast).where(Forecast.session_id == world["flagged"].session_id))
    assert forecast is not None
    expected = cognitive_index.forecast_index(
        predicted_memory_score=forecast.predicted_memory_score,
        predicted_attention_score=forecast.predicted_attention_score,
        predicted_reaction_time_ms=forecast.predicted_reaction_time_ms,
        protocol_version=PROTOCOL,
        scoring_version=SCORING,
    )
    assert before["forecast_value"] == pytest.approx(expected.value)

    # Editing the current context cannot move an already-issued projection.
    context = world["flagged"].context
    context.sleep_hours = 3
    context.mood_score = 2
    db.commit()
    after = client.get(path, headers=headers).json()["cognitive_index"]
    assert after["forecast_value"] == pytest.approx(before["forecast_value"])
    assert after["observed_value"] == pytest.approx(before["observed_value"])


def test_a_stable_looking_composite_never_suppresses_the_original_alert(world, client, login_as):
    db = world["db"]
    alert = db.scalar(select(Alert).where(Alert.assessment_id == world["flagged"].id))
    assert alert is not None and alert.deviation_level != "NORMAL"
    item = client.get(
        f"{D}/patients/{world['eleanor']}/assessments/{world['flagged'].id}", headers=login_as(RIVERA)
    ).json()
    # The composite is unremarkable, yet the domain-specific alert and category stand.
    assert item["cognitive_index"]["observed_value"] > 60
    assert item["analysis"]["deviation_level"] == alert.deviation_level
    assert item["alert"]["workflow_status"] == "OPEN"


# --- insights endpoint (§12.6, §12.7, §12.9) ------------------------------------------------------


def insights(client, headers, patient_id, *, frm=None, to=None, source=None):
    params = {
        "from": (frm or ANCHOR - timedelta(days=1)).isoformat(),
        "to": (to or ANCHOR + timedelta(days=120)).isoformat(),
    }
    if source:
        params["source"] = source
    return client.get(f"{D}/patients/{patient_id}/insights?{urlencode(params)}", headers=headers)


def test_insights_returns_one_complete_snapshot_with_every_assessment(world, client, login_as):
    body = insights(client, login_as(RIVERA), world["eleanor"]).json()
    assert body["complete"] is True
    assert body["assessment_count"] == len(body["records"]) == 9  # includes the LOW retake
    assert body["timezone"] and body["score_metadata"]["version"] == "cognitive_index_v1"
    observed_times = [r["observed_at"] for r in body["records"]]
    assert observed_times == sorted(observed_times)
    # Quality and availability are separate dimensions; each partitions the same total.
    for field, container in (("quality_status", "records"), ("analysis", "records")):
        counted = sum(1 for r in body[container] if r[field] is not None)
        assert counted == body["assessment_count"]
    with_score = [r for r in body["records"] if r["cognitive_index"]["observed_value"] is not None]
    assert len(with_score) == 8  # the LOW retake has none


def test_insights_adjacency_skips_gaps_and_ineligible_records(world, client, login_as):
    db = world["db"]
    # A missing week breaks adjacency: week 10 has no week-9 predecessor.
    iris = pid(db, IRIS)
    checkin(db, iris, week(ANCHOR, 0), **BASE)
    checkin(db, iris, week(ANCHOR, 1), **BASE)
    checkin(db, iris, week(ANCHOR, 3), **BASE)  # week 2 skipped
    body = insights(client, login_as(OKAFOR), iris).json()
    by_slot = {r["slot_index"]: r for r in body["records"]}
    assert by_slot[0]["previous_comparable_assessment_id"] is None  # first point in range
    assert by_slot[1]["previous_comparable_assessment_id"] == str(by_slot[0]["assessment_id"])
    assert by_slot[3]["previous_comparable_assessment_id"] is None  # gap, not compressed
    assert all(r["is_representative"] for r in body["records"])

    # The LOW retake is not a representative and never gains weekly weight.
    eleanor = insights(client, login_as(RIVERA), world["eleanor"]).json()
    low = next(r for r in eleanor["records"] if r["assessment_id"] == str(world["low"].id))
    assert low["is_representative"] is False
    assert low["previous_comparable_assessment_id"] is None
    assert low["comparison_segment_key"]


def test_insights_first_point_in_a_filtered_range_has_no_predecessor(world, client, login_as):
    body = insights(
        client,
        login_as(RIVERA),
        world["eleanor"],
        frm=week(ANCHOR, 5) - timedelta(hours=1),
    ).json()
    assert body["records"][0]["previous_comparable_assessment_id"] is None
    assert body["records"][1]["previous_comparable_assessment_id"] is not None


def test_insights_source_filter_and_linked_alert_metadata(world, client, login_as):
    headers = login_as(RIVERA)
    live = insights(client, headers, world["eleanor"], source="LIVE_DEMO").json()
    assert live["filters"]["source"] == "LIVE_DEMO"
    assert {r["source"] for r in live["records"]} == {"LIVE_DEMO"}
    assert insights(client, headers, world["eleanor"], source="SYNTHETIC_HISTORY").json()["records"] == []
    flagged = next(r for r in live["records"] if r["assessment_id"] == str(world["flagged"].id))
    assert flagged["linked_alert"]["workflow_status"] == "OPEN"
    assert flagged["linked_alert"]["deviation_level"] == flagged["analysis"]["deviation_level"]
    assert flagged["linked_alert"]["created_at"]
    assert flagged["context"]["reported_by"] == "PATIENT"


def test_insights_rejects_bad_ranges_and_refuses_to_truncate(world, client, login_as, monkeypatch):
    headers = login_as(RIVERA)
    patient = world["eleanor"]
    reversed_range = insights(client, headers, patient, frm=ANCHOR + timedelta(days=5), to=ANCHOR)
    assert reversed_range.status_code == 400
    assert reversed_range.json()["error"]["code"] == "INVALID_QUERY"
    too_wide = insights(client, headers, patient, to=ANCHOR + timedelta(days=400))
    assert too_wide.status_code == 400
    assert client.get(f"{D}/patients/{patient}/insights", headers=headers).status_code == 422  # no range

    monkeypatch.setattr(doctor_views, "MAX_INSIGHTS_RECORDS", 2)
    overflow = insights(client, headers, patient)
    assert overflow.status_code == 422
    assert overflow.json()["error"]["code"] == "INSIGHTS_RANGE_TOO_LARGE"
    assert "records" not in overflow.json()


def test_insights_is_assignment_scoped_and_leaks_nothing(world, client, login_as):
    patient = world["eleanor"]
    assert insights(client, login_as(OKAFOR), patient).status_code == 404  # not assigned
    assert insights(client, login_as(RIVERA), uuid.uuid4()).status_code == 404  # unknown, same shape
    assert insights(client, login_as(ELEANOR), patient).status_code == 403  # wrong role
    body = insights(client, login_as(RIVERA), patient).json()
    text = str(body)
    for secret in ("raw_responses", "payload_sha256", "password", "note"):
        assert secret not in text
    assert "recall_entries" not in text


def test_timeline_and_alert_detail_share_one_projection(world, client, login_as):
    headers = login_as(RIVERA)
    db = world["db"]
    timeline = client.get(f"{D}/patients/{world['eleanor']}/timeline", headers=headers).json()
    row = next(r for r in timeline["items"] if r["assessment_id"] == str(world["flagged"].id))
    alert = db.scalar(select(Alert).where(Alert.assessment_id == world["flagged"].id))
    nested = client.get(f"{D}/alerts/{alert.id}", headers=headers).json()["assessment"]
    assert row["cognitive_index"] == nested["cognitive_index"]
    stored = db.get(Assessment, world["flagged"].id)
    assert stored is not None and stored.memory_score is not None  # nothing was overwritten
