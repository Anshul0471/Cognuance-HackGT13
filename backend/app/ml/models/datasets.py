"""Load guide-03 prepared datasets for model work (guide 04 §2 step 1).

Verifies the dataset manifest stages and checksums before any tensor is used, and attaches the
canonical raw history (from observations, not inverted z-scores) that baselines need.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.data import exports
from app.ml.data.config import PREPROCESSING_VERSION, DatasetError
from app.ml.data.pipeline import VIEWS, load_manifest, verify_stage
from app.ml.data.preprocessing import X_CHANNELS, Y_CHANNELS, build_tensors

RAW_FIELDS = ("memory_score", "attention_score", "reaction_time_ms")


@dataclass
class View:
    name: str
    X: np.ndarray  # float32 [N,6,9]
    y: np.ndarray  # float32 [N,3]
    y_raw: np.ndarray  # float64 [N,3]
    window_ids: list[str]
    patient_ids: list[str]
    target_slots: list[int]
    history_raw: np.ndarray  # float64 [N,6,3], oldest → newest
    windows: list[dict[str, Any]]

    def __len__(self) -> int:
        return len(self.window_ids)


@dataclass
class Dataset:
    dataset_id: str
    path: Path
    manifest: dict[str, Any]
    params: dict[str, Any]
    windows: dict[str, dict[str, Any]]
    observations: dict[str, dict[str, Any]]

    @property
    def profile(self) -> str:
        return self.manifest["config"]["profile"]

    def reference(self) -> dict[str, Any]:
        st = self.manifest["stages"]
        return {
            "dataset_id": self.dataset_id,
            "profile": self.profile,
            "config_hash": self.manifest["config_hash"],
            "generate_content_hash": st["generate"]["content_hash"],
            "prepare_content_hash": st["prepare"]["content_hash"],
            "preprocessing_version": st["prepare"]["preprocessing_version"],
            "versions": self.manifest["versions"],
        }


def open_dataset(dataset_id: str, root: Path | None = None) -> Dataset:
    path, manifest = load_manifest(dataset_id, root)
    stages = manifest.get("stages", {})
    if (
        stages.get("generate", {}).get("status") != "COMPLETE"
        or stages.get("prepare", {}).get("status") != "COMPLETE"
    ):
        raise DatasetError(
            f"dataset {dataset_id!r} is not generated+prepared; run the guide-03 commands first"
        )
    verify_stage(path, manifest, "generate")
    verify_stage(path, manifest, "prepare")
    params = exports.read_json(path / "preprocessing.json")
    if params.get("preprocessing_version") != PREPROCESSING_VERSION or params.get("x_channels") != list(
        X_CHANNELS
    ):
        raise DatasetError(
            "preprocessing artifact does not match the expected preprocessing_v1 channel schema"
        )
    if params.get("y_channels") != list(Y_CHANNELS):
        raise DatasetError("target channel order mismatch")
    windows: dict[str, dict[str, Any]] = {}
    for part in ("train", "validation_tune", "validation_calibration", "test"):
        for w in exports.read_jsonl(path / f"windows/{part}.jsonl"):
            windows[w["window_id"]] = w
    observations = {o["observation_id"]: o for o in exports.read_jsonl(path / "observations.jsonl")}
    return Dataset(dataset_id, path, manifest, params, windows, observations)


def history_raw(windows: list[dict[str, Any]], observations: dict[str, dict[str, Any]]) -> np.ndarray:
    return np.array(
        [
            [[float(observations[i][f]) for f in RAW_FIELDS] for i in w["input_observation_ids"]]
            for w in windows
        ],
        dtype=np.float64,
    ).reshape(len(windows), 6, 3)


def _view_from(
    name: str,
    arrays: dict[str, np.ndarray],
    windows: list[dict[str, Any]],
    observations: dict[str, dict[str, Any]],
) -> View:
    ids = [str(x) for x in arrays["window_ids"]]
    if ids != [w["window_id"] for w in windows]:
        raise DatasetError(f"{name}: tensor rows and window manifest are out of order")
    return View(
        name=name,
        X=arrays["X"],
        y=arrays["y"],
        y_raw=arrays["y_raw"],
        window_ids=ids,
        patient_ids=[w["patient_id"] for w in windows],
        target_slots=[int(w["target_slot"]) for w in windows],
        history_raw=history_raw(windows, observations),
        windows=windows,
    )


def load_view(ds: Dataset, name: str) -> View:
    if name not in VIEWS:
        raise DatasetError(f"unknown view {name!r}")
    arrays = exports.load_npz(ds.path / f"tensors/{name}.npz")
    windows = [ds.windows[str(i)] for i in arrays["window_ids"]]
    return _view_from(name, arrays, windows, ds.observations)


def partition_slot_windows(ds: Dataset, partition: str) -> list[dict[str, Any]]:
    """Every canonical slot record of a partition (supervised or not), for chronological replay."""
    rows = [w for w in ds.windows.values() if w["partition"] == partition and w["kind"] == "slot"]
    return sorted(rows, key=lambda w: (w["patient_id"], w["target_slot"]))


def truth_patients(path: Path) -> dict[str, dict[str, Any]]:
    return {t["patient_id"]: t for t in exports.read_jsonl(path / "truth.jsonl") if t["kind"] == "patient"}


def external_view(
    name: str, windows: list[dict[str, Any]], observations: dict[str, dict[str, Any]], params: dict[str, Any]
) -> View:
    """Tensors for a separately generated population (e.g. stress) using *frozen* main preprocessing."""
    supervised = [w for w in windows if w["kind"] == "slot" and w["supervised"]]
    return _view_from(name, build_tensors(supervised, observations, params), supervised, observations)
