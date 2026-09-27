"""Guide 03 §18 checks on a smoke dataset (mechanics only; no model or clinical claims)."""

import copy
import json
import shutil
import uuid
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from app.ml.data import exports
from app.ml.data.config import DatasetError, dataset_dir, profile
from app.ml.data.demo_import import import_demo, prepare_demo
from app.ml.data.pipeline import generate, load_manifest, prepare
from app.ml.data.preprocessing import build_tensors, feature_row, fit
from app.ml.data.report import build_report
from app.ml.data.validation import validate_dataset


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    generate("smoke-a", profile("smoke"), root)
    prepare("smoke-a", "preprocessing_v1", root)
    return root


def load(root: Path, dataset_id: str, name: str):
    return list(exports.read_jsonl(dataset_dir(dataset_id, root) / name))


def windows_of(root, dataset_id="smoke-a"):
    return [
        w
        for p in ("train", "validation_tune", "validation_calibration", "test")
        for w in load(root, dataset_id, f"windows/{p}.jsonl")
    ]


def test_all_contract_checks_pass(smoke):
    checks = validate_dataset("smoke-a", smoke)
    failed = [(c.name, c.detail) for c in checks if not c.passed]
    assert not failed
    assert {c.name for c in checks} >= {
        "raw_replay_scoring",
        "score_support",
        "integrity",
        "split_isolation",
        "representatives",
        "temporal_boundary",
        "no_labels_in_x",
        "train_only_fit",
        "tensor_contract",
        "transform_round_trip",
        "missingness_encoding",
        "cognition_gaps_excluded",
        "masked_context_only_in_truth",
    }


def test_reproducible_and_reused(smoke):
    generate("smoke-b", profile("smoke"), smoke)
    prepare("smoke-b", "preprocessing_v1", smoke)
    a, b = load_manifest("smoke-a", smoke)[1], load_manifest("smoke-b", smoke)[1]
    for stage in ("generate", "prepare"):
        assert a["stages"][stage]["content_hash"] == b["stages"][stage]["content_hash"]
    assert generate("smoke-a", profile("smoke"), smoke)[1] == "reused"
    assert prepare("smoke-a", "preprocessing_v1", smoke)[1] == "reused"
    with pytest.raises(DatasetError, match="different configuration"):
        generate("smoke-a", profile("smoke", seed=7), smoke)
    with pytest.raises(DatasetError):
        generate("../escape", profile("smoke"), smoke)


def test_different_seed_changes_data(smoke):
    generate("smoke-seed7", profile("smoke", seed=7), smoke)
    a, b = load_manifest("smoke-a", smoke)[1], load_manifest("smoke-seed7", smoke)[1]
    assert a["stages"]["generate"]["content_hash"] != b["stages"]["generate"]["content_hash"]


def test_tampering_is_detected(smoke):
    shutil.copytree(dataset_dir("smoke-a", smoke), dataset_dir("smoke-tamper", smoke))
    manifest_path = dataset_dir("smoke-tamper", smoke) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_id"] = "smoke-tamper"
    manifest_path.write_text(json.dumps(manifest))
    obs_path = dataset_dir("smoke-tamper", smoke) / "observations.jsonl"
    obs_path.write_text(obs_path.read_text().replace('"memory_score":100.0', '"memory_score":99.0', 1))
    checks = {c.name: c for c in validate_dataset("smoke-tamper", smoke)}
    assert not checks["generate_checksums"].passed
    assert not checks["raw_replay_scoring"].passed or not checks["score_support"].passed


def test_invalid_partition_config_rejected():
    with pytest.raises(DatasetError, match="positive integer"):
        replace(
            profile("smoke"),
            partition_counts={"train": 40, "validation_tune": 0, "validation_calibration": 0, "test": 0},
        ).validate()


def test_target_context_never_reaches_x(smoke):
    obs = {o["observation_id"]: o for o in load(smoke, "smoke-a", "observations.jsonl")}
    params = exports.read_json(dataset_dir("smoke-a", smoke) / "preprocessing.json")
    window = next(w for w in windows_of(smoke) if w["supervised"])
    before = build_tensors([window], obs, params)["X"]
    changed = copy.deepcopy(obs)
    target = changed[window["target_observation_id"]]
    target.update(sleep_hours=0.0, mood_score=1, medication_change="YES")
    assert np.array_equal(build_tensors([window], changed, params)["X"], before)


def test_fit_ignores_held_out_values(smoke):
    obs = {o["observation_id"]: o for o in load(smoke, "smoke-a", "observations.jsonl")}
    windows = windows_of(smoke)
    train_clean = [w for w in windows if w["partition"] == "train" and w["supervised"] and w["clean"]]
    base = fit(obs, train_clean)
    changed = copy.deepcopy(obs)
    for w in windows:
        if w["partition"] == "test" and w["supervised"]:
            for i in [*w["input_observation_ids"], w["target_observation_id"]]:
                changed[i].update(memory_score=0.0, sleep_hours=24.0)
    assert fit(changed, train_clean) == base


@pytest.mark.parametrize(
    "medication,expected",
    [(None, (0.0, 1.0)), ("NOT_SURE", (0.0, 1.0)), ("NO", (0.0, 0.0)), ("YES", (1.0, 0.0))],
)
def test_medication_encoding(smoke, medication, expected):
    params = exports.read_json(dataset_dir("smoke-a", smoke) / "preprocessing.json")
    row = feature_row(
        {
            "memory_score": 50.0,
            "attention_score": 80.0,
            "reaction_time_ms": 600.0,
            "sleep_hours": None,
            "mood_score": 5,
            "medication_change": medication,
        },
        params,
    )
    assert (row[5], row[8]) == expected
    assert row[6] == 1.0 and row[7] == 0.0  # sleep missing mask, mood present


def test_cognition_is_never_imputed(smoke):
    params = exports.read_json(dataset_dir("smoke-a", smoke) / "preprocessing.json")
    with pytest.raises(DatasetError, match="never imputed"):
        feature_row(
            {
                "memory_score": None,
                "attention_score": 80.0,
                "reaction_time_ms": 600.0,
                "sleep_hours": 7,
                "mood_score": 5,
                "medication_change": "NO",
            },
            params,
        )


def _fixture_windows(root):
    truth = {
        t["patient_id"]: t["scenario"]
        for t in load(root, "smoke-a", "fixtures/truth.jsonl")
        if t["kind"] == "patient"
    }
    by = {}
    for w in load(root, "smoke-a", "windows/fixtures.jsonl"):
        by.setdefault(truth[w["patient_id"]], []).append(w)
    return by


def test_fixture_catalog_exclusions(smoke):
    fx = _fixture_windows(smoke)
    reasons = {name: {w["exclusion_reason"] for w in ws} for name, ws in fx.items()}
    assert (
        "HISTORY_GAP" in reasons["fixture_missing_week"]
        and "MISSING_TARGET" in reasons["fixture_missing_week"]
    )
    assert "LATE_AVAILABILITY" in reasons["fixture_late_submission"]
    assert "EXTRA_ATTEMPT" in reasons["fixture_extra_after_valid"]
    assert "LOW_QUALITY_TARGET" in reasons["fixture_rt_timeouts"]
    assert "INCOMPLETE_TARGET" in reasons["fixture_skipped_task"]
    assert "LOW_QUALITY_TARGET" in reasons["fixture_event_hidden_by_quality"]
    # A device or input-mode change starts a new segment: 6 matching representatives are needed again.
    for name in ("fixture_device_change", "fixture_input_mode_switch"):
        assert sum(w["exclusion_reason"] == "COMPARABILITY_CHANGE" for w in fx[name]) == 6
    # Extra attempts never add weekly slots.
    assert (
        sum(w["kind"] == "slot" for w in fx["fixture_extra_after_valid"])
        == profile("smoke").slots_per_patient
    )


def test_retake_becomes_representative_and_first_valid_wins(smoke):
    obs = load(smoke, "smoke-a", "fixtures/observations.jsonl")
    truth = {
        t["patient_id"]: t["scenario"]
        for t in load(smoke, "smoke-a", "fixtures/truth.jsonl")
        if t["kind"] == "patient"
    }
    retake_patient = next(p for p, s in truth.items() if s == "fixture_hidden_tab_and_retake")
    slot = next(o["slot_index"] for o in obs if o["patient_id"] == retake_patient and o["attempt"] == 1)
    attempts = sorted(
        (o for o in obs if o["patient_id"] == retake_patient and o["slot_index"] == slot),
        key=lambda o: o["attempt"],
    )
    assert [a["quality"] for a in attempts] == ["LOW", "VALID"]
    assert [a["representative"] for a in attempts] == [False, True]
    extra_patient = next(p for p, s in truth.items() if s == "fixture_extra_after_valid")
    extras = [o for o in obs if o["patient_id"] == extra_patient and o["schedule_purpose"] == "EXTRA_ATTEMPT"]
    assert extras and not any(o["representative"] for o in extras)


def test_report_keeps_hidden_events_in_denominator(smoke):
    report = build_report("smoke-a", smoke)
    ev = report["events"]
    hidden = sum(ev["hidden_event_target_slots_by_reason"].values())
    assert ev["analyzable_event_target_slots"] + hidden == ev["performance_event_target_slots"]
    assert report["label_shortcut_probes"]["no_deterministic_shortcut"] is True
    assert report["smoke_profile"] is True


# --- demo import (database) ---------------------------------------------------------------------


@pytest.fixture
def demo_files(tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "demo_patients": [
                    {
                        "demo_key": "eleanor",
                        "patient_email": "eleanor.park@demo.test",
                        "scenario": "stable",
                        "history_slots": 8,
                    },
                    {
                        "demo_key": "henry",
                        "patient_email": "henry.lin@demo.test",
                        "scenario": "insufficient_data",
                        "history_slots": 8,
                    },
                    {
                        "demo_key": "walter",
                        "patient_email": "walter.hughes@demo.test",
                        "scenario": "single_deviation",
                        "history_slots": 8,
                    },
                ]
            }
        )
    )
    root = tmp_path / "demo"
    prepare_demo("demo-t", mapping, root=root)
    return root


def test_demo_import_is_idempotent_and_feeds_live_forecast_state(
    client, seeded, login_as, db_session, demo_files
):
    from sqlalchemy import select

    from app.models import AssessmentSession, PatientProfile, User

    # Walter already has an unrelated live session: he must be skipped, not overwritten.
    walter = login_as("walter.hughes@demo.test")
    body = {
        "start_key": "11111111-1111-1111-1111-111111111111",
        "input_mode": "keyboard",
        "device_changed": False,
        "navigation_assistance": False,
        "allow_unscheduled": False,
    }
    assert client.post("/api/v1/patient/assessment-sessions", json=body, headers=walter).status_code == 201

    first = import_demo(db_session, "demo-t", demo_files)
    assert first[0].startswith("eleanor") and "8 session(s) imported" in first[0]
    assert "7 session(s) imported" in first[1]  # henry: one missing week
    assert "SKIPPED" in first[2]
    again = import_demo(db_session, "demo-t", demo_files)
    assert "0 session(s) imported, 8 already present" in again[0]

    eleanor_id = db_session.scalar(
        select(PatientProfile.id).join(User).where(User.email == "eleanor.park@demo.test")
    )
    imported = db_session.scalars(
        select(AssessmentSession).where(AssessmentSession.patient_id == eleanor_id)
    ).all()
    assert {s.source for s in imported} == {"SYNTHETIC_HISTORY"}
    assert all(s.assessment.analysis_state in ("BUILDING_BASELINE", "MODEL_UNAVAILABLE") for s in imported)
    assert all(s.assessment.processing_status == "ANALYZED" for s in imported)

    # The synthetic anchor puts the next weekly target in the real current window.
    eleanor = login_as("eleanor.park@demo.test")
    status = client.get("/api/v1/patient/assessment-status", headers=eleanor).json()
    assert status["schedule"]["scheduled_start_allowed"] is True
    live = client.post(
        "/api/v1/patient/assessment-sessions",
        json={**body, "start_key": "22222222-2222-2222-2222-222222222222"},
        headers=eleanor,
    )
    assert live.status_code == 201 and live.json()["schedule"]["slot_index"] == 8
    frozen = db_session.get(AssessmentSession, uuid.UUID(live.json()["session_id"]))
    assert frozen.forecast_state == "MODEL_UNAVAILABLE"  # six consecutive reps, no model yet

    henry = login_as("henry.lin@demo.test")
    live_h = client.post(
        "/api/v1/patient/assessment-sessions",
        json={**body, "start_key": "33333333-3333-3333-3333-333333333333"},
        headers=henry,
    )
    frozen_h = db_session.get(AssessmentSession, uuid.UUID(live_h.json()["session_id"]))
    assert frozen_h.forecast_state == "INSUFFICIENT_DATA" and "HISTORY_GAP" in frozen_h.forecast_reasons


def test_demo_import_conflict_on_changed_payload(seeded, db_session, demo_files):
    from sqlalchemy import select

    from app.models import Assessment

    import_demo(db_session, "demo-t", demo_files)
    a = db_session.scalars(select(Assessment)).first()
    a.payload_sha256 = "f" * 64
    db_session.flush()
    with pytest.raises(DatasetError, match="conflict"):
        import_demo(db_session, "demo-t", demo_files)


def test_demo_mapping_rejects_real_looking_accounts(tmp_path):
    mapping = tmp_path / "m.json"
    mapping.write_text(
        json.dumps(
            {
                "demo_patients": [
                    {
                        "demo_key": "x",
                        "patient_email": "someone@example.com",
                        "scenario": "stable",
                        "history_slots": 8,
                    }
                ]
            }
        )
    )
    with pytest.raises(DatasetError, match="fictional"):
        prepare_demo("demo-bad", mapping, root=tmp_path / "demo")
