import random

import numpy as np


def seed_everything(seed: int) -> None:
    """Seed Python, NumPy, and (if installed) PyTorch RNGs."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
