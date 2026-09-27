"""Idempotently provision fictional demo accounts and doctor–patient assignments.

Run from backend/:  uv run python -m app.scripts.seed_demo

Every account uses DEMO_ACCOUNT_PASSWORD from backend/.env. Refuses to run when
APP_ENV=production or DEMO_MODE is false. Re-running updates changed fields and never duplicates.
Assessment histories are not seeded here; they arrive with the synthetic data pipeline (guide 03).
"""

import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import DataProvenance, DoctorPatientAssignment, PatientProfile, User, UserRole

DEMO_DOMAIN = "demo.test"  # reserved TLD: cannot collide with real addresses


@dataclass(frozen=True)
class DemoPatient:
    email: str
    display_name: str
    # Overview §12 demo trajectories; histories themselves are generated in a later phase.
    scenario: str
    doctor_email: str


DOCTORS = {
    f"dr.rivera@{DEMO_DOMAIN}": "Dr. Ana Rivera",
    f"dr.okafor@{DEMO_DOMAIN}": "Dr. Sam Okafor",
}

PATIENTS = [
    DemoPatient(f"eleanor.park@{DEMO_DOMAIN}", "Eleanor Park", "stable", f"dr.rivera@{DEMO_DOMAIN}"),
    DemoPatient(
        f"walter.hughes@{DEMO_DOMAIN}", "Walter Hughes", "single_deviation", f"dr.rivera@{DEMO_DOMAIN}"
    ),
    DemoPatient(
        f"rosa.delgado@{DEMO_DOMAIN}", "Rosa Delgado", "persistent_deviation", f"dr.rivera@{DEMO_DOMAIN}"
    ),
    DemoPatient(f"henry.lin@{DEMO_DOMAIN}", "Henry Lin", "insufficient_data", f"dr.rivera@{DEMO_DOMAIN}"),
    # Assigned to a different doctor: demonstrates that Dr. Rivera cannot see this record.
    DemoPatient(f"iris.novak@{DEMO_DOMAIN}", "Iris Novak", "stable", f"dr.okafor@{DEMO_DOMAIN}"),
]


@dataclass
class SeedSummary:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    assignments_created: int = 0


def _upsert_user(
    db: Session, email: str, name: str, role: UserRole, password: str, summary: SeedSummary
) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=name, role=role, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        summary.created.append(email)
        return user

    changed = False
    if user.display_name != name or user.role != role or not user.is_active:
        user.display_name, user.role, user.is_active = name, role, True
        changed = True
    if not verify_password(password, user.password_hash):
        user.password_hash = hash_password(password)
        changed = True
    (summary.updated if changed else summary.unchanged).append(email)
    return user


def seed_demo(db: Session, password: str) -> SeedSummary:
    summary = SeedSummary()
    doctors = {
        email: _upsert_user(db, email, name, UserRole.DOCTOR, password, summary)
        for email, name in DOCTORS.items()
    }

    for spec in PATIENTS:
        user = _upsert_user(db, spec.email, spec.display_name, UserRole.PATIENT, password, summary)
        profile = user.patient_profile
        if profile is None:
            profile = PatientProfile(user=user, provenance=DataProvenance.SYNTHETIC_SEED)
            db.add(profile)
        profile.demo_scenario = spec.scenario
        db.flush()

        doctor = doctors[spec.doctor_email]
        assignment = db.scalar(
            select(DoctorPatientAssignment).where(
                DoctorPatientAssignment.doctor_user_id == doctor.id,
                DoctorPatientAssignment.patient_id == profile.id,
            )
        )
        if assignment is None:
            db.add(DoctorPatientAssignment(doctor_user_id=doctor.id, patient_id=profile.id))
            summary.assignments_created += 1
        elif assignment.ended_at is not None:
            assignment.ended_at = None

    db.commit()
    return summary


def main() -> int:
    import argparse

    from app.core.provisioning import ProvisioningRefused, check_provisioning

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--hosted-demo", action="store_true", help="required (and only valid) with APP_ENV=demo"
    )
    args = parser.parse_args()
    settings = get_settings()
    try:
        check_provisioning(args.hosted_demo)
    except ProvisioningRefused as exc:
        print(f"Refusing to seed demo accounts: {exc}.")
        return 1
    if settings.DEMO_ACCOUNT_PASSWORD is None or len(settings.DEMO_ACCOUNT_PASSWORD.get_secret_value()) < 12:
        print("Set DEMO_ACCOUNT_PASSWORD (12+ characters) in backend/.env first.")
        return 1

    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as db:
        summary = seed_demo(db, settings.DEMO_ACCOUNT_PASSWORD.get_secret_value())

    counts = (len(summary.created), len(summary.updated), len(summary.unchanged))
    print("created: {}, updated: {}, unchanged: {}".format(*counts))
    print(f"new assignments: {summary.assignments_created}")
    print("Demo accounts (password = DEMO_ACCOUNT_PASSWORD in backend/.env):")
    for email, name in DOCTORS.items():
        print(f"  doctor   {email:28} {name}")
    for spec in PATIENTS:
        print(f"  patient  {spec.email:28} {spec.display_name} [{spec.scenario}] -> {spec.doctor_email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
