"""Import prepared demo histories into the app database (idempotent; dev/demo only).

uv run python -m app.scripts.import_demo_data --demo-id demo-v1
"""

import argparse
import sys

from app.db.session import get_sessionmaker
from app.ml.data.config import DatasetError
from app.ml.data.demo_import import import_demo


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--demo-id", required=True)
    parser.add_argument(
        "--hosted-demo", action="store_true", help="required (and only valid) with APP_ENV=demo"
    )
    args = parser.parse_args()
    try:
        with get_sessionmaker()() as db:
            outcomes = import_demo(db, args.demo_id, hosted_demo=args.hosted_demo)
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    for line in outcomes:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
