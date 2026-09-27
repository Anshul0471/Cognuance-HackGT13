"""Candidate forecasters over prepared views and over live history (shared by offline and serving).

Every path ends in `prediction_postprocess_v1`, and live inputs are transformed with the same
`preprocessing.feature_row` used to build the offline tensors.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np

from app.ml.data.preprocessing import feature_row
from app.ml.models import baselines
from app.ml.models.postprocessing import Prediction, PredictionError, from_standardized

KINDS = ("LAST_VALUE", "LINEAR_TREND", "GRU")
SIMPLICITY_ORDER = {"LAST_VALUE": 0, "LINEAR_TREND": 1, "GRU": 2}


def gru_outputs(model: Any, X: np.ndarray) -> np.ndarray:
    """Standardized GRU outputs [N,3] in eval mode under inference_mode (no dropout, no grad)."""
    import torch

    model.eval()
    with torch.inference_mode():
        out = model(torch.as_tensor(np.asarray(X, dtype=np.float32))).numpy().astype(np.float64)
    if not np.isfinite(out).all():
        raise PredictionError("GRU produced non-finite output")
    return out


def predict_batch(
    kind: str, X: np.ndarray, history_raw: np.ndarray, params: dict[str, Any], model: Any = None
) -> list[Prediction]:
    if kind == "GRU":
        if model is None:
            raise ValueError("GRU prediction needs a model")
        return [from_standardized(row, params["target_stats"]) for row in gru_outputs(model, X)]
    return [baselines.predict(kind, h) for h in history_raw]


def history_matrices(
    history: Sequence[dict[str, Any]], params: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    """Six allow-listed history observations → (X [1,6,9] float32, raw [6,3] float64)."""
    if len(history) != 6:
        raise ValueError("forecasts need exactly six history observations")
    X = np.array([[feature_row(h, params) for h in history]], dtype=np.float32)
    raw = np.array(
        [
            [float(h["memory_score"]), float(h["attention_score"]), float(h["reaction_time_ms"])]
            for h in history
        ],
        dtype=np.float64,
    )
    return X, raw


def predict_history(
    kind: str, history: Sequence[dict[str, Any]], params: dict[str, Any], model: Any = None
) -> tuple[Prediction, np.ndarray]:
    X, raw = history_matrices(history, params)
    return predict_batch(kind, X, raw[None, ...], params, model)[0], X[0]
