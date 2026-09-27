"""Fixture commands for Playwright (isolated E2E database only; never a public endpoint).

uv run python -m tests.e2e.fixture revoke-assignment <doctor-email> <patient-id>
uv run python -m tests.e2e.fixture restore-assignment <doctor-email> <patient-id>
uv run python -m tests.e2e.fixture assessment-count <patient-id>
uv run python -m tests.e2e.fixture latest-analysis <patient-id>
uv run python -m tests.e2e.fixture alert-events <alert-id>
"""

import json
import os
import sys
import uuid

from tests.e2e import stack


def main(argv: list[str]) -> int:
    run = json.loads(stack.SECRETS.read_text())
    os.environ.update(stack.app_environment(stack.e2e_url(), run))

    from sqlalchemy import func, select

    from app.db.session import get_sessionmaker
    from app.models import Alert, AlertEvent, Analysis, Assessment, DoctorPatientAssignment, User

    cmd, *args = argv
    with get_sessionmaker()() as db:
        if cmd in ("revoke-assignment", "restore-assignment"):
            doctor = db.scalar(select(User).where(User.email == args[0]))
            row = db.scalar(
                select(DoctorPatientAssignment).where(
                    DoctorPatientAssignment.doctor_user_id == doctor.id,
                    DoctorPatientAssignment.patient_id == uuid.UUID(args[1]),
                )
            )
            row.ended_at = func.now() if cmd == "revoke-assignment" else None
            db.commit()
            print(json.dumps({"ok": True}))
        elif cmd == "assessment-count":
            print(
                json.dumps(
                    {
                        "count": db.scalar(
                            select(func.count())
                            .select_from(Assessment)
                            .where(Assessment.patient_id == uuid.UUID(args[0]))
                        )
                    }
                )
            )
        elif cmd == "latest-analysis":
            a = db.scalar(
                select(Assessment)
                .where(Assessment.patient_id == uuid.UUID(args[0]))
                .order_by(Assessment.observed_at.desc())
                .limit(1)
            )
            an = db.scalar(select(Analysis).where(Analysis.assessment_id == a.id))
            alert = db.scalar(select(Alert).where(Alert.analysis_id == an.id))
            print(
                json.dumps(
                    {
                        "assessment_id": str(a.id),
                        "source": a.source,
                        "quality": a.quality,
                        "availability": an.availability,
                        "deviation_level": an.deviation_level,
                        "alert_id": str(alert.id) if alert else None,
                    }
                )
            )
        elif cmd == "alert-events":
            print(
                json.dumps(
                    {
                        "count": db.scalar(
                            select(func.count())
                            .select_from(AlertEvent)
                            .where(AlertEvent.alert_id == uuid.UUID(args[0]))
                        )
                    }
                )
            )
        else:
            raise SystemExit(f"unknown command {cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
