"""Showcase dataset tooling (refinement 03 §4–§8, §14): roster, file-only prepare, chronological
replay through the live services, idempotent reruns, review safety and the authorization boundary."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.ml import serving
from app.ml.data.config import DatasetError
from app.ml.data.showcase import (
    FAMILIES,
    PATIENT_NAMES,
    _import_history,
    _load,
    _review_plan,
    apply_reviews,
    build_roster,
    credentials_path,
    import_showcase,
    prepare_showcase,
    provision_identities,
    verify_showcase,
)
from app.ml.models import registry
from app.models import Alert, Assessment, AssessmentSession, Forecast, User
from app.schemas.doctor import AlertEventRequest
from app.services import reviews
from tests.model_fixtures import make_bundle, register_bundle

AS_OF = datetime(2026, 9, 26, 16, 0, tzinfo=UTC)
PRESENTATION = datetime(2026, 9, 27, 16, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)


def test_roster_is_deterministic_balanced_and_names_carry_no_scenario():
    roster = build_roster(20260927)
    assert roster == build_roster(20260927)
    assert len(roster) == 30 and len({r.display_name for r in roster}) == 30
    counts = {f: sum(1 for r in roster if r.family == f) for f, _ in FAMILIES}
    assert counts == dict(FAMILIES)
    presenter = [r for r in roster if r.doctor == "presenter"]
    assert len(presenter) == 24 and len(roster) - len(presenter) == 6
    assert {r.family for r in presenter} == {f for f, _ in FAMILIES}  # every family reachable
    assert (
        sum(r.live_ready for r in roster) == 1
        and next(r for r in roster if r.live_ready).doctor == "presenter"
    )
    words = {"risk", "high", "demo", "synthetic", "patient", "steady", "stable", "alert"}
    assert not any(w in n.lower() for n in PATIENT_NAMES for w in words)


@pytest.fixture
def showcase_env(seeded, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_MODE", "baseline")
    monkeypatch.setenv("MODEL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SYNTHETIC_DATA_DIR", str(tmp_path / "data" / "synthetic"))
    get_settings.cache_clear()
    serving.clear_cache()
    root = tmp_path / "artifacts"
    register_bundle(seeded, root, make_bundle(root))
    registry.activate(seeded, "test-model", "test-policy", root)
    seeded.commit()
    presenter = seeded.scalar(select(User).where(User.email == "dr.okafor@demo.test"))
    yield seeded, presenter
    get_settings.cache_clear()
    serving.clear_cache()


def _prepare(presenter, count=6):
    return prepare_showcase("showcase-t", 7, AS_OF, PRESENTATION, presenter.id, patient_count=count)


def test_prepare_is_file_only_fixed_and_before_as_of(showcase_env):
    db, presenter = showcase_env
    path, status = _prepare(presenter)
    assert status == "created"
    assert db.scalar(select(func.count()).select_from(AssessmentSession)) == 0  # no DB writes
    assert _prepare(presenter) == (path, "reused")
    with pytest.raises(DatasetError, match="new --dataset-id"):
        prepare_showcase("showcase-t", 8, AS_OF, PRESENTATION, presenter.id, patient_count=6)
    _, manifest, sessions = _load("showcase-t", None)
    assert all(datetime.fromisoformat(s["available_at"]) < AS_OF for s in sessions)
    live = [p for p in manifest["patients"] if p["live_ready"]]
    assert len(live) == 1 and live[0]["next_target_at"] == PRESENTATION.isoformat()
    assert all(p["email"].endswith("@showcase.example") for p in manifest["patients"])
    assert "password" not in json.dumps(manifest).lower().replace("passwords are never stored", "")


def test_import_replays_through_live_services_and_reruns_are_no_ops(showcase_env):
    db, presenter = showcase_env
    _prepare(presenter)
    first = import_showcase(db, "showcase-t", now=NOW)
    assert first["failures"] == [] and first["identity"]["users_created"] == 7  # 6 patients + secondary
    assert "model_version" in first["model_binding"]

    report = verify_showcase(db, "showcase-t", now=NOW)
    assert report["problems"] == []
    assert report["rescored"]["mismatches"] == 0 and report["chronology_violations"] == 0
    assert report["forecasts"] > 0 and report["assessments"]["by_source"].get("SCENARIO_REPLAY", 0) > 0
    live = report["live_ready"][0]
    assert live["six_consecutive_before_target"] and not live["consumed"] and live["next_slot_sessions"] == []

    # Every forecast was frozen at its simulated session start, before the target answers existed.
    for f in db.scalars(select(Forecast)):
        session = db.get(AssessmentSession, f.session_id)
        target = db.scalar(select(Assessment).where(Assessment.session_id == f.session_id))
        assert f.issued_at == session.started_at == f.history_cutoff_at
        assert target is None or f.issued_at < target.available_at

    creds = credentials_path("showcase-t")
    assert oct(creds.stat().st_mode & 0o777) == "0o600"
    assert len(json.loads(creds.read_text())) == 7
    assert "password" not in json.dumps(first, default=str).lower()

    tables = (User, AssessmentSession, Assessment, Forecast, Alert)
    before = {t.__tablename__: db.scalar(select(func.count()).select_from(t)) for t in tables}
    hashes = dict(db.execute(select(User.email, User.password_hash)).all())
    again = import_showcase(db, "showcase-t", now=NOW)
    after = {t.__tablename__: db.scalar(select(func.count()).select_from(t)) for t in tables}
    assert before == after
    assert dict(db.execute(select(User.email, User.password_hash)).all()) == hashes
    assert again["identity"]["users_created"] == 0 and again["reviews"]["recorded"] == 0


def test_changed_payload_under_existing_id_is_a_conflict(showcase_env):
    db, presenter = showcase_env
    _prepare(presenter)
    _, manifest, sessions = _load("showcase-t", None)
    provision_identities(db, "showcase-t", manifest)
    entry = manifest["patients"][0]
    rows = [s for s in sessions if s["demo_key"] == entry["demo_key"]]
    _import_history(db, "showcase-t", entry, rows)
    tampered = json.loads(json.dumps(rows))
    tampered[0]["raw_submission"]["context"]["mood_score"] = (
        1 + (tampered[0]["raw_submission"]["context"]["mood_score"] or 0) % 9
    )
    with pytest.raises(DatasetError, match="conflict"):
        _import_history(db, "showcase-t", entry, tampered)


def test_review_rerun_never_overrides_a_presenter_change(showcase_env):
    db, presenter = showcase_env
    _prepare(presenter)
    _, manifest, sessions = _load("showcase-t", None)
    provision_identities(db, "showcase-t", manifest)
    for p in manifest["patients"]:
        _import_history(db, "showcase-t", p, [s for s in sessions if s["demo_key"] == p["demo_key"]])
    planned = [(p, a) for p, a, steps in _review_plan(manifest, db) if steps and p["doctor"] == "presenter"]
    if not planned:
        pytest.skip("fixture policy produced no alert with planned review steps")
    _, alert = planned[0]
    # The presenter resolves it first (e.g. during a rehearsal).
    reviews.record_event(
        db,
        presenter,
        alert.id,
        AlertEventRequest(
            request_key=uuid.uuid4(), expected_lock_version=1, action="RESOLVED", note="Handled live."
        ),
        NOW,
    )
    db.commit()
    counts = apply_reviews(db, "showcase-t", manifest, NOW)
    assert counts["skipped_changed"] >= 1
    db.refresh(alert)
    assert alert.status == "RESOLVED" and alert.lock_version == 2  # untouched by the seed


def test_presenter_cannot_reach_secondary_patients(showcase_env, client, login_as):
    db, presenter = showcase_env
    _prepare(presenter)
    import_showcase(db, "showcase-t", now=NOW)
    _, manifest, _ = _load("showcase-t", None)
    headers = login_as("dr.okafor@demo.test")
    secondary = [p for p in manifest["patients"] if p["doctor"] == "secondary"]
    assert secondary
    for p in secondary:
        assert client.get(f"/api/v1/doctor/patients/{p['patient_id']}", headers=headers).status_code == 404
        found = client.get("/api/v1/doctor/patients", params={"q": p["display_name"]}, headers=headers).json()
        assert found["items"] == []
    listed = client.get("/api/v1/doctor/patients", params={"limit": 100}, headers=headers).json()["items"]
    assert len(listed) == 1 + sum(1 for p in manifest["patients"] if p["doctor"] == "presenter")  # + Iris
