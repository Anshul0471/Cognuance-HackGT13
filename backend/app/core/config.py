"""Validated application settings loaded from environment variables and backend/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory, independent of the process working directory.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # "demo" = hosted fictional-data demo (guide 07 §10): production-like serving; data provisioning
    # additionally needs an explicit --hosted-demo CLI opt-in (app.core.provisioning).
    APP_ENV: Literal["development", "test", "demo", "production"] = "development"
    APP_NAME: str = "COGNUANCE"  # display title only (API docs); technical identifiers keep their names
    API_PREFIX: str = "/api/v1"

    # SecretStr keeps the embedded password out of reprs and logs.
    DATABASE_URL: SecretStr
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    JWT_SECRET: SecretStr
    # Required `iss`/`aud` claims (guide 07 §4.1, §10); tokens from another issuer/audience are rejected.
    JWT_ISSUER: str = Field(default="cognuance-api", min_length=1)
    JWT_AUDIENCE: str = Field(default="cognuance-web", min_length=1)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0, le=24 * 60)

    ML_DEVICE: Literal["cpu", "mps", "cuda"] = "cpu"
    MODEL_MODE: Literal["unconfigured", "baseline", "gru"] = "unconfigured"
    MODEL_ARTIFACT_DIR: Path = Path("./artifacts")
    SYNTHETIC_DATA_DIR: Path = Path("./data/synthetic")
    SEQUENCE_LENGTH: int = Field(default=6, ge=1, le=100)
    RANDOM_SEED: int = 42

    # Labels data as synthetic/demo in the UI. Never bypasses authorization.
    DEMO_MODE: bool = True
    # Password given to every seeded demo account by app.scripts.seed_demo. Local use only.
    DEMO_ACCOUNT_PASSWORD: SecretStr | None = None
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # guide 05 §16 — operational limits (defaults documented in .env.example and README).
    # In-process login limiter: one API worker for the local demo (guide 05 §2).
    LOGIN_MAX_FAILURES: int = Field(default=5, ge=1, le=100)
    LOGIN_WINDOW_SECONDS: int = Field(default=300, ge=10, le=86400)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=5000, ge=100, le=120000)
    DB_LOCK_TIMEOUT_MS: int = Field(default=3000, ge=100, le=60000)
    # Signed pagination cursors (key derived from JWT_SECRET for a separate purpose).
    CURSOR_TTL_SECONDS: int = Field(default=3600, ge=60, le=86400)
    RECOVERY_DEFAULT_LIMIT: int = Field(default=100, ge=1, le=10000)

    @field_validator("MODEL_ARTIFACT_DIR", "SYNTHETIC_DATA_DIR")
    @classmethod
    def _resolve_relative_to_backend(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @field_validator("API_PREFIX")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        return "/" + value.strip("/")

    @field_validator("DATABASE_URL")
    @classmethod
    def _require_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use the postgresql+psycopg:// driver")
        return value

    # Interactive /docs + /openapi.json: on for development/test, off for demo/production unless set.
    API_DOCS_ENABLED: bool | None = None

    @property
    def docs_enabled(self) -> bool:
        if self.API_DOCS_ENABLED is not None:
            return self.API_DOCS_ENABLED
        return self.APP_ENV in ("development", "test")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required values come from the environment
