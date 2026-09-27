"""Export the application's actual OpenAPI contract to backend/openapi.json.

uv run --extra ml python -m app.scripts.export_openapi [--check]
`--check` exits non-zero if the committed file differs from the running app's schema.
"""

import argparse
import json
import sys

from app.core.config import BACKEND_DIR

OUTPUT = BACKEND_DIR / "openapi.json"


def render() -> str:
    from app.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.check:
        same = OUTPUT.exists() and OUTPUT.read_text() == text
        status = "current" if same else "OUT OF DATE; re-export it"
        print(f"backend/openapi.json is {status}")
        return 0 if same else 1
    OUTPUT.write_text(text)
    schema = json.loads(text)
    print(f"wrote {OUTPUT} ({len(schema['paths'])} paths, {len(schema['components']['schemas'])} schemas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
