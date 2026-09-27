"""Serving-side model loading and active pair resolution (guide 04 §14, §16).

Bundles are verified (manifest digest vs DB, file hashes, feature schema) before every use; the
reconstructed model is cached per (model id, manifest digest). Nothing here trains or falls back
silently: any problem becomes a sanitized `ForecastUnavailable` code and the session records
MODEL_UNAVAILABLE.
"""

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.data import exports
from app.models import AnomalyPolicy, ModelVersion

_KIND_FOR_MODE = {"baseline": {"LAST_VALUE", "LINEAR_TREND"}, "gru": {"GRU"}}


class ForecastUnavailable(Exception):
    """`code` is a sanitized reason stored on the session (no paths or stack traces)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class LoadedModel:
    id: uuid.UUID
    version: str
    kind: str
    params: dict[str, Any]
    config: dict[str, Any]
    module: Any  # torch module for GRU, None for baselines


_cache: dict[tuple[uuid.UUID, str], LoadedModel] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def load_model(row: ModelVersion, root: Path | None = None) -> LoadedModel:
    from app.ml.models.registry import RegistryError, verify_model_row

    key = (row.id, row.artifact_sha256)
    try:
        # Hashes are re-verified on every use (cheap: small files); the cache only skips rebuilding.
        bundle, _ = verify_model_row(row, root)
    except RegistryError as exc:
        raise ForecastUnavailable(exc.code) from None
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        params = exports.read_json(bundle / "preprocessing.json")
        config = exports.read_json(bundle / "model_config.json")
        module = None
        if row.kind == "GRU":
            try:
                import torch

                from app.ml.models.gru import build_model
            except ImportError:
                raise ForecastUnavailable("TORCH_NOT_INSTALLED") from None
            module = build_model(config)
            state = torch.load(bundle / "weights.pt", map_location="cpu", weights_only=True)
            module.load_state_dict(state, strict=True)
            module.eval()
        elif config.get("kind") != row.kind:
            raise RegistryError("model_config kind mismatch", "ARTIFACT_VERSION_MISMATCH")
    except RegistryError as exc:
        raise ForecastUnavailable(exc.code) from None
    except (ValueError, KeyError, RuntimeError, OSError):
        raise ForecastUnavailable("ARTIFACT_LOAD_FAILED") from None
    loaded = LoadedModel(row.id, row.version, row.kind, params, config, module)
    with _lock:
        _cache[key] = loaded
    return loaded


def resolve_active_pair(db: Session) -> tuple[ModelVersion, AnomalyPolicy]:
    """The active model and its active calibrated policy, as one consistent pair."""
    mode = get_settings().MODEL_MODE
    if mode == "unconfigured":
        raise ForecastUnavailable("MODEL_NOT_CONFIGURED")
    model = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    policy = db.scalar(select(AnomalyPolicy).where(AnomalyPolicy.is_active.is_(True)))
    if model is None or policy is None:
        raise ForecastUnavailable("NO_ACTIVE_MODEL")
    if policy.model_version_id != model.id:
        raise ForecastUnavailable("POLICY_MODEL_MISMATCH")
    if model.kind not in _KIND_FOR_MODE[mode]:
        # Never serve a baseline under a GRU label (or vice versa).
        raise ForecastUnavailable("MODEL_MODE_MISMATCH")
    return model, policy


def readiness(db: Session) -> dict[str, Any]:
    """Patient-free status: active kind/version, loaded, policy ready, forecast ready, failure code."""
    from app.ml.models.anomaly import PolicyError, PolicyRules

    out: dict[str, Any] = {
        "active_model_kind": None,
        "active_model_version": None,
        "active_policy_version": None,
        "model_loaded": False,
        "policy_ready": False,
        "forecast_ready": False,
        "failure_code": None,
    }
    model = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    policy = db.scalar(select(AnomalyPolicy).where(AnomalyPolicy.is_active.is_(True)))
    if model is not None:
        out.update(active_model_kind=model.kind, active_model_version=model.version)
    if policy is not None:
        out["active_policy_version"] = policy.version
    try:
        model, policy = resolve_active_pair(db)
        load_model(model)
        out["model_loaded"] = True
        try:
            PolicyRules.from_configuration(policy.configuration)
        except PolicyError:
            raise ForecastUnavailable("POLICY_INVALID") from None
        out["policy_ready"] = True
        out["forecast_ready"] = True
    except ForecastUnavailable as exc:
        out["failure_code"] = exc.code
    return out
