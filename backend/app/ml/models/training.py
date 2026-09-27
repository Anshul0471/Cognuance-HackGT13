"""GRU training with fixed settings and validation-tune checkpoint selection (guide 04 §6)."""

import copy
import os
import platform
import random
import time
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from app.ml.models.datasets import View
from app.ml.models.forecasting import predict_batch
from app.ml.models.gru import CognitiveForecaster
from app.ml.models.metrics import selection_metric
from app.ml.models.postprocessing import as_array

TRAINING_SETTINGS: dict[str, Any] = {
    "training_view": "train_clean",
    "selection_view": "validation_tune_clean",
    "loss": "MSE averaged across the three standardized target channels",
    "optimizer": "AdamW",
    "learning_rate": 0.001,
    "weight_decay": 0.0001,
    "batch_size": 64,
    "max_epochs": 50,
    "grad_clip_norm": 1.0,
    "early_stop_patience": 7,
    "min_improvement": 0.0001,
    "seed": 42,
    "device": "cpu",
    "num_workers": 0,
    "hidden_size": 32,
    "cpu_threads": 1,
}


class TrainingFailure(RuntimeError):
    """NaN/Inf loss or gradient: the run fails instead of saving a broken checkpoint."""


def set_determinism(seed: int, threads: int) -> dict[str, Any]:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    # Surface nondeterministic kernels as errors rather than silently changing the run.
    torch.use_deterministic_algorithms(True)
    return {
        "python_random_seed": seed,
        "numpy_seed": seed,
        "torch_manual_seed": seed,
        "dataloader_generator_seed": seed,
        "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "torch_num_threads": torch.get_num_threads(),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
    }


def environment() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "note": "Bitwise reproducibility is only expected on the same software/hardware stack.",
    }


def tune_metric(model: nn.Module, view: View, params: dict[str, Any]) -> float:
    preds = as_array(predict_batch("GRU", view.X, view.history_raw, params, model))
    return selection_metric(preds, view.y_raw, view.patient_ids, params["target_stats"])


def train_gru(
    train: View, tune: View, params: dict[str, Any], settings: dict[str, Any] | None = None
) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    """Returns (best state_dict copy, training report)."""
    s = {**TRAINING_SETTINGS, **(settings or {})}
    determinism = set_determinism(s["seed"], s["cpu_threads"])
    started = time.perf_counter()

    model = CognitiveForecaster(input_size=train.X.shape[2], hidden_size=s["hidden_size"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=s["learning_rate"], weight_decay=s["weight_decay"])
    loss_fn = nn.MSELoss()
    generator = torch.Generator().manual_seed(s["seed"])
    loader = DataLoader(
        TensorDataset(torch.as_tensor(train.X), torch.as_tensor(train.y)),
        batch_size=s["batch_size"],
        shuffle=True,  # training view only; validation is never shuffled
        generator=generator,
        num_workers=s["num_workers"],
    )

    best_metric = float("inf")
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    stale = 0
    history: list[dict[str, Any]] = []
    initial_metric = tune_metric(model, tune, params)
    for epoch in range(1, s["max_epochs"] + 1):
        model.train()
        total, count, max_grad = 0.0, 0, 0.0
        for xb, yb in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(xb), yb)
            if not torch.isfinite(loss):
                raise TrainingFailure(f"non-finite loss at epoch {epoch}")
            loss.backward()
            grad = float(torch.nn.utils.clip_grad_norm_(model.parameters(), s["grad_clip_norm"]))
            if not np.isfinite(grad):
                raise TrainingFailure(f"non-finite gradient norm at epoch {epoch}")
            optimizer.step()
            total += loss.item() * len(xb)
            count += len(xb)
            max_grad = max(max_grad, grad)
        metric = tune_metric(model, tune, params)
        improved = metric < best_metric - s["min_improvement"]
        if improved:
            best_metric, best_epoch, stale = metric, epoch, 0
            best_state = copy.deepcopy(model.state_dict())  # later steps cannot mutate the saved best
        else:
            stale += 1
        history.append(
            {
                "epoch": epoch,
                "train_loss": round(total / count, 6),
                "tune_selection_metric": round(metric, 6),
                "max_grad_norm_before_clip": round(max_grad, 6),
                "improved": improved,
            }
        )
        if stale >= s["early_stop_patience"]:
            break

    if best_state is None:
        raise TrainingFailure("no checkpoint improved on the initial state")
    report = {
        "settings": s,
        "determinism": determinism,
        "environment": environment(),
        "train_windows": len(train),
        "train_patients": len(set(train.patient_ids)),
        "tune_windows": len(tune),
        "tune_patients": len(set(tune.patient_ids)),
        "initial_tune_selection_metric": round(initial_metric, 6),
        "selected_epoch": best_epoch,
        "selected_tune_selection_metric": round(best_metric, 6),
        "epochs_run": len(history),
        "stopped_early": len(history) < s["max_epochs"],
        "history": history,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "parameter_count": sum(p.numel() for p in model.parameters()),
        "limitations": [
            "Trained on synthetic clean windows only; not evidence of clinical accuracy.",
            "A decreasing training loss is not evidence of anomaly-detection performance.",
            "Selected by validation-tune patient-macro MAE; test data was not used.",
        ],
    }
    return best_state, report
