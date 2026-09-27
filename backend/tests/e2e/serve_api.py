"""Provision the isolated E2E database, then serve the API on 127.0.0.1:8100 (Playwright webServer).

uv run --extra ml python -m tests.e2e.serve_api
"""

import os
import sys

from sqlalchemy import create_engine, text

from tests.e2e import stack


def provision() -> dict:
    url = stack.e2e_url()
    admin = create_engine(url.set(database="cognuance_test"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:  # only the guarded, disposable E2E database is recreated
        conn.execute(text(f'DROP DATABASE IF EXISTS "{stack.E2E_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{stack.E2E_DB}"'))
    admin.dispose()

    run = stack.run_secrets()
    stack.fresh_workspace()
    os.environ.update(stack.app_environment(url, run))

    from alembic import command
    from alembic.config import Config

    from app.core.config import BACKEND_DIR

    config = Config(str(BACKEND_DIR / "alembic.ini"))  # never import tests.conftest (it rewrites env)
    config.attributes["database_url"] = url.render_as_string(hide_password=False)
    command.upgrade(config, "head")

    from sqlalchemy import select

    from app.db.session import get_sessionmaker
    from app.ml.data.showcase import import_showcase, prepare_showcase, verify_showcase
    from app.ml.models import registry
    from app.models import User
    from app.scripts.seed_demo import seed_demo

    maker = get_sessionmaker()
    with maker() as db:
        seed_demo(db, run["demo_password"])
        registry.register_run(db, "forecast-run-v1")
        registry.activate(db, "forecast-run-v1-gru", "policy-v1")
        db.commit()
        presenter = db.scalar(select(User).where(User.email == "dr.okafor@demo.test"))
        as_of, presentation = stack.window_times()
        prepare_showcase("e2e-showcase", 20260927, as_of, presentation, presenter.id)
        imported = import_showcase(db, "e2e-showcase")
        report = verify_showcase(db, "e2e-showcase")
    if imported["failures"] or report["problems"]:
        raise SystemExit(f"E2E provisioning failed: {imported['failures']} {report['problems']}")

    import json

    creds = json.loads((stack.WORKSPACE / "showcase-private" / "e2e-showcase.credentials.json").read_text())
    manifest = json.loads(
        (stack.WORKSPACE / "synthetic" / "showcase" / "e2e-showcase" / "manifest.json").read_text()
    )
    featured = report["featured"]
    env = {
        "baseURL": f"http://127.0.0.1:{stack.WEB_PORT}",
        "apiURL": f"http://127.0.0.1:{stack.API_PORT}/api/v1",
        "presenter": {"email": "dr.okafor@demo.test", "password": run["demo_password"]},
        "rivera": {"email": "dr.rivera@demo.test", "password": run["demo_password"]},
        "secondaryDoctor": {
            "email": "dr.lena.hart@showcase.example",
            "password": creds["dr.lena.hart@showcase.example"],
        },
        "livePatient": {
            **featured["live_assessment"],
            "password": creds[featured["live_assessment"]["email"]],
        },
        "abrupt": featured["abrupt_change"],
        "steady": featured["steady_control"],
        "secondaryPatient": next(p for p in manifest["patients"] if p["doctor"] == "secondary"),
        "counts": {"assigned": report["presenter_total_assigned"], "alerts": report["alerts"]},
    }
    stack.private_write(stack.ENV_OUT, env)
    return env


def main() -> int:
    provision()
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=stack.API_PORT, workers=1, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
