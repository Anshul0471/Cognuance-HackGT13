"""Assessment sessions, submitted assessments, and context check-ins (guide 02).

PROVISIONAL physical schema until 01_database_and_auth.md is supplied; enum values follow
guide 02 and the project overview exactly.
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
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.identity import TimestampMixin


class SessionStatus(StrEnum):
    STARTED = "STARTED"
    SUBMITTED = "SUBMITTED"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"


class AssessmentSource(StrEnum):
    LIVE_DEMO = "LIVE_DEMO"  # the only value public endpoints may write
    SYNTHETIC_HISTORY = "SYNTHETIC_HISTORY"
    SCENARIO_REPLAY = "SCENARIO_REPLAY"


class InputMode(StrEnum):
    KEYBOARD = "keyboard"
    POINTER = "pointer"


class SchedulePurpose(StrEnum):
    SCHEDULED = "SCHEDULED"
    RETAKE_AFTER_UNRELIABLE = "RETAKE_AFTER_UNRELIABLE"
    EXTRA_ATTEMPT = "EXTRA_ATTEMPT"
    OFF_SCHEDULE = "OFF_SCHEDULE"


# Purposes that can become a slot's representative (weekly history point).
REPRESENTATIVE_PURPOSES = (SchedulePurpose.SCHEDULED, SchedulePurpose.RETAKE_AFTER_UNRELIABLE)


class Quality(StrEnum):
    VALID = "VALID"
    LOW = "LOW"
    INCOMPLETE = "INCOMPLETE"


class AnalysisState(StrEnum):
    PENDING = "PENDING"
    BUILDING_BASELINE = "BUILDING_BASELINE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    ANALYSIS_ERROR = "ANALYSIS_ERROR"
    COMPLETE = "COMPLETE"


class ForecastState(StrEnum):
    """Frozen at session start. READY means a `forecasts` row was persisted for the session."""

    READY = "READY"
    BUILDING_BASELINE = "BUILDING_BASELINE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class ProcessingStatus(StrEnum):
    """Submission processing (guide 05 §9): not whether an anomaly comparison was possible."""

    RECEIVED = "RECEIVED"  # phase A committed; analysis not finished (incl. waiting for a prior)
    ANALYZED = "ANALYZED"  # analysis finalized (COMPLETE or a terminal unavailable state)
    FAILED = "FAILED"  # retryable ANALYSIS_ERROR recorded


class MedicationChange(StrEnum):
    YES = "YES"
    NO = "NO"
    NOT_SURE = "NOT_SURE"


class ReportedBy(StrEnum):
    PATIENT = "PATIENT"
    CAREGIVER_ASSISTED = "CAREGIVER_ASSISTED"


def _in(column: str, enum: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in enum)})"


class AssessmentSession(TimestampMixin, Base):
    __tablename__ = "assessment_sessions"
    __table_args__ = (
        UniqueConstraint("patient_id", "start_key", name="uq_assessment_sessions_patient_start_key"),
        # Target of composite foreign keys (forecasts) that pin a record to its patient.
        UniqueConstraint("id", "patient_id", name="uq_assessment_sessions_id_patient"),
        Index("ix_assessment_sessions_patient_slot", "patient_id", "slot_index"),
        CheckConstraint(_in("status", SessionStatus), name="status_valid"),
        CheckConstraint(_in("source", AssessmentSource), name="source_valid"),
        CheckConstraint(_in("input_mode", InputMode), name="input_mode_valid"),
        CheckConstraint(_in("schedule_purpose", SchedulePurpose), name="schedule_purpose_valid"),
        CheckConstraint(_in("forecast_state", ForecastState), name="forecast_state_valid"),
        CheckConstraint("slot_index >= 0", name="slot_index_nonnegative"),
        CheckConstraint("expires_at > started_at", name="expiry_after_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    start_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule_purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Frozen before any answers exist; never rewritten from this session's results.
    forecast_state: Mapped[str] = mapped_column(String(32), nullable=False)
    forecast_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    history_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    protocol_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessment: Mapped["Assessment | None"] = relationship(back_populates="session")


class Assessment(TimestampMixin, Base):
    """One immutable submission per session."""

    __tablename__ = "assessments"
    __table_args__ = (
        Index("ix_assessments_patient_slot", "patient_id", "slot_index"),
        UniqueConstraint("id", "session_id", "patient_id", name="uq_assessments_id_session_patient"),
        # Submission keys are scoped to the owning patient (guide 05 §9).
        UniqueConstraint("patient_id", "submission_key", name="uq_assessments_patient_submission_key"),
        # At most one weekly representative per patient slot.
        Index(
            "uq_assessments_representative_per_slot",
            "patient_id",
            "slot_index",
            unique=True,
            postgresql_where=text("longitudinal_eligible"),
        ),
        CheckConstraint(_in("quality", Quality), name="quality_valid"),
        CheckConstraint(_in("source", AssessmentSource), name="source_valid"),
        CheckConstraint(_in("schedule_purpose", SchedulePurpose), name="schedule_purpose_valid"),
        CheckConstraint(_in("analysis_state", AnalysisState), name="analysis_state_valid"),
        CheckConstraint(_in("processing_status", ProcessingStatus), name="processing_status_valid"),
        CheckConstraint("memory_score BETWEEN 0 AND 100", name="memory_score_range"),
        CheckConstraint("attention_score BETWEEN 0 AND 100", name="attention_score_range"),
        CheckConstraint("reaction_time_ms >= 100 AND reaction_time_ms < 3000", name="reaction_time_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment_sessions.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    submission_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # SHA-256 of {session_id, canonical payload without submission_key}; same-key/different-body = conflict.
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_responses: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    memory_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    attention_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    reaction_time_ms: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    quality: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    longitudinal_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schedule_purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Server receipt time; forecast history requires available_at <= history_cutoff_at.
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_state: Mapped[str] = mapped_column(String(32), nullable=False)
    analysis_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False)

    session: Mapped[AssessmentSession] = relationship(back_populates="assessment")
    context: Mapped["ContextCheckin | None"] = relationship(back_populates="assessment")


class ContextCheckin(TimestampMixin, Base):
    __tablename__ = "context_checkins"
    __table_args__ = (
        CheckConstraint("sleep_hours BETWEEN 0 AND 24", name="sleep_hours_range"),
        CheckConstraint("mood_score BETWEEN 1 AND 10", name="mood_score_range"),
        CheckConstraint(_in("medication_change", MedicationChange), name="medication_change_valid"),
        CheckConstraint(_in("reported_by", ReportedBy), name="reported_by_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    # NULL means not reported (see missing_fields); 0 hours is a real answer.
    sleep_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    mood_score: Mapped[int | None] = mapped_column(SmallInteger)
    medication_change: Mapped[str | None] = mapped_column(String(16))
    reported_by: Mapped[str] = mapped_column(String(24), nullable=False)
    missing_fields: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)

    assessment: Mapped[Assessment] = relationship(back_populates="context")
