"""Generate a synthetic dataset (raw sessions, observations, truth, splits, fixtures).

uv run python -m app.scripts.generate_synthetic --profile smoke --seed 42 --dataset-id smoke-v1
"""

import argparse
import sys

from app.ml.data.config import DatasetError, profile
from app.ml.data.pipeline import generate


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--profile", required=True, choices=["smoke", "full", "stress", "stress-smoke"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dataset-id", required=True)
    args = parser.parse_args()
    try:
        path, outcome = generate(args.dataset_id, profile(args.profile, args.seed))
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"{outcome}: {path} (generate stage COMPLETE, validated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
