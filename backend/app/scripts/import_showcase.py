"""Import a prepared showcase into the configured database (refinement 03 §6–§8; dev/demo only).

uv run --extra ml python -m app.scripts.import_showcase --dataset-id showcase-v1

Idempotent: existing users keep their passwords, existing sessions are verified by payload digest
and skipped, review events replay by request key (or are skipped if someone changed the alert).
New account passwords go only to the private credentials file (mode 600); they are never printed.
"""

import argparse
import sys

from app.db.session import get_sessionmaker
from app.ml.data.config import DatasetError
from app.ml.data.showcase import import_showcase


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument(
        "--hosted-demo", action="store_true", help="required (and only valid) with APP_ENV=demo"
    )
    args = parser.parse_args()
    try:
        with get_sessionmaker()() as db:
            result = import_showcase(db, args.dataset_id, hosted_demo=args.hosted_demo)
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"identity: {result['identity']}")
    print(f"model binding: {result['model_binding']}")
    for line in result["history"]:
        print(f"  {line}")
    for line in result["failures"]:
        print(f"  {line}")
    print(f"reviews: {result['reviews']}")
    print(f"credentials (private, not printed): {result['credentials_file']}")
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
