"""Small fictional demo histories for already-seeded demo patients (guide 03 §16).

`prepare_demo` builds and validates files only. `import_demo` performs controlled, idempotent
database writes through the same services as live submissions (`build_frozen_session`,
`score_submission`, `record_submission`), with source `SYNTHETIC_HISTORY` and simulated clocks.
The anchor is chosen so each patient's *next* weekly target falls inside the real current window,
which lets a live check-in follow the synthetic history without backdating anything.
"""

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.data import exports
from app.ml.data.config import DatasetError, dataset_dir, profile, synthetic_root
from app.ml.data.generator import DOMAINS, Event, Overrides, fixture_plans, generate_population, make_id, plan_patient
from app.models import AssessmentSession, AssessmentSource, DataProvenance, PatientProfile, SchedulePurpose, User
from app.schemas.assessments import AssessmentSubmission, StartSessionRequest
from app.services.assessment_sessions import build_frozen_session, lock_patient, representatives, scheduled_starts
from app.services.assessment_submissions import payload_digest, record_submission
from app.services.analyses import process_assessment
from app.services.forecasts import history_ready
from app.services.scoring import score_submission

DEMO_SCENARIOS = ("stable", "single_deviation", "persistent_deviation", "insufficient_data")
_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SCHEDULE_REASON = {
    "SCHEDULED": "IN_WINDOW",
    "RETAKE_AFTER_UNRELIABLE": "RETAKE_AFTER_UNRELIABLE",
    "EXTRA_ATTEMPT": "SLOT_COMPLETED",
}


def demo_root() -> Path:
    return synthetic_root() / "demo"


def _load_mapping(mapping_path: Path) -> list[dict[str, Any]]:
    if not mapping_path.exists():
        raise DatasetError(
            f"mapping file {mapping_path} not found; copy app/ml/data/demo_mapping.example.json there and edit it"
        )
    entries = json.loads(mapping_path.read_text())["demo_patients"]
    keys = set()
    for e in entries:
        if set(e) != {"demo_key", "patient_email", "scenario", "history_slots"}:
            raise DatasetError(f"mapping entry must have exactly demo_key, patient_email, scenario, history_slots: {e}")
        if not _KEY.match(e["demo_key"]) or e["demo_key"] in keys:
            raise DatasetError(f"invalid or duplicate demo_key {e['demo_key']!r}")
        if not e["patient_email"].endswith("@demo.test"):
            raise DatasetError("demo imports may only target fictional @demo.test accounts")
        if e["scenario"] not in DEMO_SCENARIOS:
            raise DatasetError(f"scenario must be one of {DEMO_SCENARIOS}")
        if not isinstance(e["history_slots"], int) or not 6 <= e["history_slots"] <= 20:
            raise DatasetError("history_slots must be an integer 6–20")
        keys.add(e["demo_key"])
    return entries


def _plan(entry: dict[str, Any], index: int, identity: str, anchor: datetime):
    n = entry["history_slots"]
    config = replace(profile("smoke"), profile="demo", slots_per_patient=n)
    # Start from the clean fixture template (stable levels, no random faults) in the demo population.
    plan = plan_patient(config, identity, "demo", index)
    template = fixture_plans(config, identity)[0]
    plan.params.update({k: template.params[k] for k in ("recall_p0", "hit_p0", "false_alarm_p0", "rt_median0_ms",
                                                        "recall_hit_trend", "false_alarm_trend", "log_rt_trend")})
    plan.trajectory, plan.anchor, plan.scenario = "stable", anchor, entry["scenario"]
    plan.event, plan.overrides = None, Overrides(force_clean=True)
    if entry["scenario"] == "persistent_deviation":
        plan.event = Event("persistent_worsening", n - 3, 3, DOMAINS, recall_hit_delta=-0.3, false_alarm_delta=0.15, log_rt_delta=0.3)
    elif entry["scenario"] == "insufficient_data":
        # A missed recent week plus an interrupted one: the next forecast has a history gap.
        plan.overrides = Overrides(force_clean=True, missing_slots={n - 2}, faults={n - 4: "HIDDEN_TAB_ATTENTION"})
    return config, plan


def prepare_demo(demo_id: str, mapping_path: Path, now: datetime | None = None, root: Path | None = None) -> tuple[Path, str]:
    base = root or demo_root()
    final = dataset_dir(demo_id, base)
    if final.exists():
        manifest = exports.read_json(final / "manifest.json")
        if manifest.get("status") != "COMPLETE":
            raise DatasetError(f"{final} exists but is incomplete; remove it deliberately")
        return final, "reused"
    entries = _load_mapping(mapping_path)
    now = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    identity = hashlib.sha256(f"demo/{demo_id}".encode()).hexdigest()[:16]
    sessions, observations, patients = [], [], []
    for index, entry in enumerate(entries):
        n = entry["history_slots"]
        # Next target (slot n) lands 2 h from now: inside the real ±12 h window.
        anchor = now + timedelta(hours=2) - timedelta(days=7 * n)
        config, plan = _plan(entry, index, identity, anchor)
        out = generate_population(config, identity, "demo", [plan])
        for r in out.raw_sessions:
            sessions.append({**r, "demo_key": entry["demo_key"]})
        observations += [{**o, "demo_key": entry["demo_key"]} for o in out.observations]
        patients.append({**entry, "anchor_at": anchor.isoformat(), "next_target_at": (anchor + timedelta(days=7 * n)).isoformat()})

    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{demo_id}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        exports.write_jsonl(tmp / "sessions.jsonl", sorted(sessions, key=lambda s: (s["demo_key"], s["started_at"], s["attempt"])))
        exports.write_jsonl(tmp / "observations.jsonl", sorted(observations, key=lambda o: (o["demo_key"], o["slot_index"], o["attempt"])))
        files = exports.file_hashes(tmp, ["sessions.jsonl", "observations.jsonl"])
        exports.write_json(tmp / "manifest.json", {
            "demo_id": demo_id, "status": "COMPLETE", "synthetic": True, "source": "SYNTHETIC_HISTORY",
            "generated_at": exports.now_iso(), "identity": identity, "patients": patients, "files": files,
            "note": "Fictional demo histories with simulated observation clocks; passwords are never stored here.",
        })
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final, "created"


def import_demo(db: Session, demo_id: str, root: Path | None = None, hosted_demo: bool = False) -> list[str]:
    from app.core.provisioning import ProvisioningRefused, check_provisioning

    try:
        check_provisioning(hosted_demo)
    except ProvisioningRefused as exc:
        raise DatasetError(str(exc)) from None
    path = dataset_dir(demo_id, root or demo_root())
    manifest = exports.read_json(path / "manifest.json")
    if manifest.get("status") != "COMPLETE":
        raise DatasetError("demo files are not COMPLETE; run prepare_demo_data")
    for name, digest in manifest["files"].items():
        if exports.sha256_file(path / name) != digest:
            raise DatasetError(f"checksum mismatch in {name}")
    sessions = list(exports.read_jsonl(path / "sessions.jsonl"))
    outcomes = []
    for entry in manifest["patients"]:
        rows = sorted((s for s in sessions if s["demo_key"] == entry["demo_key"]), key=lambda s: (s["started_at"], s["attempt"]))
        outcomes.append(_import_patient(db, entry, rows))
    return outcomes


def _import_patient(db: Session, entry: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """One transaction per patient. Identical re-import is a no-op; a changed payload is a conflict."""
    email = entry["patient_email"]
    profile_row = db.scalar(select(PatientProfile).join(User).where(User.email == email))
    if profile_row is None:
        return f"{entry['demo_key']}: SKIPPED — no seeded patient {email} (run seed_demo first)"
    if profile_row.provenance != DataProvenance.SYNTHETIC_SEED:
        return f"{entry['demo_key']}: SKIPPED — {email} is not a synthetic demo patient"
    lock_patient(db, profile_row.id)
    demo_ids = {uuid.UUID(r["session_id"]) for r in rows}
    existing = set(db.scalars(select(AssessmentSession.id).where(AssessmentSession.patient_id == profile_row.id)))
    unrelated = existing - demo_ids
    if unrelated:
        db.rollback()
        return (f"{entry['demo_key']}: SKIPPED — {email} already has {len(unrelated)} other session(s); "
                "not mixing histories or deleting records")
    anchor = datetime.fromisoformat(entry["anchor_at"])
    created = unchanged = 0
    try:
        for r in rows:
            session_id = uuid.UUID(r["session_id"])
            payload = AssessmentSubmission.model_validate(r["raw_submission"])
            digest = payload_digest(session_id, payload)
            prior = db.get(AssessmentSession, session_id)
            if prior is not None:
                if prior.assessment is None or prior.assessment.payload_sha256 != digest:
                    raise DatasetError(f"conflict: session {session_id} exists with a different payload")
                unchanged += 1
                continue
            purpose = SchedulePurpose(r["schedule_purpose"])
            req = StartSessionRequest(
                start_key=uuid.UUID(make_id("demo-start", r["session_id"])),
                input_mode=r["input_mode"],
                device_changed=bool(r["device_changed"]),
                navigation_assistance=False,
                allow_unscheduled=purpose == SchedulePurpose.EXTRA_ATTEMPT,
            )
            session = build_frozen_session(
                patient_id=profile_row.id,
                req=req,
                started_at=datetime.fromisoformat(r["started_at"]),
                anchor=anchor,
                slot=r["slot_index"],
                target=datetime.fromisoformat(r["target_at"]),
                purpose=purpose,
                schedule_reason=SCHEDULE_REASON[purpose.value],
                starts=scheduled_starts(db, profile_row.id, r["slot_index"]),
                reps=representatives(db, profile_row.id),
                task_protocol=r["protocol_snapshot"],
                source=AssessmentSource.SYNTHETIC_HISTORY,
                session_id=session_id,
            )
            if history_ready(session):
                # History sufficed, but no forecast was issued in (simulated) real time; never backfilled.
                session.forecast_reasons = ["MODEL_UNAVAILABLE", "HISTORICAL_IMPORT"]
            db.add(session)
            db.flush()
            scoring = score_submission(r["protocol_snapshot"], payload, r["input_mode"])
            received = datetime.fromisoformat(r["available_at"])
            assessment = record_submission(db, session, payload, digest, scoring, received_at=received)
            process_assessment(db, assessment.id, received)  # terminal: imported history has no forecast
            created += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return f"{entry['demo_key']}: {email} — {created} session(s) imported, {unchanged} already present"
