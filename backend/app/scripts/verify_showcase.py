"""Read-only verification of an imported showcase (refinement 03 §14, refinement 04 §10).

uv run --extra ml python -m app.scripts.verify_showcase --dataset-id showcase-v1 [--json out.json]

Prints actual counts (sources, quality, analysis availability, deviation levels, alert workflow),
score re-check, forecast chronology, authorization boundary, and live-slot readiness.
"""

import argparse
import json
import sys
from pathlib import Path

from app.db.session import get_sessionmaker
from app.ml.data.config import DatasetError
from app.ml.data.showcase import verify_showcase


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    args = parser.parse_args()
    try:
        with get_sessionmaker()() as db:
            report = verify_showcase(db, args.dataset_id)
            db.rollback()  # read-only
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    text = json.dumps(report, indent=2, default=str)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
