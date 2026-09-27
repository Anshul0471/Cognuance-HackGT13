"""Model registry, calibrated policies, frozen forecasts, analyses and alerts (guide 04 §11, §14, §16).

PROVISIONAL physical schema until 01_database_and_auth.md is supplied. Composite foreign keys tie
each forecast/analysis/alert to one patient, one session and one exact model/policy pair, so a
historical result can never be re-attributed to whichever model is active today.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.assessment import AnalysisState, _in
from app.models.identity import TimestampMixin


class ModelKind(StrEnum):
    LAST_VALUE = "LAST_VALUE"
    LINEAR_TREND = "LINEAR_TREND"
    GRU = "GRU"


class DeviationLevel(StrEnum):
    NORMAL = "NORMAL"
    REVIEW = "REVIEW"
    PERSISTENT_DEVIATION = "PERSISTENT_DEVIATION"
    HIGH_DEVIATION = "HIGH_DEVIATION"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class AlertAction(StrEnum):
    CREATED = "CREATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    NOTE_ADDED = "NOTE_ADDED"
    RESOLVED = "RESOLVED"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


class ModelVersion(TimestampMixin, Base):
    """Immutable registered forecasting model content (weights/formula + preprocessing identity)."""

    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(_in("kind", ModelKind), name="kind_valid"),
        CheckConstraint("NOT is_active OR activatable", name="active_requires_activatable"),
        Index(
            "uq_model_versions_single_active", "is_active", unique=True, postgresql_where=text("is_active")
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    postprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative to settings.MODEL_ARTIFACT_DIR; points at the bundle manifest.
    artifact_relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_order: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sequence_length: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    activatable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnomalyPolicy(TimestampMixin, Base):
    """Immutable calibrated deviation policy bound to exactly one model version."""

    __tablename__ = "anomaly_policies"
    __table_args__ = (
        UniqueConstraint("id", "model_version_id", name="uq_anomaly_policies_id_model"),
        CheckConstraint("NOT is_active OR activatable", name="active_requires_activatable"),
        Index(
            "uq_anomaly_policies_single_active", "is_active", unique=True, postgresql_where=text("is_active")
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    policy_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # The actual serving rules (scales, r, multipliers, persistence); never edited after insert.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Relative file paths + checksums of policy.json / calibration_report.json, and provenance.
    calibration_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    activatable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Forecast(TimestampMixin, Base):
    """A prediction frozen at session start, before any answers exist. Never rewritten."""

    __tablename__ = "forecasts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "patient_id"],
            ["assessment_sessions.id", "assessment_sessions.patient_id"],
            name="fk_forecasts_session_patient",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["policy_id", "model_version_id"],
            ["anomaly_policies.id", "anomaly_policies.model_version_id"],
            name="fk_forecasts_policy_model",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "id", "session_id", "patient_id", "model_version_id", "policy_id", name="uq_forecasts_identity"
        ),
        CheckConstraint("predicted_memory_score BETWEEN 0 AND 100", name="memory_range"),
        CheckConstraint("predicted_attention_score BETWEEN 0 AND 100", name="attention_range"),
        CheckConstraint(
            "predicted_reaction_time_ms >= 100 AND predicted_reaction_time_ms <= 2999.999", name="rt_range"
        ),
        CheckConstraint("issued_at <= history_cutoff_at + interval '1 minute'", name="issued_at_cutoff"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    history_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_memory_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    predicted_attention_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    predicted_reaction_time_ms: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    bounds_applied: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Ordered oldest → newest; one per history slot.
    input_assessment_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Raw allow-listed history values, the transformed 9-channel matrix, and their SHA-256.
    feature_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    feature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    comparability_key: Mapped[str] = mapped_column(String(160), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    postprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)


class Analysis(TimestampMixin, Base):
    """Comparison of one submitted assessment with its session's stored forecast (one per assessment)."""

    __tablename__ = "analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "session_id", "patient_id"],
            ["assessments.id", "assessments.session_id", "assessments.patient_id"],
            name="fk_analyses_assessment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["forecast_id", "session_id", "patient_id", "model_version_id", "policy_id"],
            [
                "forecasts.id",
                "forecasts.session_id",
                "forecasts.patient_id",
                "forecasts.model_version_id",
                "forecasts.policy_id",
            ],
            name="fk_analyses_forecast",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "patient_id", name="uq_analyses_id_patient"),
        CheckConstraint(_in("availability", AnalysisState), name="availability_valid"),
        CheckConstraint(
            f"deviation_level IS NULL OR {_in('deviation_level', DeviationLevel)}",
            name="deviation_level_valid",
        ),
        # Only a COMPLETE analysis carries a deviation level, and it always does.
        CheckConstraint(
            "(availability = 'COMPLETE') = (deviation_level IS NOT NULL)", name="level_iff_complete"
        ),
        CheckConstraint("persistent_count IS NULL OR persistent_count >= 0", name="persistent_count_nonneg"),
        CheckConstraint(
            "(forecast_id IS NULL) = (model_version_id IS NULL) "
            "AND (forecast_id IS NULL) = (policy_id IS NULL)",
            name="forecast_link_all_or_none",
        ),
        CheckConstraint(
            "availability <> 'COMPLETE' OR forecast_id IS NOT NULL", name="complete_needs_forecast"
        ),
        Index("ix_analyses_patient_availability", "patient_id", "availability"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Null when the session had no preissued forecast (terminal unavailable analysis).
    forecast_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    comparability_key: Mapped[str | None] = mapped_column(String(160))
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    deviation_level: Mapped[str | None] = mapped_column(String(32))
    domain_deviations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    max_deviation: Mapped[float | None] = mapped_column(Double)
    aggregate_deviation: Mapped[float | None] = mapped_column(Double)
    moderate_signal: Mapped[bool | None] = mapped_column(Boolean)
    high_signal: Mapped[bool | None] = mapped_column(Boolean)
    persistent_count: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation_version: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(TimestampMixin, Base):
    """Doctor review item for a non-NORMAL COMPLETE analysis. At most one per assessment."""

    __tablename__ = "alerts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id", "patient_id"],
            ["analyses.id", "analyses.patient_id"],
            name="fk_alerts_analysis_patient",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_in("status", AlertStatus), name="status_valid"),
        CheckConstraint(
            "deviation_level IN ('REVIEW', 'PERSISTENT_DEVIATION', 'HIGH_DEVIATION')", name="level_not_normal"
        ),
        Index("ix_alerts_patient_status", "patient_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    deviation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Optimistic concurrency: every accepted human review event increments it.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class AlertEvent(Base):
    """Append-only review/audit history for an alert (CREATED is written with the alert)."""

    __tablename__ = "alert_events"
    __table_args__ = (
        CheckConstraint(_in("action", AlertAction), name="action_valid"),
        # Review idempotency: one event per (alert, request_key); NULL for system CREATED events.
        UniqueConstraint("alert_id", "request_key", name="uq_alert_events_alert_request_key"),
        CheckConstraint("(action = 'CREATED') = (request_key IS NULL)", name="request_key_iff_human"),
        Index("ix_alert_events_alert_created", "alert_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_key: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # SHA-256 of {actor, action, canonical note, expected_lock_version}: replay vs conflict.
    request_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
