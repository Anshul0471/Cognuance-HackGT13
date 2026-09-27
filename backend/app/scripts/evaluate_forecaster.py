"""Final frozen evaluation (once) on test_all, or on the separately generated stress set.

uv run --extra ml python -m app.scripts.evaluate_forecaster --run-id forecast-run-v1 --partition test
uv run --extra ml python -m app.scripts.evaluate_forecaster --run-id forecast-run-v1 --partition stress
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.exports import read_json
from app.ml.models.runs import RunError, evaluate_run, load_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--partition", required=True, choices=["test", "stress"])
    parser.add_argument("--policy-version", help="defaults to the run's only COMPLETE policy")
    parser.add_argument("--stress-dataset-id", default="stress-v1")
    args = parser.parse_args()
    try:
        policy = args.policy_version
        if policy is None:
            done = [
                p
                for p, s in load_run(args.run_id)[1]["stages"].get("calibrate", {}).items()
                if s.get("status") == "COMPLETE"
            ]
            if len(done) != 1:
                raise RunError(f"specify --policy-version (COMPLETE policies: {done})")
            policy = done[0]
        out, outcome = evaluate_run(
            args.run_id, args.partition, policy, stress_dataset_id=args.stress_dataset_id
        )
    except (DatasetError, RunError) as exc:
        print(f"FAILED: {exc}")
        return 1
    rep = read_json(out / "test_report.json")
    f, a = rep["forecast"]["all"], rep["alerts"]
    print(
        f"{outcome}: {out / 'test_report.json'}"
        + ("  (already evaluated once; not re-run)" if outcome == "reused" else "")
    )
    print(
        f"  {rep['model_kind']} {rep['model_version']} + {rep['policy_version']} (r={rep['policy_r']}) on {rep['partition']}"
    )
    print(
        f"  forecast: {f['n_windows']} windows / {f['n_patients']} patients, selection metric {f['selection_metric']}"
    )
    for kind, s in rep["forecast"]["same_target_comparison"].items():
        print(f"    {kind:14} metric {s['selection_metric']}")
    w = a["worsening_events"]
    print(f"  clean-target alert fraction {a['clean_target_alert_fraction']}")
    print(f"  no-event alert fraction {a['no_event_alert_fraction']}")
    print(f"  worsening events: {w['detected']} detected / {w['analyzable']} analyzable / {w['total']} total")
    print(
        f"  categories {a['category_counts']}; point precision {a['point_level']['precision']}, "
        f"recall {a['point_level']['recall']}"
    )
    print(
        f"  coverage: {rep['coverage']['analyzed']} analyzed of {rep['coverage']['slot_records']} slot records"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
