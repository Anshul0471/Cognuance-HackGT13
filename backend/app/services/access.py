"""Patient-record authorization. Every route touching patient data must go through here.

A patient may access only their own records; a doctor may access only patients with a current
(not ended) assignment to them. A deactivated *patient login* does not remove an active doctor's
access to history (shown as account_active=false); ending the assignment does. Inaccessible and
missing records are indistinguishable (404).
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import DoctorPatientAssignment, PatientProfile, User


def assigned_patient_ids(doctor: User) -> Select[tuple[uuid.UUID]]:
    """Scope applied before any filter, count or pagination."""
    return select(DoctorPatientAssignment.patient_id).where(
        DoctorPatientAssignment.doctor_user_id == doctor.id,
        DoctorPatientAssignment.ended_at.is_(None),
    )


def active_assignment(db: Session, doctor: User, patient_id: uuid.UUID) -> DoctorPatientAssignment | None:
    return db.scalar(
        select(DoctorPatientAssignment).where(
            DoctorPatientAssignment.doctor_user_id == doctor.id,
            DoctorPatientAssignment.patient_id == patient_id,
            DoctorPatientAssignment.ended_at.is_(None),
        )
    )


def get_assigned_patient(db: Session, doctor: User, patient_id: uuid.UUID) -> PatientProfile | None:
    if active_assignment(db, doctor, patient_id) is None:
        return None
    return db.get(PatientProfile, patient_id)
