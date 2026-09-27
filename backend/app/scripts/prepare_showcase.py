"""Prepare the presentation showcase files (refinement 03 §8). Files only — no database writes.

uv run python -m app.scripts.prepare_showcase --dataset-id showcase-v1 --seed 20260927 \
    --as-of 2026-09-26T16:00:00Z --presentation-at 2026-09-27T16:00:00Z \
    --presenter-doctor-id <doctor user UUID> [--patient-count 30]

`--presenter-doctor-id` is checked read-only against the configured database. `--as-of` fixes every
simulated date; rerunning with the same inputs reuses the dataset, different inputs need a new ID.
"""

import argparse
import sys
import uuid
from datetime import datetime

from app.db.session import get_sessionmaker
from app.ml.data.config import DatasetError
from app.ml.data.showcase import prepare_showcase
from app.models import User, UserRole


def _ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone, e.g. 2026-09-26T16:00:00Z")
    return ts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--as-of", type=_ts, required=True)
    parser.add_argument("--presentation-at", type=_ts, required=True)
    parser.add_argument("--presenter-doctor-id", type=uuid.UUID, required=True)
    parser.add_argument("--patient-count", type=int, default=30)
    args = parser.parse_args()
    with get_sessionmaker()() as db:
        doctor = db.get(User, args.presenter_doctor_id)
        if doctor is None or doctor.role != UserRole.DOCTOR:
            print("FAILED: --presenter-doctor-id is not a doctor account in the configured database")
            return 1
        print(f"presenter: {doctor.display_name} <{doctor.email}>")
    try:
        path, status = prepare_showcase(
            args.dataset_id,
            args.seed,
            args.as_of,
            args.presentation_at,
            args.presenter_doctor_id,
            args.patient_count,
        )
    except DatasetError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"{status}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
