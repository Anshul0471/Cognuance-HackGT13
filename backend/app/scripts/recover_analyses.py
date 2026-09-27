"""Retry PENDING / ANALYSIS_ERROR analyses in patient/slot order (bounded, idempotent).

uv run --extra ml python -m app.scripts.recover_analyses [--limit 100]
There is no background queue: this command (or a replayed submission) completes unfinished
analyses. It uses the same service as submissions, never creates a post-assessment forecast, never
changes a finalized analysis and never duplicates alerts. Output lists IDs and sanitized reason
codes only (no answers).
"""

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.analyses import recover_analyses


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=get_settings().RECOVERY_DEFAULT_LIMIT)
    args = parser.parse_args()
    with get_sessionmaker()() as db:
        results = recover_analyses(db, datetime.now(UTC), limit=args.limit)
        db.commit()
    print(f"processed {len(results)} analyses: {dict(Counter(state for _, state, _ in results))}")
    for assessment_id, state, reason in results:
        if state != "COMPLETE":
            print(f"  {assessment_id}: {state} ({reason or 'no reason'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
