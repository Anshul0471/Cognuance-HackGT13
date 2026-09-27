"""Forecast error metrics (guide 04 §6, §17). Computed on postprocessed predictions."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

import numpy as np

from app.ml.models.postprocessing import DOMAINS, to_standardized


def selection_metric(
    pred_raw: np.ndarray, y_raw: np.ndarray, patient_ids: Sequence[str], target_stats: dict[str, Any]
) -> float:
    """Patient-macro mean of the three per-domain MAEs in target-standardized coordinates.

    Postprocessed raw predictions and raw targets both go through the frozen target transforms, so
    units are balanced; each patient with eligible targets counts once however many windows it has.
    """
    if len(pred_raw) == 0:
        raise ValueError("no eligible targets for the selection metric")
    err = np.abs(to_standardized(pred_raw, target_stats) - to_standardized(y_raw, target_stats))
    by_patient: dict[str, list[np.ndarray]] = defaultdict(list)
    for pid, row in zip(patient_ids, err, strict=True):
        by_patient[pid].append(row)
    per_patient = [float(np.mean(np.mean(np.stack(rows), axis=0))) for rows in by_patient.values()]
    return float(np.mean(per_patient))


def raw_errors(pred_raw: np.ndarray, y_raw: np.ndarray) -> dict[str, dict[str, Any]]:
    """Per-domain MAE / RMSE / mean residual (actual - predicted) in points, points, ms."""
    out: dict[str, dict[str, Any]] = {}
    n = len(pred_raw)
    for i, d in enumerate(DOMAINS):
        if n == 0:
            out[d] = {"n": 0, "mae": None, "rmse": None, "mean_residual": None}
            continue
        resid = np.asarray(y_raw, dtype=np.float64)[:, i] - np.asarray(pred_raw, dtype=np.float64)[:, i]
        out[d] = {
            "n": n,
            "mae": round(float(np.mean(np.abs(resid))), 6),
            "rmse": round(float(np.sqrt(np.mean(resid**2))), 6),
            "mean_residual": round(float(np.mean(resid)), 6),
        }
    return out


def summarize(
    pred_raw: np.ndarray, y_raw: np.ndarray, patient_ids: Sequence[str], target_stats: dict[str, Any]
) -> dict[str, Any]:
    n = len(pred_raw)
    return {
        "n_windows": n,
        "n_patients": len(set(patient_ids)),
        "selection_metric": round(selection_metric(pred_raw, y_raw, patient_ids, target_stats), 6)
        if n
        else None,
        "raw": raw_errors(pred_raw, y_raw),
    }
