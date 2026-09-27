"""Dataset contract checks (guide 03 §18). Each returns a named pass/fail with concise evidence.

`check_generated` runs inside `generate` before the stage is marked COMPLETE; `check_prepared`
runs inside `prepare`. `validate_dataset` (CLI) re-runs both plus checksum verification.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.data import exports
from app.ml.data.config import PARTITIONS, DatasetError, config_from_dict
from app.ml.data.preprocessing import FEATURE_SOURCE_FIELDS, X_CHANNELS, Y_CHANNELS, feature_row, fit, inverse_targets
from app.models import MedicationChange, Quality, SchedulePurpose
from app.ml.data.legacy_payload import upgrade_v1_payload
from app.schemas.assessments import AssessmentSubmission
from app.services import schedule
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION
from app.services.scoring import score_submission

MEMORY_SUPPORT = {round(100 * k / 6, 3) for k in range(7)}
TRUTH_ONLY_FIELDS = {
    "scenario", "event_id", "event_kind", "event_active", "performance_event_active", "latent",
    "latent_params", "trajectory", "hidden_context", "quality_fault_kind", "event",
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _utc(value: str) -> bool:
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return ts.utcoffset() == timedelta(0)


def _num(v: Any) -> bool:
    return v is None or (isinstance(v, int | float) and math.isfinite(v))


def _dec(v: Decimal | None) -> float | None:
    return None if v is None else float(v)


def _group(root: Path, prefix: str = "") -> dict[str, list[dict[str, Any]]]:
    return {
        "raw": list(exports.read_jsonl(root / f"{prefix}raw_sessions.jsonl.gz")),
        "obs": list(exports.read_jsonl(root / f"{prefix}observations.jsonl")),
        "truth": list(exports.read_jsonl(root / f"{prefix}truth.jsonl")),
    }


def check_generated(root: Path) -> list[Check]:
    manifest = exports.read_json(root / "manifest.json")
    config = config_from_dict(manifest["config"])
    main, fixtures = _group(root), _group(root, "fixtures/")
    patients = list(exports.read_jsonl(root / "patients.jsonl"))
    checks: list[Check] = []

    # Raw replay scoring: canonical scorer reproduces every exported score and quality.
    legacy = manifest["versions"].get("dataset_schema") == "dataset_schema_v1"
    mismatches, total = [], 0
    for group in (main, fixtures):
        by_id = {o["observation_id"]: o for o in group["obs"]}
        for r in group["raw"]:
            total += 1
            raw = upgrade_v1_payload(r["raw_submission"]) if legacy else r["raw_submission"]
            sub = AssessmentSubmission.model_validate(raw)
            res = score_submission(r["protocol_snapshot"], sub, r["input_mode"])
            o = by_id[r["observation_id"]]
            got = (_dec(res.memory.score), _dec(res.attention.score), _dec(res.reaction.score), res.quality.value)
            want = (o["memory_score"], o["attention_score"], o["reaction_time_ms"], o["quality"])
            if got != want:
                mismatches.append(r["observation_id"])
    checks.append(Check("raw_replay_scoring", not mismatches,
                        f"{total} sessions re-scored{' (v1 payloads upgraded)' if legacy else ''}, "
                        f"{len(mismatches)} mismatches"))

    all_obs = main["obs"] + fixtures["obs"]
    bad_support = []
    for o in all_obs:
        m, a, rt = o["memory_score"], o["attention_score"], o["reaction_time_ms"]
        att = o["task_status"]["attention"]["counters"]
        if m is not None and m not in MEMORY_SUPPORT:
            bad_support.append((o["observation_id"], "memory"))
        if a is not None and (abs(a - 50 * (att["hits"] / 10 + att["correct_rejections"] / 20)) > 1e-9 or (a / 2.5) % 1):
            bad_support.append((o["observation_id"], "attention"))
        if rt is not None and not (100 <= rt < 3000):
            bad_support.append((o["observation_id"], "reaction"))
        if o["quality"] == Quality.VALID and None in (m, a, rt):
            bad_support.append((o["observation_id"], "valid_missing_score"))
    checks.append(Check("score_support", not bad_support, f"{len(all_obs)} observations; violations: {bad_support[:5]}"))

    ids = [o["observation_id"] for o in all_obs]
    sids = [o["session_id"] for o in all_obs]
    problems = []
    if len(ids) != len(set(ids)) or len(sids) != len(set(sids)):
        problems.append("duplicate ids")
    purposes = {p.value for p in SchedulePurpose}
    meds = {m.value for m in MedicationChange}
    for o in all_obs:
        if o["quality"] not in {q.value for q in Quality} or o["schedule_purpose"] not in purposes:
            problems.append(f"enum {o['observation_id']}")
        if o["medication_change"] not in meds | {None}:
            problems.append(f"medication enum {o['observation_id']}")
        if not all(_utc(o[k]) for k in ("target_at", "session_started_at", "observed_at", "available_at")):
            problems.append(f"timestamp {o['observation_id']}")
        if not all(_num(o[k]) for k in ("memory_score", "attention_score", "reaction_time_ms", "sleep_hours", "mood_score")):
            problems.append(f"non-finite {o['observation_id']}")
        if (o["protocol_version"], o["scoring_version"]) != (PROTOCOL_VERSION, SCORING_VERSION):
            problems.append(f"unknown protocol {o['observation_id']}")
        nulls = {f for f in ("sleep_hours", "mood_score", "medication_change") if o[f] is None}
        if nulls != {m["field"] for m in o["missing_context"]}:
            problems.append(f"missingness mismatch {o['observation_id']}")
        if set(o) & TRUTH_ONLY_FIELDS:
            problems.append(f"truth field leaked {o['observation_id']}")
    checks.append(Check("integrity", not problems, f"{len(all_obs)} observations; problems: {problems[:5]}"))

    # Hidden original context values live only in truth.
    leaks = 0
    obs_by_id = {o["observation_id"]: o for o in all_obs}
    for t in main["truth"] + fixtures["truth"]:
        if t["kind"] == "observation":
            leaks += sum(1 for f in t["hidden_context"] if obs_by_id[t["observation_id"]][f] is not None)
    checks.append(Check("masked_context_only_in_truth", leaks == 0, f"{leaks} masked values visible in observations"))

    # Split isolation.
    fam_parts: dict[str, set[str]] = defaultdict(set)
    for p in patients:
        fam_parts[p["family_id"]].add(p["partition"])
    counts = {part: sum(1 for p in patients if p["partition"] == part) for part in PARTITIONS}
    fixture_patients = {o["patient_id"] for o in fixtures["obs"]}
    main_patients = {p["patient_id"] for p in patients}
    split_ok = (
        all(len(v) == 1 for v in fam_parts.values())
        and counts == config.partition_counts
        and {o["patient_id"] for o in main["obs"]} <= main_patients
        and not fixture_patients & main_patients
    )
    checks.append(Check("split_isolation", split_ok, f"partition counts {counts}; fixtures disjoint={not fixture_patients & main_patients}"))

    # Representatives follow the shared rule; extras never become representatives.
    rep_problems = []
    for group in (main["obs"], fixtures["obs"]):
        by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in group:
            by_patient[o["patient_id"]].append(o)
        for rows in by_patient.values():
            expected = schedule.select_representatives(
                [schedule.SubmissionRef(o["observation_id"], o["slot_index"], o["schedule_purpose"], o["quality"],
                                        datetime.fromisoformat(o["available_at"])) for o in rows]
            )
            actual = {o["slot_index"]: o["observation_id"] for o in rows if o["representative"]}
            if expected != actual or len([o for o in rows if o["representative"]]) != len(actual):
                rep_problems.append(rows[0]["patient_id"])
    checks.append(Check("representatives", not rep_problems, f"{len(rep_problems)} patients with rule violations"))
    return checks


def _view_windows(windows: list[dict[str, Any]], partition: str, clean_only: bool) -> list[dict[str, Any]]:
    return [w for w in windows if w["kind"] == "slot" and w["supervised"] and w["partition"] == partition and (w["clean"] or not clean_only)]


def check_prepared(root: Path) -> list[Check]:
    from app.ml.data.pipeline import VIEWS

    observations = list(exports.read_jsonl(root / "observations.jsonl"))
    obs_by_id = {o["observation_id"]: o for o in observations}
    windows = [w for part in PARTITIONS for w in exports.read_jsonl(root / f"windows/{part}.jsonl")]
    params = exports.read_json(root / "preprocessing.json")
    checks: list[Check] = []

    # Temporal boundary: inputs are exactly the representatives of slots k-6..k-1, available by cutoff.
    temporal = []
    for w in windows:
        if not w["forecast_eligible"]:
            if w["input_observation_ids"]:
                temporal.append(w["window_id"])
            continue
        inputs = [obs_by_id[i] for i in w["input_observation_ids"]]
        cutoff = datetime.fromisoformat(w["forecast_cutoff"])
        k = w["target_slot"]
        if (
            [o["slot_index"] for o in inputs] != list(range(k - 6, k))
            or not all(o["representative"] and datetime.fromisoformat(o["available_at"]) <= cutoff for o in inputs)
            or w["target_observation_id"] in w["input_observation_ids"]
            or len({o["comparability_key"] for o in inputs}) != 1
        ):
            temporal.append(w["window_id"])
    checks.append(Check("temporal_boundary", not temporal, f"{sum(w['forecast_eligible'] for w in windows)} eligible windows; {len(temporal)} violations"))

    # Feature schema: allow-listed sources only, fixed channel order.
    schema_ok = (
        params["feature_source_fields"] == list(FEATURE_SOURCE_FIELDS)
        and params["x_channels"] == list(X_CHANNELS)
        and params["y_channels"] == list(Y_CHANNELS)
        and not set(params["feature_source_fields"]) & TRUTH_ONLY_FIELDS
    )
    checks.append(Check("no_labels_in_x", schema_ok, f"X channels {len(X_CHANNELS)}: {', '.join(X_CHANNELS)}"))

    # Train-only fit: refitting from train_clean reproduces the stored parameters exactly.
    train_clean = _view_windows(windows, "train", True)
    refit = fit(obs_by_id, train_clean)
    checks.append(Check("train_only_fit", refit == params and all(w["partition"] == "train" for w in train_clean),
                        f"fitted on {params['fit_population']}"))

    tensor_problems, roundtrip, masks = [], [], 0
    for name, (partition, clean_only) in VIEWS.items():
        data = exports.load_npz(root / f"tensors/{name}.npz")
        expected = _view_windows(windows, partition, clean_only)
        X, y, y_raw, ids = data["X"], data["y"], data["y_raw"], data["window_ids"]
        n = len(expected)
        if X.shape != (n, 6, 9) or y.shape != (n, 3) or y_raw.shape != (n, 3) or ids.shape != (n,):
            tensor_problems.append(f"{name} shapes")
        if X.dtype != np.float32 or y.dtype != np.float32 or y_raw.dtype != np.float64 or ids.dtype.kind != "U":
            tensor_problems.append(f"{name} dtypes")
        if not (np.isfinite(X).all() and np.isfinite(y).all()):
            tensor_problems.append(f"{name} non-finite")
        if list(ids) != [w["window_id"] for w in expected]:
            tensor_problems.append(f"{name} order")
        err = np.abs(inverse_targets(y, params) - y_raw)
        if (err[:, :2] > 1e-3).any() or (err[:, 2] > 1e-2).any():
            roundtrip.append(f"{name} max err {err.max(axis=0).tolist()}")
        for i, w in enumerate(expected):
            for t, oid in enumerate(w["input_observation_ids"]):
                o = obs_by_id[oid]
                row = X[i, t]
                if row[6] != float(o["sleep_hours"] is None) or row[7] != float(o["mood_score"] is None):
                    masks += 1
                med = o["medication_change"]
                if (row[5], row[8]) != ((1.0, 0.0) if med == "YES" else (0.0, 0.0) if med == "NO" else (0.0, 1.0)):
                    masks += 1
                if not np.allclose(row, np.float32(feature_row(o, params))):
                    masks += 1
    checks.append(Check("tensor_contract", not tensor_problems, f"views {list(VIEWS)}; problems: {tensor_problems}"))
    checks.append(Check("transform_round_trip", not roundtrip, "abs tol 1e-3 scores, 1e-2 ms RT (float32 y)" + (f"; {roundtrip}" if roundtrip else "")))
    checks.append(Check("missingness_encoding", masks == 0, f"{masks} rows with wrong value/mask encoding"))

    # Cognition gaps exclude windows (never zero-filled): every eligible input has all three scores.
    gaps = sum(1 for w in windows if w["forecast_eligible"] for i in w["input_observation_ids"]
               if None in (obs_by_id[i]["memory_score"], obs_by_id[i]["attention_score"], obs_by_id[i]["reaction_time_ms"]))
    checks.append(Check("cognition_gaps_excluded", gaps == 0, f"{gaps} eligible inputs lacking a domain score"))
    return checks


def validate_dataset(dataset_id: str, root: Path | None = None) -> list[Check]:
    from app.ml.data.pipeline import load_manifest, verify_stage

    path, manifest = load_manifest(dataset_id, root)
    checks: list[Check] = []
    for stage in ("generate", "prepare"):
        if manifest["stages"].get(stage, {}).get("status") == "COMPLETE":
            try:
                verify_stage(path, manifest, stage)
                checks.append(Check(f"{stage}_checksums", True, f"{len(manifest['stages'][stage]['files'])} files match"))
            except DatasetError as exc:
                checks.append(Check(f"{stage}_checksums", False, str(exc)))
    checks += check_generated(path)
    if manifest["stages"].get("prepare", {}).get("status") == "COMPLETE":
        checks += check_prepared(path)
    return checks


def require(checks: list[Check]) -> None:
    failed = [c for c in checks if not c.passed]
    if failed:
        raise DatasetError("validation failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failed))
