"""The custom GRU forecaster (guide 04 §5). Requires the `ml` extra (torch)."""

from typing import Any

import torch
from torch import nn

from app.ml.data.preprocessing import X_CHANNELS, Y_CHANNELS

ARCHITECTURE_VERSION = "cognitive_gru_v1"
SEQUENCE_LENGTH = 6
INPUT_SIZE = len(X_CHANNELS)


class CognitiveForecaster(nn.Module):
    def __init__(self, input_size: int = 9, hidden_size: int = 32) -> None:
        super().__init__()
        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=False,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 16),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(16, 3),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1:] != (6, 9):
            raise ValueError("Expected input shape [batch, 6, 9]")
        # No hidden state is passed in: every sequence starts from zeros (no carry between patients).
        _, hidden = self.gru(x)
        return self.head(hidden[-1])


def architecture_config(hidden_size: int = 32) -> dict[str, Any]:
    return {
        "architecture_version": ARCHITECTURE_VERSION,
        "class": "CognitiveForecaster",
        "input_size": INPUT_SIZE,
        "hidden_size": hidden_size,
        "num_layers": 1,
        "bidirectional": False,
        "head": "Linear(hidden,16) → ReLU → Dropout(0.1) → Linear(16,3)",
        "sequence_length": SEQUENCE_LENGTH,
        "x_channels": list(X_CHANNELS),
        "y_channels": list(Y_CHANNELS),
        "output": "regression in target-standardized coordinates (no sigmoid/softmax)",
    }


def build_model(config: dict[str, Any]) -> CognitiveForecaster:
    """Reconstruct the known architecture from a bundle's model_config (refuses other schemas)."""
    if config.get("architecture_version") != ARCHITECTURE_VERSION:
        raise ValueError("unsupported GRU architecture version")
    if list(config.get("x_channels", [])) != list(X_CHANNELS) or config.get("input_size") != INPUT_SIZE:
        raise ValueError("feature schema does not match preprocessing_v1 channel order")
    if config.get("sequence_length") != SEQUENCE_LENGTH:
        raise ValueError("sequence length does not match the architecture")
    return CognitiveForecaster(input_size=INPUT_SIZE, hidden_size=int(config["hidden_size"]))
