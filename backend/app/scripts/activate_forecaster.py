"""Verify and atomically activate a registered model/policy pair for NEW sessions.

uv run --extra ml python -m app.scripts.activate_forecaster --model-version <registered version> --policy-version policy-v1
Existing sessions keep the pair their forecast was issued under.
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.ml.models.registry import RegistryError, activate


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--policy-version", required=True)
    args = parser.parse_args()
    try:
        with get_sessionmaker()() as db:
            result = activate(db, args.model_version, args.policy_version)
            db.commit()
    except RegistryError as exc:
        print(f"FAILED ({exc.code}): {exc}")
        return 1
    print(
        f"active: {result['kind']} {result['model_version']} with policy {result['policy_version']} "
        f"(r={result['threshold_r']})"
    )
    mode = get_settings().MODEL_MODE
    needed = "gru" if result["kind"] == "GRU" else "baseline"
    if mode != needed:
        print(
            f"NOTE: MODEL_MODE is '{mode}'. Set MODEL_MODE={needed} in backend/.env and restart the API; "
            "until then /model/status reports forecasting unavailable (no silent relabeling)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
