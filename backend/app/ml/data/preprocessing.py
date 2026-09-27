"""`preprocessing_v1`: train-only fitted transforms and the 9-channel tensor schema (guide 03 §12–§14).

Only these observation fields may reach X (`FEATURE_SOURCE_FIELDS`); scenario, event, latent,
slot, identity and source fields are rejected by construction. Fitted values are plain JSON.
"""

import hashlib
import math
from typing import Any

import numpy as np

from app.ml.data.config import PREPROCESSING_VERSION, DatasetError

FEATURE_SOURCE_FIELDS = ("memory_score", "attention_score", "reaction_time_ms", "sleep_hours", "mood_score", "medication_change")
X_CHANNELS = (
    "memory_score_z",
    "attention_score_z",
    "log_reaction_time_z",
    "sleep_hours_z",
    "mood_score_z",
    "medication_change_value",
    "sleep_missing",
    "mood_missing",
    "medication_missing",
)
Y_CHANNELS = ("memory_score_z", "attention_score_z", "log_reaction_time_z")
FORBIDDEN_FEATURE_FIELDS = {
    "scenario", "event_id", "event_kind", "event_active", "performance_event_active", "latent", "latent_params",
    "patient_id", "family_id", "slot_index", "source", "trajectory", "hidden_context", "quality_fault_kind",
}
TOLERANCE = {"score_abs": 1e-3, "rt_ms_abs": 1e-2, "float32_note": "y is float32; checked against y_raw at these tolerances"}


def _stats(values: list[float]) -> dict[str, Any]:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        raise DatasetError("INSUFFICIENT_PREPROCESSING_DATA: empty fitting population")
    std = float(arr.std())  # population standard deviation
    constant = std == 0.0
    return {"mean": float(arr.mean()), "scale": 1.0 if constant else std, "constant": constant, "count": int(arr.size)}


def _medication_value(value: str | None) -> tuple[float, float]:
    """(encoded value, missing mask). NOT_SURE is unknown → placeholder 0 with mask 1 (not "no change")."""
    if value == "YES":
        return 1.0, 0.0
    if value == "NO":
        return 0.0, 0.0
    return 0.0, 1.0


def fit(observations_by_id: dict[str, dict[str, Any]], train_windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit on unique input IDs / unique target IDs of clean *train* windows only."""
    if not train_windows:
        raise DatasetError("INSUFFICIENT_TRAINING_WINDOWS: train_clean is empty")
    if any(w["partition"] != "train" for w in train_windows):
        raise DatasetError("preprocessing may only be fitted on train windows")
    input_ids = sorted({i for w in train_windows for i in w["input_observation_ids"]})
    target_ids = sorted({w["target_observation_id"] for w in train_windows})
    inputs = [observations_by_id[i] for i in input_ids]
    targets = [observations_by_id[i] for i in target_ids]

    sleep_obs = [o["sleep_hours"] for o in inputs if o["sleep_hours"] is not None]
    mood_obs = [o["mood_score"] for o in inputs if o["mood_score"] is not None]
    if not sleep_obs or not mood_obs:
        raise DatasetError("INSUFFICIENT_PREPROCESSING_DATA: a context field is entirely missing in train inputs")
    sleep_median, mood_median = float(np.median(sleep_obs)), float(np.median(mood_obs))

    def imputed(field: str, median: float) -> list[float]:
        return [float(o[field]) if o[field] is not None else median for o in inputs]

    fingerprint = hashlib.sha256("\n".join(input_ids + ["--"] + target_ids).encode()).hexdigest()
    return {
        "preprocessing_version": PREPROCESSING_VERSION,
        "feature_source_fields": list(FEATURE_SOURCE_FIELDS),
        "x_channels": list(X_CHANNELS),
        "y_channels": list(Y_CHANNELS),
        "x_shape": ["N", 6, len(X_CHANNELS)],
        "y_shape": ["N", len(Y_CHANNELS)],
        "dtype": {"X": "float32", "y": "float32", "y_raw": "float64"},
        "time_order": "oldest_to_newest",
        "units": {"memory_score": "score 0-100", "attention_score": "score 0-100", "reaction_time_ms": "milliseconds",
                  "sleep_hours": "hours", "mood_score": "1-10"},
        "transforms": {
            "memory_score_z": "(memory_score - mean) / scale",
            "attention_score_z": "(attention_score - mean) / scale",
            "log_reaction_time_z": "(ln(reaction_time_ms) - mean) / scale",
            "sleep_hours_z": "(sleep_hours or train_median - mean) / scale",
            "mood_score_z": "(mood_score or train_median - mean) / scale",
            "medication_change_value": "YES=1, NO=0, NULL/NOT_SURE=0 with medication_missing=1",
            "masks": "1 if originally NULL (medication: NULL or NOT_SURE), else 0; unscaled",
            "inverse_y": "memory = z*scale+mean; attention = z*scale+mean; rt_ms = exp(z*scale+mean)",
        },
        "imputation": {"sleep_hours_median": sleep_median, "mood_score_median": mood_median},
        "input_stats": {
            "memory_score": _stats([o["memory_score"] for o in inputs]),
            "attention_score": _stats([o["attention_score"] for o in inputs]),
            "log_reaction_time": _stats([math.log(o["reaction_time_ms"]) for o in inputs]),
            "sleep_hours": _stats(imputed("sleep_hours", sleep_median)),
            "mood_score": _stats(imputed("mood_score", mood_median)),
        },
        "target_stats": {
            "memory_score": _stats([o["memory_score"] for o in targets]),
            "attention_score": _stats([o["attention_score"] for o in targets]),
            "log_reaction_time": _stats([math.log(o["reaction_time_ms"]) for o in targets]),
        },
        "fit_population": {"input_observations": len(input_ids), "target_observations": len(target_ids),
                           "train_windows": len(train_windows), "fingerprint_sha256": fingerprint},
        "tolerance": TOLERANCE,
    }


def _z(value: float, stats: dict[str, Any]) -> float:
    return (value - stats["mean"]) / stats["scale"]


def feature_row(obs: dict[str, Any], params: dict[str, Any]) -> list[float]:
    """Nine channels from the six allow-listed fields of one historical observation."""
    src = {f: obs[f] for f in FEATURE_SOURCE_FIELDS}  # allow-list: nothing else is read
    s, imp = params["input_stats"], params["imputation"]
    if src["memory_score"] is None or src["attention_score"] is None or src["reaction_time_ms"] is None:
        raise DatasetError("cognition is never imputed: input observation lacks a domain score")
    sleep_missing = src["sleep_hours"] is None
    mood_missing = src["mood_score"] is None
    med_value, med_missing = _medication_value(src["medication_change"])
    row = [
        _z(src["memory_score"], s["memory_score"]),
        _z(src["attention_score"], s["attention_score"]),
        _z(math.log(src["reaction_time_ms"]), s["log_reaction_time"]),
        _z(imp["sleep_hours_median"] if sleep_missing else src["sleep_hours"], s["sleep_hours"]),
        _z(imp["mood_score_median"] if mood_missing else src["mood_score"], s["mood_score"]),
        med_value,
        float(sleep_missing),
        float(mood_missing),
        med_missing,
    ]
    if not all(math.isfinite(v) for v in row):
        raise DatasetError("non-finite feature value")
    return row


def target_row(obs: dict[str, Any], params: dict[str, Any]) -> tuple[list[float], list[float]]:
    t = params["target_stats"]
    raw = [obs["memory_score"], obs["attention_score"], obs["reaction_time_ms"]]
    z = [_z(raw[0], t["memory_score"]), _z(raw[1], t["attention_score"]), _z(math.log(raw[2]), t["log_reaction_time"])]
    return z, [float(v) for v in raw]


def inverse_targets(y: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    t = params["target_stats"]
    y = np.asarray(y, dtype=np.float64)
    out = np.empty_like(y)
    out[:, 0] = y[:, 0] * t["memory_score"]["scale"] + t["memory_score"]["mean"]
    out[:, 1] = y[:, 1] * t["attention_score"]["scale"] + t["attention_score"]["mean"]
    out[:, 2] = np.exp(y[:, 2] * t["log_reaction_time"]["scale"] + t["log_reaction_time"]["mean"])
    return out


def build_tensors(
    windows: list[dict[str, Any]], observations_by_id: dict[str, dict[str, Any]], params: dict[str, Any]
) -> dict[str, np.ndarray]:
    X = np.array(
        [[feature_row(observations_by_id[i], params) for i in w["input_observation_ids"]] for w in windows],
        dtype=np.float32,
    ).reshape(len(windows), 6, len(X_CHANNELS))
    ys = [target_row(observations_by_id[w["target_observation_id"]], params) for w in windows]
    y = np.array([z for z, _ in ys], dtype=np.float32).reshape(len(windows), 3)
    y_raw = np.array([r for _, r in ys], dtype=np.float64).reshape(len(windows), 3)
    window_ids = np.array([w["window_id"] for w in windows], dtype="<U36")
    if not (np.isfinite(X).all() and np.isfinite(y).all() and np.isfinite(y_raw).all()):
        raise DatasetError("non-finite tensor values")
    return {"X": X, "y": y, "y_raw": y_raw, "window_ids": window_ids}
