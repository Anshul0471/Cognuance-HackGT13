"""Write the immutable artifact bundle for a run's selected model and register it + its policies (inactive).

uv run --extra ml python -m app.scripts.register_forecaster --run-id forecast-run-v1
"""

# ruff: noqa: E501  (command lines and report rows read best unwrapped)

import argparse
import sys

from app.db.session import get_sessionmaker
from app.ml.data.config import DatasetError
from app.ml.models.registry import RegistryError, register_run
from app.ml.models.runs import RunError


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        with get_sessionmaker()() as db:
            result = register_run(db, args.run_id)
            db.commit()
    except (DatasetError, RunError, RegistryError) as exc:
        print(f"FAILED: {exc}")
        return 1
    print(
        f"model version: {result['model_version']} ({result['kind']}), bundle {result['bundle_status']}, "
        f"registry {result['db']}, activatable={result['model_activatable']}"
    )
    print(f"  bundle: {result['bundle']}")
    for pv, status in result["policies"].items():
        print(f"  policy {pv}: {status}")
    print(f"  reports copied: {result['reports'] or 'none'}")
    print("Nothing was activated. To serve it for new sessions:")
    for pv in result["policies"]:
        print(
            f"  uv run --extra ml python -m app.scripts.activate_forecaster --model-version {result['model_version']} "
            f"--policy-version {pv}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
