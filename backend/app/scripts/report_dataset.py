"""Write data_report.json and data_report.md (coverage, distributions, events, exclusions).

uv run python -m app.scripts.report_dataset --dataset-id smoke-v1
"""

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.report import write_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    args = parser.parse_args()
    try:
        path = write_report(args.dataset_id)
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"wrote {path / 'data_report.json'} and {path / 'data_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
