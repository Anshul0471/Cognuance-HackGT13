"""Identity and access tables (overview §3, §10). PROVISIONAL until 01_database_and_auth.md.

Authorization facts live here: a user's role, the patient profile tied to a patient account, and
explicit doctor–patient assignments. The browser never supplies any of these.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"


class DataProvenance(StrEnum):
    """Where a record came from (overview §10: synthetic vs simulated vs live must stay distinct)."""

    SYNTHETIC_SEED = "synthetic_seed"
    LIVE = "live"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('patient', 'doctor')", name="role_valid"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    # Stored lowercased so the unique constraint is case-insensitive.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    patient_profile: Mapped["PatientProfile | None"] = relationship(back_populates="user")


class PatientProfile(TimestampMixin, Base):
    __tablename__ = "patient_profiles"
    __table_args__ = (CheckConstraint("provenance IN ('synthetic_seed', 'live')", name="provenance_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    # IANA zone for local display; storage is always UTC.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="America/New_York")
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    # Short demo scenario tag (e.g. "stable", "single_deviation"); null for non-demo patients.
    demo_scenario: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="patient_profile")
    assignments: Mapped[list["DoctorPatientAssignment"]] = relationship(back_populates="patient")


class DoctorPatientAssignment(TimestampMixin, Base):
    """Explicit relationship authorizing a doctor to access a patient. Ended by setting ended_at."""

    __tablename__ = "doctor_patient_assignments"
    __table_args__ = (
        UniqueConstraint("doctor_user_id", "patient_id", name="uq_assignment_doctor_patient"),
        Index("ix_assignments_patient_id", "patient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    doctor_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    doctor: Mapped[User] = relationship()
    patient: Mapped[PatientProfile] = relationship(back_populates="assignments")
