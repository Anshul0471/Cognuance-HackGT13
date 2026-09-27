"""Build windows, fit train-only preprocessing and write tensor views (never regenerates raw data).

uv run python -m app.scripts.prepare_dataset --dataset-id smoke-v1 --preprocessing-version preprocessing_v1
"""

import argparse
import sys

from app.ml.data.config import PREPROCESSING_VERSION, DatasetError
from app.ml.data.pipeline import load_manifest, prepare


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument(
        "--preprocessing-version", default=PREPROCESSING_VERSION, choices=[PREPROCESSING_VERSION]
    )
    args = parser.parse_args()
    try:
        path, outcome = prepare(args.dataset_id, args.preprocessing_version)
        counts = load_manifest(args.dataset_id)[1]["stages"]["prepare"]["view_counts"]
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"{outcome}: {path} (prepare stage COMPLETE, validated)")
    for view, n in counts.items():
        print(f"  {view:30} {n:>7} windows  -> tensors/{view}.npz  X[{n},6,9] y[{n},3]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
