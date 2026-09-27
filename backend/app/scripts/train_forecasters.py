"""Train the GRU (train_clean; checkpoint on validation_tune_clean) and stage the baseline configs.

uv run --extra ml python -m app.scripts.train_forecasters --dataset-id full-v1 --run-id forecast-run-v1
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.exports import read_json
from app.ml.models.runs import RunError, train_run
from app.ml.models.training import TrainingFailure


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        path, outcome = train_run(args.dataset_id, args.run_id)
    except (DatasetError, RunError, TrainingFailure) as exc:
        print(f"FAILED: {exc}")
        return 1
    report = read_json(path / "candidates/GRU/training_report.json")
    print(f"{outcome}: {path}")
    print(
        f"  GRU: {report['epochs_run']} epochs (stopped early: {report['stopped_early']}), selected epoch "
        f"{report['selected_epoch']}, validation-tune selection metric {report['selected_tune_selection_metric']} "
        f"(initial {report['initial_tune_selection_metric']}), {report['runtime_seconds']} s, "
        f"{report['train_windows']} train windows"
    )
    print("  Baselines LAST_VALUE / LINEAR_TREND staged (no learned parameters).")
    print(f"Next: uv run --extra ml python -m app.scripts.select_forecaster --run-id {args.run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
