"""Build and validate fictional demo-history files (no database writes).

cp app/ml/data/demo_mapping.example.json data/demo_mapping.json   # once; local, git-ignored
uv run python -m app.scripts.prepare_demo_data --demo-id demo-v1 --mapping ./data/demo_mapping.json
"""

import argparse
import sys
from pathlib import Path

from app.ml.data import exports
from app.ml.data.config import DatasetError
from app.ml.data.demo_import import prepare_demo


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--demo-id", required=True)
    parser.add_argument("--mapping", default="./data/demo_mapping.json")
    args = parser.parse_args()
    try:
        path, outcome = prepare_demo(args.demo_id, Path(args.mapping))
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    manifest = exports.read_json(path / "manifest.json")
    print(f"{outcome}: {path}")
    for p in manifest["patients"]:
        weeks = f"{p['history_slots']} weeks"
        print(f"  {p['demo_key']:8} {p['scenario']:22} {weeks:9} next target {p['next_target_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
