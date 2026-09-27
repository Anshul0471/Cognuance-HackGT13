"""FastAPI entrypoint: `uvicorn app.main:app` (one worker for the local demo; guide 05 §2).

Startup never trains, seeds, or migrates. The lifespan only warms the verified active model
bundle (if forecasting is configured) and disposes the engine on shutdown.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import BodyLimitMiddleware, RequestContextMiddleware

CONTRACT_VERSION = "backend_contract_v1"
log = logging.getLogger("app.lifespan")


def _warm_model() -> None:
    """Best effort: verify/load the active bundle once. Failure is reported by /model/status."""
    from app.db.session import get_sessionmaker
    from app.ml.serving import ForecastUnavailable, load_model, resolve_active_pair

    try:
        with get_sessionmaker()() as db:
            model, _ = resolve_active_pair(db)
            load_model(model)
            log.info("model ready: %s %s", model.kind, model.version)
    except ForecastUnavailable as exc:
        log.warning("forecasting unavailable at startup: %s", exc.code)
    except Exception as exc:  # database down etc.: the API still serves patient data workflows
        log.warning("model warm-up skipped: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if get_settings().MODEL_MODE != "unconfigured":
        await run_in_threadpool(_warm_model)
    yield
    from app.db.session import get_engine

    get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title=settings.APP_NAME,
        version=CONTRACT_VERSION,
        description="Cognitive monitoring prototype API (synthetic/demo data only; not a diagnostic "
        "or emergency service). All errors use the shared `ErrorResponse` envelope.",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "Location", "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware)  # outermost: every response gets X-Request-ID
    app.include_router(api_router, prefix=settings.API_PREFIX)
    return app


app = create_app()
