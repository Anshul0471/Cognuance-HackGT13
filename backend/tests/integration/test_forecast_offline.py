"""Offline workflow on a temporary smoke dataset (guide 04 §18, §19).

train → select → calibrate → evaluate → register.

A tiny training run proves loss/backprop and save/reload; smoke artifacts are fixture mode and
must never become activatable.
"""

import numpy as np
import pytest
import torch

from app.ml.data import exports
from app.ml.data.config import profile
from app.ml.data.pipeline import generate, prepare
from app.ml.models import registry, runs
from app.ml.models.datasets import load_view, open_dataset
from app.ml.models.forecasting import predict_batch, predict_history


@pytest.fixture(scope="module")
def smoke_run(tmp_path_factory):
    data = tmp_path_factory.mktemp("synthetic")
    art = tmp_path_factory.mktemp("artifacts")
    generate("smoke-m", profile("smoke"), data)
    prepare("smoke-m", "preprocessing_v1", data)
    path, status = runs.train_run("smoke-m", "run-a", root=art, data_root=data, settings={"max_epochs": 3})
    assert status == "created"
    return data, art, path


def test_training_smoke_saves_reloadable_best_checkpoint(smoke_run):
    data, art, path = smoke_run
    report = exports.read_json(path / "candidates/GRU/training_report.json")
    assert report["epochs_run"] == 3 and report["determinism"]["torch_deterministic_algorithms"] is True
    assert all(np.isfinite(h["train_loss"]) for h in report["history"])
    assert report["history"][-1]["train_loss"] < report["history"][0]["train_loss"]  # backprop works
    model = runs.load_gru(path)
    assert not model.training
    ds = open_dataset("smoke-m", data)
    tune = load_view(ds, "validation_tune_clean")
    preds = predict_batch("GRU", tune.X, tune.history_raw, ds.params, model)
    again = predict_batch("GRU", tune.X, tune.history_raw, ds.params, runs.load_gru(path))
    assert [p.values() for p in preds] == [p.values() for p in again]
    # Same run id + same dataset → reused, never silently retrained.
    assert runs.train_run("smoke-m", "run-a", root=art, data_root=data)[1] == "reused"


def test_serving_transform_matches_offline_tensors(smoke_run):
    data, _, path = smoke_run
    ds = open_dataset("smoke-m", data)
    view = load_view(ds, "validation_tune_clean")
    model = runs.load_gru(path)
    for i in range(3):
        rows = [ds.observations[o] for o in view.windows[i]["input_observation_ids"]]
        for kind in ("LAST_VALUE", "LINEAR_TREND", "GRU"):
            live, x = predict_history(kind, rows, ds.params, model if kind == "GRU" else None)
            offline = predict_batch(
                kind,
                view.X[i : i + 1],
                view.history_raw[i : i + 1],
                ds.params,
                model if kind == "GRU" else None,
            )[0]
            assert live.values() == offline.values()
        assert np.array_equal(x, view.X[i])


def test_select_calibrate_evaluate_register_in_fixture_mode(smoke_run, db_session):
    data, art, path = smoke_run
    runs.select_run("run-a", root=art, data_root=data)
    evaluation = exports.read_json(path / "forecast_evaluation.json")
    assert evaluation["same_targets"]["validation_tune_clean"]["n_windows"] > 0
    assert set(evaluation["candidates"]) == {"LAST_VALUE", "LINEAR_TREND", "GRU"}
    assert evaluation["test_data_used"] is False
    selected = evaluation["decision"]["selected_kind"]
    assert evaluation["selected_model_version"] == runs.model_version_for("run-a", selected)

    with pytest.raises(runs.RunError, match="calibrate"):
        runs.evaluate_run("run-a", "test", "policy-a", root=art, data_root=data)  # prerequisites enforced
    pdir, _ = runs.calibrate_run("run-a", "policy-a", root=art, data_root=data)
    report = exports.read_json(pdir / "calibration_report.json")
    assert report["decision"] == "INSUFFICIENT_CALIBRATION_DATA" and report["activatable"] is False
    assert report["mode"] == "FIXTURE_NON_ACTIVATABLE" and report["test_data_used"] is False
    assert [c["r"] for c in report["candidates"]] == [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]

    out, status = runs.evaluate_run("run-a", "test", "policy-a", root=art, data_root=data)
    assert status == "created"
    test_report = exports.read_json(out / "test_report.json")
    cov = test_report["coverage"]
    assert cov["analyzed"] + sum(cov["not_analyzed_by_reason"].values()) == cov["slot_records"]
    assert runs.evaluate_run("run-a", "test", "policy-a", root=art, data_root=data)[1] == "reused"  # once

    result = registry.register_run(db_session, "run-a", root=art)
    assert result["model_activatable"] is False and result["reports"] == ["test-policy-a"]
    with pytest.raises(registry.RegistryError) as exc:
        registry.activate(db_session, result["model_version"], "policy-a", art)
    assert exc.value.code == "NOT_ACTIVATABLE"
    assert registry.register_run(db_session, "run-a", root=art)["db"] == "reused"  # idempotent


def test_tampered_run_and_wrong_schema_are_refused(smoke_run, tmp_path):
    data, art, path = smoke_run
    weights = path / "candidates/GRU/weights.pt"
    original = weights.read_bytes()
    try:
        state = torch.load(weights, weights_only=True)
        state["head.3.bias"] += 1.0
        torch.save(state, weights)
        with pytest.raises(runs.RunError, match="checksum"):
            runs.calibrate_run("run-a", "policy-b", root=art, data_root=data)
    finally:
        weights.write_bytes(original)
    bad = exports.read_json(path / "preprocessing.json")
    bad["x_channels"] = list(reversed(bad["x_channels"]))
    exports.write_json(tmp_path / "preprocessing.json", bad)
    for n in ("model_config.json", "training_report.json", "forecast_evaluation.json"):
        exports.write_json(tmp_path / n, {})
    with pytest.raises(registry.RegistryError) as exc:
        registry.write_model_bundle(
            model_version="bad-schema",
            kind="LAST_VALUE",
            provenance={},
            activatable=False,
            root=tmp_path,
            sources={
                n: tmp_path / n
                for n in (
                    "model_config.json",
                    "preprocessing.json",
                    "training_report.json",
                    "forecast_evaluation.json",
                )
            },
        )
    assert exc.value.code == "FEATURE_SCHEMA_MISMATCH"
    with pytest.raises(runs.RunError):
        runs.run_path("../escape", art)
