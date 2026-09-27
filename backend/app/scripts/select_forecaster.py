"""Compare LAST_VALUE, LINEAR_TREND and the GRU on identical validation-tune targets; freeze the choice.

uv run --extra ml python -m app.scripts.select_forecaster --run-id forecast-run-v1
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.exports import read_json
from app.ml.models.runs import RunError, select_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        path, outcome = select_run(args.run_id)
    except (DatasetError, RunError) as exc:
        print(f"FAILED: {exc}")
        return 1
    doc = read_json(path / "forecast_evaluation.json")
    print(f"{outcome}: {path / 'forecast_evaluation.json'}")
    print(f"  {'candidate':14} {'clean metric':>13} {'all metric':>11}   raw MAE mem / att / RT ms (clean)")
    for kind, res in doc["candidates"].items():
        c, a = res["validation_tune_clean"], res["validation_tune_all"]
        mae = " / ".join(f"{c['raw'][d]['mae']:.2f}" for d in ("memory", "attention", "reaction_time_ms"))
        print(f"  {kind:14} {c['selection_metric']:>13.4f} {a['selection_metric']:>11.4f}   {mae}")
    d = doc["decision"]
    print(f"  tied (1% rule): {d['tied']} -> selected {d['selected_kind']} ({doc['selected_model_version']})")
    g = d["gru_vs_best_baseline"]
    print(
        f"  GRU lower error than best baseline: {g['gru_lower_error']} (relative change {g['relative_change']})"
    )
    print(
        f"Next: uv run --extra ml python -m app.scripts.calibrate_policy --run-id {args.run_id} --policy-version policy-v1"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
