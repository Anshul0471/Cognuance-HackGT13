# syntax=docker/dockerfile:1.7
# COGNUANCE API — Python 3.12, locked uv environment incl. the CPU-only `ml` extra (guide 07 §9).
# Build for the host architecture: docker build -t cognuance-api:<release> backend/

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
# Dependencies first (cached layer), exactly as locked; no dev dependencies in the runtime.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ml --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ml

FROM python:3.12-slim-bookworm
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app app
COPY --from=build /opt/venv /opt/venv
COPY --from=build --chown=app:app /app /app
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8000
# One worker (in-process login limiter and model cache are per process). No --reload.
# Proxy headers are honoured only from FORWARDED_ALLOW_IPS (the web container), set by compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
