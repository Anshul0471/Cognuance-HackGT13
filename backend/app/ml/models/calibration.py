"""Error-scale estimation and threshold selection for `deviation_policy_v1` (guide 04 §9, §12).

Scales: `validation_calibration_clean`. Threshold r: chronological replay of
`validation_calibration_all`. The test partition is never read here.
"""

import math
from typing import Any

import numpy as np

from app.ml.models.anomaly import (
    AGGREGATE_METHOD,
    HIGH_MAX_MULTIPLIER,
    HIGH_MIN_DOMAINS,
    MODERATE_AGGREGATE_MULTIPLIER,
    PERSISTENCE_RULE,
    PERSISTENT_MIN_COUNT,
    POLICY_SCHEMA_VERSION,
    SCALE_FLOORS,
    PolicyRules,
)
from app.ml.models.postprocessing import DOMAINS

MIN_CALIBRATION_WINDOWS = 200
MIN_CALIBRATION_PATIENTS = 20
MIN_WORSENING_EVENTS = 10
MAX_CLEAN_ALERT_FRACTION = 0.05
SELECTION_RULE = (
    "Among r in the grid with clean-target alert fraction <= 0.05, maximize the analyzable worsening-event "
    "detection fraction; tie-break by fewer total calibration alerts, then larger r. Requires >= 10 "
    "analyzable worsening event IDs and >= 1 detected event."
)


def fit_scales(pred_raw: np.ndarray, y_raw: np.ndarray) -> dict[str, dict[str, Any]]:
    out = {}
    for i, d in enumerate(DOMAINS):
        resid = np.asarray(y_raw, dtype=np.float64)[:, i] - np.asarray(pred_raw, dtype=np.float64)[:, i]
        rmse = float(np.sqrt(np.mean(resid**2)))
        floor = SCALE_FLOORS[d]
        out[d] = {
            "n": int(len(resid)),
            "mean_residual": round(float(np.mean(resid)), 6),
            "raw_rmse": round(rmse, 6),
            "floor": floor,
            "floor_applied": rmse < floor,
            "scale": max(rmse, floor),
        }
        if not math.isfinite(out[d]["scale"]) or out[d]["scale"] <= 0:
            raise ValueError(f"invalid scale for {d}")
    return out


def rules_for(scales: dict[str, dict[str, Any]], r: float) -> PolicyRules:
    return PolicyRules(scales={d: scales[d]["scale"] for d in DOMAINS}, r=r)


def rules_json(r: float) -> dict[str, Any]:
    return {
        "r": r,
        "moderate_rule": "(M >= r) OR (A >= 0.8 * r)",
        "high_rule": "(M >= 2.0 * r) OR (count(z_domain >= r) >= 2)",
        "moderate_aggregate_multiplier": MODERATE_AGGREGATE_MULTIPLIER,
        "high_max_multiplier": HIGH_MAX_MULTIPLIER,
        "high_min_domains": HIGH_MIN_DOMAINS,
        "persistent_min_count": PERSISTENT_MIN_COUNT,
        "aggregate_method": AGGREGATE_METHOD,
        "persistence_rule": PERSISTENCE_RULE,
        "category_order": ["HIGH_DEVIATION", "PERSISTENT_DEVIATION", "REVIEW", "NORMAL"],
    }


def select_threshold(candidates: list[dict[str, Any]]) -> tuple[float | None, str]:
    """`candidates`: one metrics dict per r (with key 'r'). Returns (r or None, decision code)."""
    if not candidates:
        return None, "NO_CANDIDATES"
    analyzable = candidates[0]["metrics"]["worsening_events"]["analyzable"]
    if analyzable < MIN_WORSENING_EVENTS:
        return None, "INSUFFICIENT_WORSENING_EVENTS"
    qualified = [
        c
        for c in candidates
        if (f := c["metrics"]["clean_target_alert_fraction"]["fraction"]) is not None
        and f <= MAX_CLEAN_ALERT_FRACTION
    ]
    if not qualified:
        return None, "NO_THRESHOLD_MEETS_CLEAN_ALERT_OBJECTIVE"
    best = sorted(
        qualified,
        key=lambda c: (
            -(c["metrics"]["worsening_events"]["conditional_detection_fraction"] or 0.0),
            c["metrics"]["alerts"],
            -c["r"],
        ),
    )[0]
    if best["metrics"]["worsening_events"]["detected"] == 0:
        return None, "ZERO_DETECTED_WORSENING_EVENTS"
    return best["r"], "SELECTED"


def policy_document(
    *,
    policy_version: str,
    model_version: str,
    model_kind: str,
    engine_version: str,
    preprocessing_version: str,
    postprocessing_version: str,
    scales: dict[str, dict[str, Any]],
    r: float,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """The immutable serving rules (also stored verbatim in `anomaly_policies.configuration`)."""
    return {
        "policy_version": policy_version,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "model_version": model_version,
        "model_kind": model_kind,
        "engine_version": engine_version,
        "preprocessing_version": preprocessing_version,
        "postprocessing_version": postprocessing_version,
        "scales": scales,
        "rules": rules_json(r),
        "provenance": provenance,
        "disclaimer": "Engineering parameters calibrated on synthetic data; not clinical cutoffs.",
    }
