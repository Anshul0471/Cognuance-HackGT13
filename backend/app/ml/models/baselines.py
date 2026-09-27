"""LAST_VALUE and LINEAR_TREND baselines (guide 04 §4).

Both take the *raw* six-point history (oldest → newest; memory points, attention points, RT ms)
from the canonical window, never input z-scores. Neither uses sleep, mood or medication.
"""

import numpy as np

from app.ml.models.postprocessing import Prediction, from_log_rt, from_raw_rt

BASELINE_VERSIONS = {"LAST_VALUE": "last_value_v1", "LINEAR_TREND": "linear_trend_v1"}
FORMULAS = {
    "LAST_VALUE": "Each domain = its value at the most recent of the six eligible history observations "
    "(raw units). Sleep, mood and medication are ignored.",
    "LINEAR_TREND": "Per window and domain, ordinary least squares with intercept on offsets [0..5], "
    "predicted at offset 6. Memory/attention in raw points; reaction time in ln(ms), exponentiated. "
    "Coefficients use only that window. Sleep, mood and medication are ignored.",
}
_OFFSETS = np.arange(6, dtype=np.float64)


def _check(history_raw: np.ndarray) -> np.ndarray:
    h = np.asarray(history_raw, dtype=np.float64)
    if h.shape != (6, 3) or not np.isfinite(h).all() or (h[:, 2] <= 0).any():
        raise ValueError("history must be six finite (memory, attention, reaction_time_ms>0) rows")
    return h


def last_value(history_raw: np.ndarray) -> Prediction:
    h = _check(history_raw)
    return from_raw_rt(h[-1, 0], h[-1, 1], h[-1, 2])


def ols_next(values: np.ndarray) -> float:
    """OLS with intercept on offsets 0..5, evaluated at offset 6."""
    x_mean = _OFFSETS.mean()
    y = np.asarray(values, dtype=np.float64)
    slope = float(((_OFFSETS - x_mean) * (y - y.mean())).sum() / ((_OFFSETS - x_mean) ** 2).sum())
    return float(y.mean() + slope * (6.0 - x_mean))


def linear_trend(history_raw: np.ndarray) -> Prediction:
    h = _check(history_raw)
    return from_log_rt(ols_next(h[:, 0]), ols_next(h[:, 1]), ols_next(np.log(h[:, 2])))


def predict(kind: str, history_raw: np.ndarray) -> Prediction:
    if kind == "LAST_VALUE":
        return last_value(history_raw)
    if kind == "LINEAR_TREND":
        return linear_trend(history_raw)
    raise ValueError(f"unknown baseline {kind!r}")
