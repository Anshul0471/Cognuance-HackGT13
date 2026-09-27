"""Offline experiment stages: train → select → calibrate → evaluate (guide 04 §2, §6–§9, §12, §17, §18).

Each stage lives in `artifacts/runs/<run_id>/`, checks the previous stage's manifest and checksums,
and records its own files. A COMPLETE stage is reused, never silently re-run as a different
experiment. The test partition is read only by `evaluate_run`, after model and policy are frozen.
"""

import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch

from app.core.config import get_settings
from app.ml.data import exports
from app.ml.data.config import DatasetError, config_from_dict, dataset_dir
from app.ml.data.pipeline import performance_slots, verify_stage
from app.ml.data.windows import build_windows
from app.ml.models import ENGINE_VERSION, calibration, gru
from app.ml.models.anomaly import THRESHOLD_GRID
from app.ml.models.baselines import BASELINE_VERSIONS, FORMULAS
from app.ml.models.datasets import (
    Dataset,
    View,
    external_view,
    load_view,
    open_dataset,
    partition_slot_windows,
    truth_patients,
)
from app.ml.models.evaluation import alert_metrics, replay
from app.ml.models.forecasting import KINDS, SIMPLICITY_ORDER, predict_batch
from app.ml.models.metrics import summarize
from app.ml.models.postprocessing import POSTPROCESSING_VERSION, Prediction, as_array, bound_rates
from app.ml.models.training import train_gru

TIE_RELATIVE = 0.01
TRAIN_FILES = (
    "preprocessing.json",
    "candidates/GRU/model_config.json",
    "candidates/GRU/weights.pt",
    "candidates/GRU/training_report.json",
    "candidates/LAST_VALUE/model_config.json",
    "candidates/LINEAR_TREND/model_config.json",
)


class RunError(RuntimeError):
    pass


def artifact_root(root: Path | None = None) -> Path:
    return (root or get_settings().MODEL_ARTIFACT_DIR).resolve()


def run_path(run_id: str, root: Path | None = None) -> Path:
    try:
        return dataset_dir(run_id, artifact_root(root) / "runs")
    except DatasetError as exc:
        raise RunError(str(exc).replace("dataset", "run")) from None


def model_version_for(run_id: str, kind: str) -> str:
    version = f"{run_id}-{kind.lower().replace('_', '-')}"
    if len(version) > 64:
        raise RunError("run id too long to derive a model version (max 64 chars)")
    return version


def load_run(run_id: str, root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = run_path(run_id, root)
    if not (path / "run.json").exists():
        raise RunError(f"no run {run_id!r}; run train_forecasters first")
    return path, exports.read_json(path / "run.json")


def _require(manifest: dict[str, Any], stage: str, key: str | None = None) -> dict[str, Any]:
    st = manifest["stages"].get(stage, {})
    if key is not None:
        st = st.get(key, {})
    if st.get("status") != "COMPLETE":
        raise RunError(f"stage {stage}{'/' + key if key else ''} is not COMPLETE")
    return st


def _verify(path: Path, files: dict[str, str]) -> None:
    actual = exports.file_hashes(path, files)
    bad = [n for n in files if files[n] != actual[n]]
    if bad:
        raise RunError(f"checksum mismatch in run files: {bad}")


def _dataset_for(manifest: dict[str, Any], data_root: Path | None) -> Dataset:
    ds = open_dataset(manifest["dataset"]["dataset_id"], data_root)
    if ds.reference() != manifest["dataset"]:
        raise RunError("the dataset changed since this run was trained; start a new run id")
    return ds


def load_gru(run: Path) -> gru.CognitiveForecaster:
    config = exports.read_json(run / "candidates/GRU/model_config.json")
    model = gru.build_model(config)
    state = torch.load(run / "candidates/GRU/weights.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def baseline_config(kind: str, sequence_length: int = 6) -> dict[str, Any]:
    return {
        "kind": kind,
        "engine_version": ENGINE_VERSION,
        "baseline_version": BASELINE_VERSIONS[kind],
        "formula": FORMULAS[kind],
        "learned_parameters": False,
        "uses_context": False,
        "history_fields": ["memory_score", "attention_score", "reaction_time_ms"],
        "sequence_length": sequence_length,
        "device": "cpu",
        "preprocessing_version": "preprocessing_v1",
        "postprocessing_version": POSTPROCESSING_VERSION,
    }


# ----------------------------------------------------------------------------------------- train


def train_run(
    dataset_id: str,
    run_id: str,
    *,
    root: Path | None = None,
    data_root: Path | None = None,
    settings: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    ds = open_dataset(dataset_id, data_root)
    final = run_path(run_id, root)
    if final.exists():
        _, manifest = load_run(run_id, root)
        st = _require(manifest, "train")
        if manifest["dataset"] != ds.reference():
            raise RunError("run id already used with a different dataset; choose a new run id")
        _verify(final, st["files"])
        return final, "reused"

    train, tune = load_view(ds, "train_clean"), load_view(ds, "validation_tune_clean")
    state, report = train_gru(train, tune, ds.params, settings)
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = final.parent / f".{run_id}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        (tmp / "candidates/GRU").mkdir(parents=True)
        shutil.copyfile(ds.path / "preprocessing.json", tmp / "preprocessing.json")  # copied unchanged
        torch.save(state, tmp / "candidates/GRU/weights.pt")
        exports.write_json(
            tmp / "candidates/GRU/model_config.json",
            {
                "kind": "GRU",
                "engine_version": ENGINE_VERSION,
                **gru.architecture_config(report["settings"]["hidden_size"]),
                "learned_parameters": True,
                "uses_context": True,
                "device": "cpu",
                "weights_file": "weights.pt",
                "weights_format": "torch state_dict (load with weights_only=True)",
                "preprocessing_version": ds.params["preprocessing_version"],
                "postprocessing_version": POSTPROCESSING_VERSION,
            },
        )
        exports.write_json(
            tmp / "candidates/GRU/training_report.json",
            {"kind": "GRU", "run_id": run_id, "dataset": ds.reference(), **report},
        )
        for kind in ("LAST_VALUE", "LINEAR_TREND"):
            exports.write_json(tmp / f"candidates/{kind}/model_config.json", baseline_config(kind))
        files = exports.file_hashes(tmp, TRAIN_FILES)
        exports.write_json(
            tmp / "run.json",
            {
                "run_id": run_id,
                "engine_version": ENGINE_VERSION,
                "synthetic": True,
                "dataset": ds.reference(),
                "activatable_profile": ds.profile == "full",
                "activatable_note": "Only a full-profile dataset can produce activatable artifacts; "
                "smoke runs are fixture mode.",
                "source_revision": exports.source_revision(),
                "stages": {
                    "train": {
                        "status": "COMPLETE",
                        "completed_at": exports.now_iso(),
                        "files": files,
                        "gru_selected_epoch": report["selected_epoch"],
                        "gru_tune_selection_metric": report["selected_tune_selection_metric"],
                    }
                },
            },
        )
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final, "created"


# ---------------------------------------------------------------------------------------- select


def _predict(kind: str, view: View, params: dict[str, Any], model: Any) -> tuple[list[Prediction], float]:
    t0 = time.perf_counter()
    preds = predict_batch(kind, view.X, view.history_raw, params, model if kind == "GRU" else None)
    return preds, time.perf_counter() - t0


def _window_digest(view: View) -> str:
    import hashlib

    return hashlib.sha256("\n".join(view.window_ids).encode()).hexdigest()


def choose_candidate(metrics: dict[str, float]) -> dict[str, Any]:
    """Lowest metric; candidates within 1% relative of a nonzero best are tied → simplest wins."""
    best = min(metrics.values())
    if best == 0:
        tied = [k for k, v in metrics.items() if v == 0]
    else:
        tied = [k for k, v in metrics.items() if (v - best) / best <= TIE_RELATIVE]
    selected = min(tied, key=lambda k: SIMPLICITY_ORDER[k])
    return {
        "metric_values": metrics,
        "best_metric": best,
        "best_kind": min(metrics, key=lambda k: (metrics[k], SIMPLICITY_ORDER[k])),
        "tie_rule": "within 1% relative of the best nonzero metric are practically tied "
        "(exact zero only if best is 0); "
        "prefer LAST_VALUE, then LINEAR_TREND, then GRU",
        "tied": sorted(tied, key=lambda k: SIMPLICITY_ORDER[k]),
        "selected_kind": selected,
        "note": "Engineering selection rule on validation-tune data, not a statistical superiority claim.",
    }


def select_run(run_id: str, *, root: Path | None = None, data_root: Path | None = None) -> tuple[Path, str]:
    path, manifest = load_run(run_id, root)
    _verify(path, _require(manifest, "train")["files"])
    if manifest["stages"].get("select", {}).get("status") == "COMPLETE":
        _verify(path, manifest["stages"]["select"]["files"])
        return path, "reused"
    ds = _dataset_for(manifest, data_root)
    model = load_gru(path)
    params = exports.read_json(path / "preprocessing.json")

    candidates: dict[str, dict[str, Any]] = {k: {} for k in KINDS}
    same_targets = {}
    for view_name in ("validation_tune_clean", "validation_tune_all"):
        view = load_view(ds, view_name)
        same_targets[view_name] = {"n_windows": len(view), "window_ids_sha256": _window_digest(view)}
        for kind in KINDS:
            preds, secs = _predict(kind, view, params, model)
            candidates[kind][view_name] = {
                **summarize(as_array(preds), view.y_raw, view.patient_ids, params["target_stats"]),
                "prediction_bounds": bound_rates(preds),
                "runtime_seconds": round(secs, 4),
            }
    decision = choose_candidate(
        {k: candidates[k]["validation_tune_clean"]["selection_metric"] for k in KINDS}
    )
    best_baseline = min(
        candidates[k]["validation_tune_clean"]["selection_metric"] for k in ("LAST_VALUE", "LINEAR_TREND")
    )
    gru_metric = candidates["GRU"]["validation_tune_clean"]["selection_metric"]
    decision["gru_vs_best_baseline"] = {
        "gru_metric": gru_metric,
        "best_baseline_metric": best_baseline,
        "relative_change": round((gru_metric - best_baseline) / best_baseline, 6) if best_baseline else None,
        "gru_lower_error": gru_metric < best_baseline,
    }
    selected = decision["selected_kind"]
    doc = {
        "run_id": run_id,
        "dataset": manifest["dataset"],
        "selection_view": "validation_tune_clean",
        "also_reported": ["validation_tune_all (injected changes; not used to choose)"],
        "selection_metric": "patient-macro mean of per-domain MAE in target-standardized coordinates, after "
        "prediction_postprocess_v1",
        "same_targets": same_targets,
        "candidates": candidates,
        "decision": decision,
        "selected_model_version": model_version_for(run_id, selected),
        "test_data_used": False,
    }
    exports.write_json(path / "forecast_evaluation.json", doc)
    manifest["stages"]["select"] = {
        "status": "COMPLETE",
        "completed_at": exports.now_iso(),
        "selected_kind": selected,
        "selected_model_version": model_version_for(run_id, selected),
        "files": exports.file_hashes(path, ["forecast_evaluation.json"]),
    }
    exports.atomic_write_json(path / "run.json", manifest)
    return path, "created"


# ------------------------------------------------------------------------------------- calibrate


def _frozen_candidate(path: Path, manifest: dict[str, Any]) -> tuple[str, Any, dict[str, Any]]:
    sel = _require(manifest, "select")
    _verify(path, manifest["stages"]["train"]["files"])
    _verify(path, sel["files"])
    kind = sel["selected_kind"]
    return kind, load_gru(path) if kind == "GRU" else None, exports.read_json(path / "preprocessing.json")


def _observed(view: View) -> dict[str, tuple[float, float, float]]:
    return {wid: tuple(float(v) for v in row) for wid, row in zip(view.window_ids, view.y_raw, strict=True)}


def calibrate_run(
    run_id: str, policy_version: str, *, root: Path | None = None, data_root: Path | None = None
) -> tuple[Path, str]:
    path, manifest = load_run(run_id, root)
    try:
        pdir = dataset_dir(policy_version, path / "policies")
    except DatasetError:
        raise RunError("policy version must match [a-z0-9][a-z0-9._-]{0,63}") from None
    existing = manifest["stages"].get("calibrate", {}).get(policy_version)
    if existing and existing.get("status") in ("COMPLETE", "FAILED"):
        _verify(path, existing["files"])
        return pdir, "reused"
    kind, model, params = _frozen_candidate(path, manifest)
    ds = _dataset_for(manifest, data_root)
    model_version = model_version_for(run_id, kind)

    cal_clean = load_view(ds, "validation_calibration_clean")
    clean_preds, _ = _predict(kind, cal_clean, params, model)
    scales = calibration.fit_scales(as_array(clean_preds), cal_clean.y_raw)
    n_cal_patients = len(set(cal_clean.patient_ids))
    data_sufficient = (
        len(cal_clean) >= calibration.MIN_CALIBRATION_WINDOWS
        and n_cal_patients >= calibration.MIN_CALIBRATION_PATIENTS
    )

    cal_all = load_view(ds, "validation_calibration_all")
    all_preds, _ = _predict(kind, cal_all, params, model)
    predictions = dict(zip(cal_all.window_ids, all_preds, strict=True))
    slot_windows = partition_slot_windows(ds, "validation_calibration")
    truth = truth_patients(ds.path)
    candidates = []
    for r in THRESHOLD_GRID:
        rows = replay(slot_windows, predictions, _observed(cal_all), calibration.rules_for(scales, r))
        candidates.append({"r": r, "metrics": alert_metrics(rows, slot_windows, truth)})
    selected_r, decision = calibration.select_threshold(candidates)
    if not data_sufficient:
        decision = "INSUFFICIENT_CALIBRATION_DATA"
    activatable = bool(manifest["activatable_profile"] and data_sufficient and decision == "SELECTED")
    fixture_mode = not manifest["activatable_profile"]
    policy_r = selected_r
    if policy_r is None and fixture_mode:
        policy_r = 2.0  # guide 04 §13 fixture constant: exercises calculations only; never activatable
    if activatable is False and not fixture_mode:
        policy_r = None  # a failed full-profile calibration writes no serving policy

    report = {
        "policy_version": policy_version,
        "model_version": model_version,
        "model_kind": kind,
        "scale_view": "validation_calibration_clean",
        "threshold_view": "validation_calibration_all (chronological replay)",
        "calibration_windows": len(cal_clean),
        "calibration_patients": n_cal_patients,
        "minimums": {
            "windows": calibration.MIN_CALIBRATION_WINDOWS,
            "patients": calibration.MIN_CALIBRATION_PATIENTS,
            "analyzable_worsening_events": calibration.MIN_WORSENING_EVENTS,
            "max_clean_alert_fraction": calibration.MAX_CLEAN_ALERT_FRACTION,
        },
        "scales": scales,
        "grid": list(THRESHOLD_GRID),
        "candidates": candidates,
        "selection_rule": calibration.SELECTION_RULE,
        "decision": decision,
        "selected_r": selected_r,
        "policy_r": policy_r,
        "mode": "FIXTURE_NON_ACTIVATABLE" if fixture_mode else "FULL",
        "activatable": activatable,
        "test_data_used": False,
        "notes": [
            "The 5% clean-alert objective is an empirical synthetic calibration target, not a guaranteed "
            "false-alert rate or a medical performance standard.",
            "Selecting r on this partition makes these numbers optimistic; only the untouched test set "
            "assesses the frozen selection.",
            "Scales are population-level synthetic forecast-error RMSEs, not patient-specific normal ranges.",
        ],
    }
    pdir.mkdir(parents=True, exist_ok=True)
    exports.write_json(pdir / "calibration_report.json", report)
    names = [f"policies/{policy_version}/calibration_report.json"]
    if policy_r is not None:
        doc = calibration.policy_document(
            policy_version=policy_version,
            model_version=model_version,
            model_kind=kind,
            engine_version=ENGINE_VERSION,
            preprocessing_version=params["preprocessing_version"],
            postprocessing_version=POSTPROCESSING_VERSION,
            scales=scales,
            r=policy_r,
            provenance={
                "run_id": run_id,
                "dataset": manifest["dataset"],
                "decision": decision,
                "mode": report["mode"],
                "activatable": activatable,
            },
        )
        exports.write_json(pdir / "policy.json", doc)
        names.append(f"policies/{policy_version}/policy.json")
    manifest["stages"].setdefault("calibrate", {})[policy_version] = {
        "status": "COMPLETE" if policy_r is not None else "FAILED",
        "completed_at": exports.now_iso(),
        "decision": decision,
        "selected_r": selected_r,
        "activatable": activatable,
        "files": exports.file_hashes(path, names),
    }
    exports.atomic_write_json(path / "run.json", manifest)
    return pdir, "created"


# -------------------------------------------------------------------------------------- evaluate


def _stress_inputs(stress_id: str, params: dict[str, Any], data_root: Path | None):
    """Stress population with the *frozen main* preprocessing (no refit on stress data)."""
    path = dataset_dir(stress_id, data_root)
    manifest = exports.read_json(path / "manifest.json")
    if manifest["stages"].get("generate", {}).get("status") != "COMPLETE":
        raise RunError(f"stress dataset {stress_id!r} is not generated")
    verify_stage(path, manifest, "generate")
    config = config_from_dict(manifest["config"])
    observations = list(exports.read_jsonl(path / "observations.jsonl"))
    truth_rows = list(exports.read_jsonl(path / "truth.jsonl"))
    patients = {p["patient_id"]: p["partition"] for p in exports.read_jsonl(path / "patients.jsonl")}
    windows = build_windows(
        observations,
        patients,
        performance_slots(truth_rows),
        config.slots_per_patient,
        config.history_length,
        manifest["identity"],
        params["preprocessing_version"],
    )
    obs = {o["observation_id"]: o for o in observations}
    slot_windows = sorted(
        (w for w in windows if w["kind"] == "slot"), key=lambda w: (w["patient_id"], w["target_slot"])
    )
    view = external_view("stress_all", windows, obs, params)
    truth = {t["patient_id"]: t for t in truth_rows if t["kind"] == "patient"}
    ref = {
        "dataset_id": stress_id,
        "config_hash": manifest["config_hash"],
        "generate_content_hash": manifest["stages"]["generate"]["content_hash"],
    }
    return view, slot_windows, truth, obs, ref


def _missing_context(view: View, obs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    targets = [obs[w["target_observation_id"]] for w in view.windows]
    n = len(targets)
    return {
        f: {
            "missing": sum(1 for o in targets if o[f] is None),
            "n": n,
            "rate": round(sum(1 for o in targets if o[f] is None) / n, 6) if n else None,
        }
        for f in ("sleep_hours", "mood_score", "medication_change")
    }


def evaluate_run(
    run_id: str,
    partition: str,
    policy_version: str,
    *,
    stress_dataset_id: str = "stress-v1",
    root: Path | None = None,
    data_root: Path | None = None,
) -> tuple[Path, str]:
    if partition not in ("test", "stress"):
        raise RunError("partition must be 'test' or 'stress'")
    path, manifest = load_run(run_id, root)
    cal = _require(manifest, "calibrate", policy_version)
    _verify(path, cal["files"])
    kind, model, params = _frozen_candidate(path, manifest)
    eval_id = f"{partition}-{policy_version}"
    out_dir = path / "reports" / eval_id
    if (out_dir / "test_report.json").exists():
        _verify(path, manifest["stages"]["evaluate"][eval_id]["files"])
        return out_dir, "reused"  # evaluated once; never re-run to chase a better number
    policy = exports.read_json(path / f"policies/{policy_version}/policy.json")
    rules = calibration.rules_for(policy["scales"], policy["rules"]["r"])
    ds = _dataset_for(manifest, data_root)

    if partition == "test":
        view = load_view(ds, "test_all")
        slot_windows = partition_slot_windows(ds, "test")
        truth, obs, data_ref = truth_patients(ds.path), ds.observations, manifest["dataset"]
    else:
        view, slot_windows, truth, obs, data_ref = _stress_inputs(stress_dataset_id, params, data_root)

    t0 = time.perf_counter()
    preds, _ = _predict(kind, view, params, model)
    predict_secs = time.perf_counter() - t0
    pred_arr = as_array(preds)
    clean_idx = [i for i, w in enumerate(view.windows) if w["clean"]]
    pert_idx = [i for i, w in enumerate(view.windows) if not w["clean"]]

    def subset(idx: list[int]) -> dict[str, Any] | None:
        if not idx:
            return None
        return summarize(
            pred_arr[idx], view.y_raw[idx], [view.patient_ids[i] for i in idx], params["target_stats"]
        )

    # Baselines on the same targets, for honest comparison (never used to change the selection).
    comparison = {}
    gru_model = model if kind == "GRU" else load_gru(path)
    for other in KINDS:
        other_model = gru_model
        other_preds = predict_batch(
            other, view.X, view.history_raw, params, other_model if other == "GRU" else None
        )
        comparison[other] = summarize(
            as_array(other_preds), view.y_raw, view.patient_ids, params["target_stats"]
        )

    rows = replay(slot_windows, dict(zip(view.window_ids, preds, strict=True)), _observed(view), rules)
    exclusions = Counter(w["exclusion_reason"] for w in slot_windows if not w["supervised"])
    run_bytes = sum(
        p.stat().st_size
        for p in (path / "candidates" / ("GRU" if kind == "GRU" else kind)).rglob("*")
        if p.is_file()
    )
    report = {
        "evaluation_id": eval_id,
        "partition": partition,
        "data": data_ref,
        "model_version": model_version_for(run_id, kind),
        "model_kind": kind,
        "policy_version": policy_version,
        "policy_r": policy["rules"]["r"],
        "frozen": {"weights_refit": False, "preprocessing_refit": False, "threshold_refit": False},
        "forecast": {
            "all": summarize(pred_arr, view.y_raw, view.patient_ids, params["target_stats"]),
            "clean_history_and_target": subset(clean_idx),
            "perturbed_history_or_target": subset(pert_idx),
            "same_target_comparison": comparison,
            "prediction_bounds": bound_rates(preds),
        },
        "alerts": alert_metrics(rows, slot_windows, truth),
        "coverage": {
            "slot_records": len(slot_windows),
            "forecast_eligible": sum(1 for w in slot_windows if w["forecast_eligible"]),
            "analyzed": len(rows),
            "not_analyzed_by_reason": dict(sorted(exclusions.items())),
            "note": "Missing/LOW/INCOMPLETE targets stay in denominators; "
            "they are never counted as normal negatives.",
        },
        "missing_context_in_analyzed_targets": _missing_context(view, obs),
        "runtime": {
            "prediction_seconds": round(predict_secs, 4),
            "windows": len(view),
            "ms_per_window": round(1000 * predict_secs / max(1, len(view)), 4),
            "environment": exports.environment(),
        },
        "artifact_bytes": run_bytes,
        "limitations": [
            "Synthetic injected-event labels only; results do not establish clinical sensitivity, "
            "specificity or benefit.",
            "Repeated windows from one patient are correlated; no uncertainty intervals are reported.",
            "Severe slowdowns can time out and become unanalyzable rather than alerts (see coverage).",
            "Precision is N/A when there are no alerts; recall is N/A without positive targets.",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    exports.write_jsonl(
        out_dir / "analyses.jsonl",
        [
            {
                "window_id": r.window_id,
                "patient_id": r.patient_id,
                "slot": r.slot,
                "clean": r.clean,
                "level": r.evaluation.level,
                "persistent_count": r.evaluation.persistent_count,
                "max_deviation": r.evaluation.max_deviation,
                "aggregate_deviation": r.evaluation.aggregate_deviation,
                "domains": r.evaluation.domain_json(),
            }
            for r in rows
        ],
    )
    exports.write_json(out_dir / "test_report.json", report)
    names = [f"reports/{eval_id}/test_report.json", f"reports/{eval_id}/analyses.jsonl"]
    manifest["stages"].setdefault("evaluate", {})[eval_id] = {
        "status": "COMPLETE",
        "completed_at": exports.now_iso(),
        "files": exports.file_hashes(path, names),
    }
    exports.atomic_write_json(path / "run.json", manifest)
    return out_dir, "created"
