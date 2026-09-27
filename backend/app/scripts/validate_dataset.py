"""Re-run every dataset contract check (checksums, re-scoring, splits, windows, tensors).

uv run python -m app.scripts.validate_dataset --dataset-id smoke-v1
"""

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.validation import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    args = parser.parse_args()
    try:
        checks = validate_dataset(args.dataset_id)
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    for c in checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name}: {c.detail}")
    failed = sum(not c.passed for c in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
