"""Estimate error scales (validation_calibration_clean) and select r (validation_calibration_all replay).

uv run --extra ml python -m app.scripts.calibrate_policy --run-id forecast-run-v1 --policy-version policy-v1
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.ml.data.config import DatasetError
from app.ml.data.exports import read_json
from app.ml.models.runs import RunError, calibrate_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--policy-version", required=True)
    args = parser.parse_args()
    try:
        pdir, outcome = calibrate_run(args.run_id, args.policy_version)
    except (DatasetError, RunError) as exc:
        print(f"FAILED: {exc}")
        return 1
    rep = read_json(pdir / "calibration_report.json")
    print(f"{outcome}: {pdir}  (model {rep['model_version']}, mode {rep['mode']})")
    print(f"  calibration windows {rep['calibration_windows']} from {rep['calibration_patients']} patients")
    for d, s in rep["scales"].items():
        print(
            f"  scale {d:17} {s['scale']:.4f} (raw RMSE {s['raw_rmse']}, bias {s['mean_residual']}, n {s['n']})"
        )
    print(f"  {'r':>4} {'clean alert frac':>18} {'alerts':>7} {'worsening det/analyzable':>25}")
    for c in rep["candidates"]:
        m = c["metrics"]
        f = m["clean_target_alert_fraction"]
        w = m["worsening_events"]
        print(
            f"  {c['r']:>4} {f['fraction']!s:>9} ({f['count']}/{f['n']}) {m['alerts']:>7} "
            f"{w['detected']:>10}/{w['analyzable']} ({w['conditional_detection_fraction']})"
        )
    print(
        f"  decision: {rep['decision']}, selected r = {rep['selected_r']}, activatable = {rep['activatable']}"
    )
    if rep["decision"] != "SELECTED":
        print("  Calibration did not produce an activatable policy (reported honestly; nothing activated).")
        return 0 if rep["mode"] != "FULL" else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
