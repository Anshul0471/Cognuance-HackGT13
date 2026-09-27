"""`prediction_postprocess_v1`: the one conversion shared by every model (guide 04 §7).

Offline evaluation, calibration, database persistence and online analysis all call these
functions, so thresholds are never computed against differently rounded or bounded values.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np

POSTPROCESSING_VERSION = "prediction_postprocess_v1"
SCORE_BOUNDS = (0.0, 100.0)
RT_BOUNDS_MS = (100.0, 2999.999)
LOG_RT_BOUNDS = (math.log(RT_BOUNDS_MS[0]), math.log(RT_BOUNDS_MS[1]))
DOMAINS = ("memory", "attention", "reaction_time_ms")
_Q = Decimal("0.001")


class PredictionError(ValueError):
    """A model produced a non-finite value; never replaced by a boundary value."""


def decimal3(value: float) -> Decimal:
    """Decimal ROUND_HALF_UP to 3 dp from the float's shortest decimal string."""
    if not math.isfinite(value):
        raise PredictionError("non-finite prediction")
    return Decimal(repr(float(value))).quantize(_Q, rounding=ROUND_HALF_UP)


def round3(value: float) -> float:
    return float(decimal3(value))


@dataclass(frozen=True)
class Prediction:
    """Postprocessed raw-unit forecast (points, points, milliseconds), already rounded to 3 dp."""

    memory: float
    attention: float
    reaction_time_ms: float
    # Domain → "lower" | "upper" when a support bound was applied.
    bounds: dict[str, str] = field(default_factory=dict)

    def values(self) -> tuple[float, float, float]:
        return (self.memory, self.attention, self.reaction_time_ms)

    def to_json(self) -> dict[str, Any]:
        return {
            "predicted_memory_score": self.memory,
            "predicted_attention_score": self.attention,
            "predicted_reaction_time_ms": self.reaction_time_ms,
            "bounds_applied": dict(self.bounds),
            "postprocessing_version": POSTPROCESSING_VERSION,
        }


def _clip(value: float, lo: float, hi: float, name: str, bounds: dict[str, str]) -> float:
    if not math.isfinite(value):
        raise PredictionError(f"non-finite {name} prediction")
    if value < lo:
        bounds[name] = "lower"
        return lo
    if value > hi:
        bounds[name] = "upper"
        return hi
    return value


def from_log_rt(memory: float, attention: float, log_rt: float) -> Prediction:
    """GRU / LINEAR_TREND path: scores in points, reaction time as ln(ms)."""
    bounds: dict[str, str] = {}
    m = _clip(float(memory), *SCORE_BOUNDS, "memory", bounds)
    a = _clip(float(attention), *SCORE_BOUNDS, "attention", bounds)
    # Clamp in log space before exponentiation so a large value cannot overflow.
    lr = _clip(float(log_rt), *LOG_RT_BOUNDS, "reaction_time_ms", bounds)
    rt = min(max(math.exp(lr), RT_BOUNDS_MS[0]), RT_BOUNDS_MS[1])
    return Prediction(round3(m), round3(a), round3(rt), bounds)


def from_raw_rt(memory: float, attention: float, rt_ms: float) -> Prediction:
    """LAST_VALUE path: reaction time already in milliseconds; equivalent bounds."""
    bounds: dict[str, str] = {}
    m = _clip(float(memory), *SCORE_BOUNDS, "memory", bounds)
    a = _clip(float(attention), *SCORE_BOUNDS, "attention", bounds)
    rt = _clip(float(rt_ms), *RT_BOUNDS_MS, "reaction_time_ms", bounds)
    return Prediction(round3(m), round3(a), round3(rt), bounds)


def from_standardized(z: Sequence[float], target_stats: dict[str, Any]) -> Prediction:
    """GRU output [memory_z, attention_z, log_rt_z] → raw via the *target* transforms."""
    if len(z) != 3 or not all(math.isfinite(float(v)) for v in z):
        raise PredictionError("model output must be three finite values")
    t = target_stats
    return from_log_rt(
        float(z[0]) * t["memory_score"]["scale"] + t["memory_score"]["mean"],
        float(z[1]) * t["attention_score"]["scale"] + t["attention_score"]["mean"],
        float(z[2]) * t["log_reaction_time"]["scale"] + t["log_reaction_time"]["mean"],
    )


def to_standardized(raw: np.ndarray, target_stats: dict[str, Any]) -> np.ndarray:
    """Raw [N,3] (points, points, ms) → target-standardized coordinates, float64."""
    raw = np.asarray(raw, dtype=np.float64)
    t = target_stats
    out = np.empty_like(raw)
    out[:, 0] = (raw[:, 0] - t["memory_score"]["mean"]) / t["memory_score"]["scale"]
    out[:, 1] = (raw[:, 1] - t["attention_score"]["mean"]) / t["attention_score"]["scale"]
    out[:, 2] = (np.log(raw[:, 2]) - t["log_reaction_time"]["mean"]) / t["log_reaction_time"]["scale"]
    return out


def as_array(predictions: Sequence[Prediction]) -> np.ndarray:
    return np.array([p.values() for p in predictions], dtype=np.float64).reshape(len(predictions), 3)


def bound_rates(predictions: Sequence[Prediction]) -> dict[str, dict[str, Any]]:
    n = len(predictions)
    out: dict[str, dict[str, Any]] = {}
    for d in DOMAINS:
        count = sum(1 for p in predictions if d in p.bounds)
        out[d] = {"count": count, "n": n, "rate": round(count / n, 6) if n else None}
    return out
