"""Presentation showcase dataset (refinement 03 §4–§8, refinement 04 §6–§8).

Three stages, each a thin coordinator over the existing services (no parallel persistence path):

* `prepare_showcase` — files only. A fixed manifest (seed, explicit `as_of`, presentation window,
  presenter/secondary doctor IDs, patient keys, scenario families) plus raw protocol payloads from
  the guide-03 generator in the disjoint `showcase` population. Scenario families live only here,
  never in display names or API responses.
* `import_showcase` — controlled DB writes. Identity: creates users/profiles/assignments that do
  not exist (random passwords → private credentials file; never resets a password or reopens an
  ended assignment). History: **chronological replay** per patient — `build_frozen_session` at the
  simulated start, `issue_forecast` from representatives available before that cutoff, canonical
  scoring, `record_submission`, `process_assessment` — with source `SCENARIO_REPLAY` (or
  `SYNTHETIC_HISTORY` without forecasts for the forecast-unavailable family). Reviews: real
  `reviews.record_event` calls at the actual current time with deterministic request keys and
  expected lock versions, so a rerun replays or skips and never overrides later presenter changes.
* `verify_showcase` — read-only counts, score/chronology/authorization checks, featured examples.

Identical reruns are no-ops (deterministic IDs + payload digests); a changed payload under an
existing session ID is a conflict. A new population or date anchor needs a new dataset ID.
"""

import hashlib
import json
import os
import random
import secrets
import shutil
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.security import hash_password
from app.ml.data import exports
from app.ml.data.config import DatasetError, dataset_dir, profile, synthetic_root
from app.ml.data.generator import DOMAINS, Event, Overrides, generate_population, make_id, plan_patient
from app.models import (
    Alert,
    Analysis,
    Assessment,
    AssessmentSession,
    AssessmentSource,
    DataProvenance,
    DoctorPatientAssignment,
    Forecast,
    PatientProfile,
    SchedulePurpose,
    User,
    UserRole,
)
from app.schemas.assessments import AssessmentSubmission, StartSessionRequest
from app.schemas.doctor import AlertEventRequest
from app.services import reviews
from app.services.analyses import process_assessment
from app.services.assessment_sessions import (
    build_frozen_session,
    lock_patient,
    representatives,
    scheduled_starts,
)
from app.services.assessment_submissions import payload_digest, record_submission
from app.services.forecasts import history_ready, issue_forecast
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION
from app.services.scoring import score_submission

SHOWCASE_DOMAIN = "showcase.example"  # reserved TLD: cannot collide with a real address
POPULATION = "showcase"
MANIFEST_VERSION = "showcase_manifest_v1"
SCHEDULE_REASON = {
    "SCHEDULED": "IN_WINDOW",
    "RETAKE_AFTER_UNRELIABLE": "RETAKE_AFTER_UNRELIABLE",
    "EXTRA_ATTEMPT": "SLOT_COMPLETED",
}

# Scenario families (generation targets, not guaranteed model outcomes) and how many patients each.
FAMILIES: tuple[tuple[str, int], ...] = (
    ("steady", 8),
    ("isolated", 4),
    ("repeated", 4),
    ("larger", 3),
    ("quality", 3),
    ("short", 3),
    ("context", 3),
    ("unavailable", 2),
)
# How many members of each family go to the secondary doctor (6 of 30); every family stays
# represented in the presenter's 24.
SECONDARY_PER_FAMILY = {"steady": 2, "isolated": 1, "repeated": 1, "context": 1, "short": 1}

# Plausible fictional names (no real patients); names never encode a scenario.
PATIENT_NAMES = (
    "Maya Chen",
    "Daniel Okoro",
    "Lucia Ferreira",
    "Arthur Bennett",
    "Priya Nair",
    "Samuel Whitaker",
    "Grace Holloway",
    "Tomas Varga",
    "Helen Castillo",
    "Oliver Grant",
    "Nadia Rahman",
    "George Ellison",
    "Marta Kowalski",
    "Ibrahim Haddad",
    "Clara Jensen",
    "Frank Moreno",
    "Aiko Tanaka",
    "Edward Lindqvist",
    "Beatrice Adeyemi",
    "Harold Singh",
    "Irene Dubois",
    "Victor Alvarez",
    "Margaret Doyle",
    "Kenji Watanabe",
    "Esther Goldberg",
    "Raymond Asante",
    "Lillian Fitzgerald",
    "Joan Sorensen",
    "Patrick Nwosu",
    "Dolores Ruiz",
)
SECONDARY_DOCTOR = ("dr.lena.hart", "Dr. Lena Hart")
TIMEZONES = ("America/New_York",) * 5 + ("America/Chicago", "America/Denver", "America/Los_Angeles")
NOTES = {
    "ACKNOWLEDGED": None,
    "NOTE_ADDED": "Reviewed the recorded task changes and context; follow-up discussion planned.",
    "RESOLVED": "Reviewed the recorded task results and context alongside earlier weeks; no further review "
    "needed for this check-in.",
}


def showcase_root() -> Path:
    return synthetic_root() / "showcase"


def credentials_path(dataset_id: str) -> Path:
    """Private, git-ignored credential store (mode 600), kept apart from the hashed dataset files."""
    return get_settings().SYNTHETIC_DATA_DIR.parent / "showcase-private" / f"{dataset_id}.credentials.json"


def _uuid(dataset_id: str, *parts: object) -> uuid.UUID:
    return uuid.UUID(make_id(f"showcase/{dataset_id}", *parts))


def _email(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@{SHOWCASE_DOMAIN}"


def _require_demo_environment(hosted_demo: bool = False) -> None:
    from app.core.provisioning import ProvisioningRefused, check_provisioning

    try:
        check_provisioning(hosted_demo)
    except ProvisioningRefused as exc:
        raise DatasetError(str(exc)) from None


# --- roster ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    index: int
    demo_key: str
    display_name: str
    family: str
    doctor: str  # "presenter" | "secondary"
    live_ready: bool


def build_roster(seed: int, count: int = 30) -> list[RosterEntry]:
    """Deterministic family/name/doctor assignment. `count < 30` keeps a proportional subset (tests)."""
    rng = random.Random(seed)  # noqa: S311 — seeded, reproducible generation (not security)
    families = [f for f, n in FAMILIES for _ in range(n)]
    if count < len(families):
        # Round-robin across families so a small roster still covers several families.
        buckets = {f: [f] * n for f, n in FAMILIES}
        families = []
        while len(families) < count:
            for f, _ in FAMILIES:
                if buckets[f] and len(families) < count:
                    families.append(buckets[f].pop())
    names = list(PATIENT_NAMES)
    rng.shuffle(names)
    secondary_left = {f: n for f, n in SECONDARY_PER_FAMILY.items()} if count >= 30 else {}
    if count < 30:
        secondary_left = {families[-1]: 1} if count >= 3 else {}
    seen: dict[str, int] = {}
    roster: list[RosterEntry] = []
    live_given = False
    for i, fam in enumerate(families):
        seen[fam] = seen.get(fam, 0) + 1
        members = sum(1 for f in families if f == fam)
        # The last members of a family go to the secondary doctor.
        doctor = "secondary" if secondary_left.get(fam, 0) > members - seen[fam] else "presenter"
        live = not live_given and fam == "steady" and doctor == "presenter"
        live_given = live_given or live
        roster.append(RosterEntry(i, f"sc-{i + 1:02d}", names[i], fam, doctor, live))
    return roster


# --- prepare (files only) ----------------------------------------------------------------------


def _patient_plan(entry: RosterEntry, seed: int, identity: str, as_of: datetime, presentation_at: datetime):
    rng = random.Random(f"{seed}/{entry.demo_key}")  # noqa: S311 — seeded, reproducible generation (not security)
    fam = entry.family
    slots = {
        "steady": (14, 24),
        "isolated": (12, 20),
        "repeated": (14, 22),
        "larger": (12, 18),
        "quality": (12, 18),
        "short": (2, 5),
        "context": (12, 20),
        "unavailable": (10, 16),
    }[fam]
    n = 12 if entry.live_ready else rng.randint(*slots)
    config = replace(
        profile("smoke", seed),
        profile="showcase",
        slots_per_patient=n,
        technical_issue_probability=0.0,
        missing_slot_probability=0.0,
        input_mode_switch_probability=0.0,
        extra_attempt_probability=0.0,
        missing_context_probability_per_field=0.12,
        medication_change_probability=0.08,
    )
    plan = plan_patient(config, identity, POPULATION, entry.index)
    plan.params.update(
        {
            "recall_p0": rng.uniform(0.55, 0.9),
            "hit_p0": rng.uniform(0.72, 0.97),
            "false_alarm_p0": rng.uniform(0.03, 0.18),
            "rt_median0_ms": rng.uniform(430, 880),
            "recall_hit_trend": rng.uniform(-0.004, 0.001),
            "false_alarm_trend": rng.uniform(-0.0005, 0.002),
            "log_rt_trend": rng.uniform(-0.001, 0.004),
            "innovation_multiplier": rng.uniform(0.6, 1.2),
        }
    )
    plan.trajectory = "stable" if entry.live_ready or rng.random() < 0.6 else "linear"
    plan.scenario = fam
    plan.event = None
    plan.overrides = Overrides()
    if entry.live_ready:
        # Next canonical target = the planned presentation time (inside the ±12 h window).
        plan.anchor = presentation_at - timedelta(days=7 * n)
        plan.overrides = Overrides(force_clean=True)
    else:
        last_target = as_of - timedelta(days=rng.uniform(0.6, 6.4))
        plan.anchor = (last_target - timedelta(days=7 * (n - 1))).replace(second=0, microsecond=0)

    def ev(kind: str, start: int, duration: int, domains: tuple[str, ...], **deltas: float) -> Event:
        return Event(kind, max(7, start), duration, domains, **deltas)

    if fam == "isolated":
        domains = tuple(sorted(rng.sample(DOMAINS, rng.choice((2, 3))), key=DOMAINS.index))
        plan.event = ev(
            "isolated_worsening",
            n - 1 - rng.randint(0, 5),
            1,
            domains,
            recall_hit_delta=-rng.uniform(0.18, 0.3),
            false_alarm_delta=rng.uniform(0.06, 0.15),
            log_rt_delta=rng.uniform(0.22, 0.32),
        )
    elif fam == "repeated":
        d = rng.choice((3, 4))
        plan.event = ev(
            "persistent_worsening",
            n - d - rng.randint(0, 2),
            d,
            DOMAINS,
            recall_hit_delta=-rng.uniform(0.12, 0.2),
            false_alarm_delta=rng.uniform(0.05, 0.1),
            log_rt_delta=rng.uniform(0.2, 0.28),
        )
    elif fam == "larger":
        plan.event = ev(
            "isolated_worsening",
            n - 1 - (0 if entry.index % 2 == 0 else rng.randint(1, 3)),
            1,
            DOMAINS,
            recall_hit_delta=-rng.uniform(0.35, 0.45),
            false_alarm_delta=rng.uniform(0.2, 0.3),
            log_rt_delta=rng.uniform(0.4, 0.55),
        )
    elif fam == "context":
        plan.event = ev(
            "context_only_change",
            n - 1 - rng.randint(2, 6),
            3,
            ("memory",),
            recall_hit_delta=-0.05,
            sleep_delta=-rng.uniform(2.0, 3.0),
            mood_delta=-rng.uniform(2.0, 3.0),
        )
    elif fam == "quality":
        variant = rng.randint(0, 2)
        mid, late = n // 2, n - 3
        if variant == 0:
            plan.overrides = Overrides(
                faults={mid: "HIDDEN_TAB_ATTENTION"}, retake_slots={mid}, extra_slots={late}
            )
        elif variant == 1:
            plan.overrides = Overrides(
                faults={mid: "MEMORY_INTERRUPTION", late: "ATTENTION_SKIPPED"}, missing_slots={mid - 3}
            )
        else:
            plan.overrides = Overrides(
                faults={mid - 1: "REACTION_STOPPED"},
                missing_slots={late - 1},
                rt_slowdown_slots={mid + 1: 0.18},
                extra_slots={n - 1},
            )
    return config, plan, n


def prepare_showcase(
    dataset_id: str,
    seed: int,
    as_of: datetime,
    presentation_at: datetime,
    presenter_doctor_id: uuid.UUID,
    patient_count: int = 30,
    root: Path | None = None,
) -> tuple[Path, str]:
    """Write the fixed manifest + raw payloads. Reuses a COMPLETE dataset; never mutates the DB."""
    if as_of.tzinfo is None or presentation_at.tzinfo is None:
        raise DatasetError("--as-of and --presentation-at must be timezone-aware (e.g. ...Z)")
    base = root or showcase_root()
    final = dataset_dir(dataset_id, base)
    if final.exists():
        manifest = exports.read_json(final / "manifest.json")
        if manifest.get("status") != "COMPLETE":
            raise DatasetError(f"{final} exists but is incomplete; remove it deliberately")
        fixed = (
            manifest["seed"],
            manifest["as_of"],
            manifest["presentation_at"],
            manifest["presenter_doctor_id"],
        )
        if fixed != (seed, as_of.isoformat(), presentation_at.isoformat(), str(presenter_doctor_id)):
            raise DatasetError(
                "dataset exists with different fixed inputs; a new population needs a new --dataset-id"
            )
        return final, "reused"
    if presentation_at <= as_of:
        raise DatasetError("--presentation-at must be after --as-of")

    identity = hashlib.sha256(f"showcase/{dataset_id}".encode()).hexdigest()[:16]
    roster = build_roster(seed, patient_count)
    tz_rng = random.Random(f"{seed}/timezones")  # noqa: S311 — seeded, reproducible generation (not security)
    sessions: list[dict[str, Any]] = []
    patients: list[dict[str, Any]] = []
    for entry in roster:
        config, plan, n = _patient_plan(entry, seed, identity, as_of, presentation_at)
        out = generate_population(config, identity, POPULATION, [plan])
        source = "SYNTHETIC_HISTORY" if entry.family == "unavailable" else "SCENARIO_REPLAY"
        for r in out.raw_sessions:
            if datetime.fromisoformat(r["available_at"]) >= as_of:
                raise DatasetError(f"{entry.demo_key}: generated a session after as_of")
            sessions.append({**r, "source": source, "demo_key": entry.demo_key})
        next_target = plan.anchor + timedelta(days=7 * n)
        patients.append(
            {
                "demo_key": entry.demo_key,
                "display_name": entry.display_name,
                "email": _email(entry.display_name),
                "timezone": "America/New_York" if entry.live_ready else tz_rng.choice(TIMEZONES),
                "family": entry.family,
                "doctor": entry.doctor,
                "live_ready": entry.live_ready,
                "source": source,
                "history_slots": n,
                "event": None
                if plan.event is None
                else {
                    "kind": plan.event.kind,
                    "start_slot": plan.event.start_slot,
                    "duration": plan.event.duration,
                    "domains": list(plan.event.domains),
                },
                "anchor_at": plan.anchor.isoformat(),
                "next_target_at": next_target.isoformat(),
                "input_mode": "keyboard",
                "user_id": str(_uuid(dataset_id, "user", entry.demo_key)),
                "patient_id": plan.patient_id,
                "session_count": sum(1 for r in out.raw_sessions),
            }
        )

    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f".{dataset_id}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        exports.write_jsonl(
            tmp / "sessions.jsonl",
            sorted(sessions, key=lambda s: (s["demo_key"], s["started_at"], s["attempt"])),
        )
        files = exports.file_hashes(tmp, ["sessions.jsonl"])
        window = timedelta(hours=12)
        exports.write_json(
            tmp / "manifest.json",
            {
                "manifest_version": MANIFEST_VERSION,
                "dataset_id": dataset_id,
                "status": "COMPLETE",
                "fictional": True,
                "seed": seed,
                "as_of": as_of.isoformat(),
                "presentation_at": presentation_at.isoformat(),
                "presentation_window": {
                    "opens_at": (presentation_at - window).isoformat(),
                    "closes_at": (presentation_at + window).isoformat(),
                },
                "presenter_doctor_id": str(presenter_doctor_id),
                "secondary_doctor": {
                    "email": f"{SECONDARY_DOCTOR[0]}@{SHOWCASE_DOMAIN}",
                    "display_name": SECONDARY_DOCTOR[1],
                    "user_id": str(_uuid(dataset_id, "user", "secondary-doctor")),
                },
                "versions": {
                    "protocol": PROTOCOL_VERSION,
                    "scoring": SCORING_VERSION,
                    "cognitive_index": "cognitive_index_v1",
                    "population": POPULATION,
                },
                "identity": identity,
                "generated_at": exports.now_iso(),
                "patients": patients,
                "files": files,
                "note": "Fictional presentation data. Scenario families are internal; "
                "passwords are never stored here.",
            },
        )
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final, "created"


# --- import (controlled DB writes) -------------------------------------------------------------


def _load(dataset_id: str, root: Path | None) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    path = dataset_dir(dataset_id, root or showcase_root())
    if not (path / "manifest.json").exists():
        raise DatasetError(f"no prepared showcase {dataset_id!r}; run prepare_showcase first")
    manifest = exports.read_json(path / "manifest.json")
    if manifest.get("status") != "COMPLETE":
        raise DatasetError("showcase files are not COMPLETE; run prepare_showcase")
    for name, digest in manifest["files"].items():
        if exports.sha256_file(path / name) != digest:
            raise DatasetError(f"checksum mismatch in {name}")
    return path, manifest, list(exports.read_jsonl(path / "sessions.jsonl"))


class _Credentials:
    """Private credential file: entries are written before the account is committed, never printed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}

    def password_for(self, email: str) -> str:
        if email not in self.data:
            self.data[email] = secrets.token_urlsafe(18)
            self._save()
        return self.data[email]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)


def _ensure_user(
    db: Session, creds: _Credentials, user_id: uuid.UUID, email: str, name: str, role: UserRole
) -> tuple[User, bool]:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        if user.role != role:
            raise DatasetError(f"{email} exists with role {user.role}; refusing to change it")
        return user, False  # never reset a password or rename an existing account
    user = User(
        id=user_id,
        email=email,
        display_name=name,
        role=role,
        password_hash=hash_password(creds.password_for(email)),
    )
    db.add(user)
    db.flush()
    return user, True


def _ensure_assignment(db: Session, doctor_id: uuid.UUID, patient_id: uuid.UUID) -> str:
    row = db.scalar(
        select(DoctorPatientAssignment).where(
            DoctorPatientAssignment.doctor_user_id == doctor_id,
            DoctorPatientAssignment.patient_id == patient_id,
        )
    )
    if row is None:
        db.add(DoctorPatientAssignment(doctor_user_id=doctor_id, patient_id=patient_id))
        return "created"
    return "ended (left as is)" if row.ended_at is not None else "present"


def provision_identities(db: Session, dataset_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    presenter = db.get(User, uuid.UUID(manifest["presenter_doctor_id"]))
    if presenter is None or presenter.role != UserRole.DOCTOR or not presenter.is_active:
        raise DatasetError(
            "the manifest's presenter doctor does not exist (or is not an active doctor) in this database"
        )
    creds = _Credentials(credentials_path(dataset_id))
    sec = manifest["secondary_doctor"]
    secondary, sec_created = _ensure_user(
        db, creds, uuid.UUID(sec["user_id"]), sec["email"], sec["display_name"], UserRole.DOCTOR
    )
    summary = {"users_created": int(sec_created), "users_present": int(not sec_created), "assignments": {}}
    doctors = {"presenter": presenter.id, "secondary": secondary.id}
    for p in manifest["patients"]:
        user, created = _ensure_user(
            db, creds, uuid.UUID(p["user_id"]), p["email"], p["display_name"], UserRole.PATIENT
        )
        summary["users_created" if created else "users_present"] += 1
        profile_row = user.patient_profile
        if profile_row is None:
            profile_row = PatientProfile(
                id=uuid.UUID(p["patient_id"]),
                user=user,
                timezone=p["timezone"],
                provenance=DataProvenance.SYNTHETIC_SEED,
                demo_scenario=p["demo_key"],
            )
            db.add(profile_row)
            db.flush()
        elif str(profile_row.id) != p["patient_id"]:
            raise DatasetError(
                f"{p['email']} already has a different patient profile; refusing to mix records"
            )
        outcome = _ensure_assignment(db, doctors[p["doctor"]], profile_row.id)
        summary["assignments"][outcome] = summary["assignments"].get(outcome, 0) + 1
    db.commit()
    return summary


def _import_history(db: Session, dataset_id: str, entry: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """One transaction per patient: chronological replay through the live services."""
    pid = uuid.UUID(entry["patient_id"])
    lock_patient(db, pid)
    wanted = {uuid.UUID(r["session_id"]) for r in rows}
    existing = set(db.scalars(select(AssessmentSession.id).where(AssessmentSession.patient_id == pid)))
    missing = wanted - existing
    if missing and existing - wanted:
        db.rollback()
        return f"{entry['demo_key']}: SKIPPED — has sessions outside this dataset; not mixing histories"
    source = AssessmentSource(entry["source"])
    anchor = datetime.fromisoformat(entry["anchor_at"])
    created = unchanged = 0
    try:
        for r in sorted(rows, key=lambda s: (s["started_at"], s["attempt"])):
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
            started = datetime.fromisoformat(r["started_at"])
            req = StartSessionRequest(
                start_key=_uuid(dataset_id, "start", r["session_id"]),
                input_mode=r["input_mode"],
                device_changed=bool(r["device_changed"]),
                navigation_assistance=False,
                allow_unscheduled=purpose == SchedulePurpose.EXTRA_ATTEMPT,
            )
            reps = representatives(db, pid)  # chronological import: only earlier representatives exist
            session = build_frozen_session(
                patient_id=pid,
                req=req,
                started_at=started,
                anchor=anchor,
                slot=r["slot_index"],
                target=datetime.fromisoformat(r["target_at"]),
                purpose=purpose,
                schedule_reason=SCHEDULE_REASON[purpose.value],
                starts=scheduled_starts(db, pid, r["slot_index"]),
                reps=reps,
                task_protocol=r["protocol_snapshot"],
                source=source,
                session_id=session_id,
            )
            db.add(session)
            db.flush()
            if source == AssessmentSource.SCENARIO_REPLAY:
                # Frozen at the simulated session start, before the answers below exist.
                issue_forecast(db, session, reps, started)
            elif history_ready(session):
                session.forecast_reasons = ["MODEL_UNAVAILABLE", "HISTORICAL_IMPORT"]
            scoring = score_submission(r["protocol_snapshot"], payload, r["input_mode"])
            received = datetime.fromisoformat(r["available_at"])
            assessment = record_submission(db, session, payload, digest, scoring, received_at=received)
            process_assessment(db, assessment.id, received)
            created += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return f"{entry['demo_key']}: {created} session(s) replayed, {unchanged} already present"


def _review_plan(manifest: dict[str, Any], db: Session) -> list[tuple[dict[str, Any], Alert, list[str]]]:
    """Deterministic workflow targets over the alerts the analysis actually created."""
    plan: list[tuple[dict[str, Any], Alert, list[str]]] = []
    with_alerts = 0
    for p in manifest["patients"]:
        alerts = db.scalars(
            select(Alert)
            .join(Assessment, Assessment.id == Alert.assessment_id)
            .where(Alert.patient_id == uuid.UUID(p["patient_id"]))
            .order_by(Assessment.observed_at, Alert.id)
        ).all()
        if not alerts:
            continue
        with_alerts += 1
        for i, alert in enumerate(alerts):
            latest = i == len(alerts) - 1
            if latest:
                # Most patients keep their newest alert OPEN for the presenter; some are acknowledged.
                steps = ["ACKNOWLEDGED", "NOTE_ADDED"] if with_alerts % 4 == 0 else []
            else:
                steps = (
                    ["ACKNOWLEDGED", "NOTE_ADDED"]
                    if (i + with_alerts) % 3 == 0
                    else ["ACKNOWLEDGED", "RESOLVED"]
                )
            plan.append((p, alert, steps))
    return plan


def apply_reviews(db: Session, dataset_id: str, manifest: dict[str, Any], now: datetime) -> dict[str, int]:
    """Real review events at the actual current time; reruns replay (same key) or skip (changed)."""
    doctors = {
        "presenter": db.get(User, uuid.UUID(manifest["presenter_doctor_id"])),
        "secondary": db.scalar(select(User).where(User.email == manifest["secondary_doctor"]["email"])),
    }
    counts = {"recorded": 0, "replayed": 0, "skipped_changed": 0, "left_open": 0}
    for p, alert, steps in _review_plan(manifest, db):
        if not steps:
            counts["left_open"] += 1
            continue
        doctor = doctors[p["doctor"]]
        for n, action in enumerate(steps):
            req = AlertEventRequest(
                request_key=_uuid(dataset_id, "review", alert.id, n),
                expected_lock_version=1 + n,
                action=action,
                note=NOTES[action],
            )
            try:
                response, _ = reviews.record_event(db, doctor, alert.id, req, now)
                db.commit()
            except ApiError:
                # Someone (e.g. the presenter during a rehearsal) changed this alert: leave it alone.
                db.rollback()
                counts["skipped_changed"] += 1
                break
            counts["replayed" if response.replayed else "recorded"] += 1
    return counts


def import_showcase(
    db: Session, dataset_id: str, root: Path | None = None, now: datetime | None = None, hosted_demo: bool = False
) -> dict[str, Any]:
    _require_demo_environment(hosted_demo)
    path, manifest, sessions = _load(dataset_id, root)
    state_path = path / "import_state.json"
    state = exports.read_json(state_path) if state_path.exists() else {"stages": {}}
    identity = provision_identities(db, dataset_id, manifest)
    state["stages"]["identity"] = {"completed_at": exports.now_iso(), **identity}
    exports.write_json(state_path, state)

    from app.ml.serving import ForecastUnavailable, resolve_active_pair

    try:
        model, policy = resolve_active_pair(db)
        binding: dict[str, Any] = {
            "model_version": model.version,
            "model_kind": model.kind,
            "policy_version": policy.version,
        }
    except ForecastUnavailable as exc:
        binding = {"unavailable": exc.code}
    state.setdefault("first_model_binding", binding)
    state["latest_model_binding"] = binding

    outcomes, failures = [], []
    for p in manifest["patients"]:
        rows = [s for s in sessions if s["demo_key"] == p["demo_key"]]
        try:
            outcomes.append(_import_history(db, dataset_id, p, rows))
        except DatasetError as exc:
            failures.append(f"{p['demo_key']}: FAILED — {exc}")
    state["stages"]["history"] = {
        "completed_at": exports.now_iso(),
        "outcomes": outcomes,
        "failures": failures,
    }
    exports.write_json(state_path, state)

    review_counts = apply_reviews(db, dataset_id, manifest, now or datetime.now(UTC))
    state["stages"]["reviews"] = {"completed_at": exports.now_iso(), **review_counts}
    exports.write_json(state_path, state)
    return {
        "identity": identity,
        "model_binding": binding,
        "history": outcomes,
        "failures": failures,
        "reviews": review_counts,
        "credentials_file": str(credentials_path(dataset_id)),
    }


# --- verify (read-only) ------------------------------------------------------------------------


def _counts(db: Session, stmt) -> dict[str, int]:
    return {str(k): int(v) for k, v in db.execute(stmt).all()}


def verify_showcase(
    db: Session, dataset_id: str, root: Path | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Read back what was actually stored; nothing here writes."""
    from app.services.access import active_assignment

    now = now or datetime.now(UTC)
    _, manifest, sessions = _load(dataset_id, root)
    pids = [uuid.UUID(p["patient_id"]) for p in manifest["patients"]]
    presenter = db.get(User, uuid.UUID(manifest["presenter_doctor_id"]))
    secondary = db.scalar(select(User).where(User.email == manifest["secondary_doctor"]["email"]))
    report: dict[str, Any] = {"dataset_id": dataset_id, "checked_at": now.isoformat(), "problems": []}
    problems = report["problems"]

    present = set(db.scalars(select(PatientProfile.id).where(PatientProfile.id.in_(pids))))
    report["patients"] = {"expected": len(pids), "present": len(present)}
    assigned = {}
    for role, doctor in (("presenter", presenter), ("secondary", secondary)):
        ids = {uuid.UUID(p["patient_id"]) for p in manifest["patients"] if p["doctor"] == role}
        ok = sum(1 for pid in ids if doctor is not None and active_assignment(db, doctor, pid) is not None)
        assigned[role] = {"expected": len(ids), "active": ok}
        if ok != len(ids):
            problems.append(f"{role}: {ok}/{len(ids)} assignments active")
    report["assignments"] = assigned
    if presenter is not None:
        report["presenter_total_assigned"] = db.scalar(
            select(func.count())
            .select_from(DoctorPatientAssignment)
            .where(
                DoctorPatientAssignment.doctor_user_id == presenter.id,
                DoctorPatientAssignment.ended_at.is_(None),
            )
        )
        # Authorization boundary: the presenter must not reach any secondary-only patient.
        leaks = [
            p["demo_key"]
            for p in manifest["patients"]
            if p["doctor"] == "secondary"
            and active_assignment(db, presenter, uuid.UUID(p["patient_id"])) is not None
        ]
        report["presenter_sees_secondary"] = leaks
        if leaks:
            problems.append(f"presenter can access secondary patients {leaks}")

    in_set = Assessment.patient_id.in_(pids)
    report["assessments"] = {
        "total": db.scalar(select(func.count()).select_from(Assessment).where(in_set)),
        "by_source": _counts(
            db, select(Assessment.source, func.count()).where(in_set).group_by(Assessment.source)
        ),
        "by_quality": _counts(
            db, select(Assessment.quality, func.count()).where(in_set).group_by(Assessment.quality)
        ),
        "observed_from": (
            db.scalar(select(func.min(Assessment.observed_at)).where(in_set)) or now
        ).isoformat(),
        "observed_to": (db.scalar(select(func.max(Assessment.observed_at)).where(in_set)) or now).isoformat(),
        "last_30_days": db.scalar(
            select(func.count())
            .select_from(Assessment)
            .where(in_set, Assessment.observed_at >= now - timedelta(days=30))
        ),
        "last_90_days": db.scalar(
            select(func.count())
            .select_from(Assessment)
            .where(in_set, Assessment.observed_at >= now - timedelta(days=90))
        ),
    }
    a_set = Analysis.patient_id.in_(pids)
    report["analyses"] = {
        "by_availability": _counts(
            db, select(Analysis.availability, func.count()).where(a_set).group_by(Analysis.availability)
        ),
        "by_level": _counts(
            db,
            select(Analysis.deviation_level, func.count())
            .where(a_set, Analysis.deviation_level.is_not(None))
            .group_by(Analysis.deviation_level),
        ),
    }
    al_set = Alert.patient_id.in_(pids)
    report["alerts"] = {
        "by_level": _counts(
            db, select(Alert.deviation_level, func.count()).where(al_set).group_by(Alert.deviation_level)
        ),
        "by_workflow": _counts(db, select(Alert.status, func.count()).where(al_set).group_by(Alert.status)),
    }
    report["forecasts"] = db.scalar(
        select(func.count()).select_from(Forecast).where(Forecast.patient_id.in_(pids))
    )

    # Score integrity: re-score a deterministic sample of stored raw payloads.
    sample = [s for i, s in enumerate(sorted(sessions, key=lambda s: s["session_id"])) if i % 7 == 0]
    mismatches = 0
    for s in sample:
        a = db.scalar(select(Assessment).where(Assessment.session_id == uuid.UUID(s["session_id"])))
        if a is None:
            continue
        res = score_submission(
            s["protocol_snapshot"], AssessmentSubmission.model_validate(s["raw_submission"]), s["input_mode"]
        )
        got = (a.memory_score, a.attention_score, a.reaction_time_ms, a.quality)
        want = (res.memory.score, res.attention.score, res.reaction.score, res.quality.value)
        if tuple(None if v is None else float(v) for v in got[:3]) + (got[3],) != tuple(
            None if v is None else float(v) for v in want[:3]
        ) + (want[3],):
            mismatches += 1
    report["rescored"] = {"sampled": len(sample), "mismatches": mismatches}
    if mismatches:
        problems.append(f"{mismatches} re-scored payload(s) differ from stored scores")

    # Chronology: every forecast used only representatives available at its cutoff (= session start)
    # and was issued before the target assessment became available.
    bad_chrono = 0
    for f in db.scalars(select(Forecast).where(Forecast.patient_id.in_(pids))):
        sess = db.get(AssessmentSession, f.session_id)
        inputs = db.scalars(
            select(Assessment).where(Assessment.id.in_([uuid.UUID(i) for i in f.input_assessment_ids]))
        ).all()
        target = db.scalar(select(Assessment).where(Assessment.session_id == f.session_id))
        if (
            len(inputs) != 6
            or any(i.available_at > f.history_cutoff_at for i in inputs)
            or f.history_cutoff_at != sess.started_at
            or (target is not None and f.issued_at > target.available_at)
        ):
            bad_chrono += 1
    report["chronology_violations"] = bad_chrono
    if bad_chrono:
        problems.append(f"{bad_chrono} forecast(s) violate the pre-cutoff rule")

    # Live-ready patient(s): unsubmitted next slot, no active session, window covers presentation.
    live = []
    for p in manifest["patients"]:
        if not p["live_ready"]:
            continue
        pid = uuid.UUID(p["patient_id"])
        next_slot = p["history_slots"]
        later = db.scalars(
            select(AssessmentSession).where(
                AssessmentSession.patient_id == pid, AssessmentSession.slot_index >= next_slot
            )
        ).all()
        reps = representatives(db, pid)
        live.append(
            {
                "demo_key": p["demo_key"],
                "display_name": p["display_name"],
                "patient_id": p["patient_id"],
                "email": p["email"],
                "next_target_at": p["next_target_at"],
                "window": manifest["presentation_window"],
                "prior_representatives": len([k for k in reps if k < next_slot]),
                "six_consecutive_before_target": all(k in reps for k in range(next_slot - 6, next_slot)),
                "next_slot_sessions": [{"status": s.status, "source": s.source} for s in later],
                "consumed": any(s.status != "ABANDONED" for s in later),
            }
        )
    report["live_ready"] = live

    report["model_binding"] = _binding_summary(db, pids)
    report["featured"] = featured_examples(db, manifest)
    return report


def _binding_summary(db: Session, pids: list[uuid.UUID]) -> dict[str, int]:
    from app.models import AnomalyPolicy, ModelVersion

    rows = db.execute(
        select(ModelVersion.version, AnomalyPolicy.version, func.count())
        .select_from(Forecast)
        .join(ModelVersion, ModelVersion.id == Forecast.model_version_id)
        .join(AnomalyPolicy, AnomalyPolicy.id == Forecast.policy_id)
        .where(Forecast.patient_id.in_(pids))
        .group_by(ModelVersion.version, AnomalyPolicy.version)
    ).all()
    return {f"{m} + {p}": int(n) for m, p, n in rows}


# --- featured examples (refinement 04 §6–§7), read-only ----------------------------------------


def _index(a: Assessment) -> float | None:
    from app.services.cognitive_index import observed_index

    return observed_index(
        quality=a.quality,
        memory_score=a.memory_score,
        attention_score=a.attention_score,
        reaction_time_ms=a.reaction_time_ms,
        protocol_version=a.protocol_version,
        scoring_version=a.scoring_version,
    ).value


def _scores(a: Assessment) -> dict[str, Any]:
    return {
        "assessment_id": str(a.id),
        "observed_at": a.observed_at.isoformat(),
        "slot_index": a.slot_index,
        "source": a.source,
        "quality": a.quality,
        "longitudinal_eligible": a.longitudinal_eligible,
        "memory_score": None if a.memory_score is None else float(a.memory_score),
        "attention_score": None if a.attention_score is None else float(a.attention_score),
        "reaction_time_ms": None if a.reaction_time_ms is None else float(a.reaction_time_ms),
        "cognitive_index_v1": None if (v := _index(a)) is None else round(v, 3),
    }


def _analysis_evidence(db: Session, a: Assessment) -> dict[str, Any]:
    from app.models import AnomalyPolicy, ModelVersion
    from app.services.cognitive_index import forecast_index

    analysis = db.scalar(select(Analysis).where(Analysis.assessment_id == a.id))
    forecast = db.get(Forecast, analysis.forecast_id) if analysis and analysis.forecast_id else None
    alert = db.scalar(select(Alert).where(Alert.analysis_id == analysis.id)) if analysis else None
    out: dict[str, Any] = {
        "availability": analysis.availability if analysis else None,
        "deviation_level": analysis.deviation_level if analysis else None,
        "persistent_count": analysis.persistent_count if analysis else None,
        "domain_deviations": analysis.domain_deviations if analysis else None,
        "alert": None
        if alert is None
        else {"alert_id": str(alert.id), "workflow_status": alert.status, "lock_version": alert.lock_version},
    }
    if forecast is not None:
        parts = forecast.comparability_key.split("|")
        composite = forecast_index(
            predicted_memory_score=forecast.predicted_memory_score,
            predicted_attention_score=forecast.predicted_attention_score,
            predicted_reaction_time_ms=forecast.predicted_reaction_time_ms,
            protocol_version=parts[0],
            scoring_version=parts[1],
        ).value
        out["forecast"] = {
            "forecast_id": str(forecast.id),
            "issued_at": forecast.issued_at.isoformat(),
            "history_cutoff_at": forecast.history_cutoff_at.isoformat(),
            "input_assessment_ids": forecast.input_assessment_ids,
            "predicted": {
                "memory_score": float(forecast.predicted_memory_score),
                "attention_score": float(forecast.predicted_attention_score),
                "reaction_time_ms": float(forecast.predicted_reaction_time_ms),
                "cognitive_index_v1": None if composite is None else round(composite, 3),
            },
            "model_version": db.get(ModelVersion, forecast.model_version_id).version,
            "policy_version": db.get(AnomalyPolicy, forecast.policy_id).version,
        }
    return out


def featured_examples(db: Session, manifest: dict[str, Any]) -> dict[str, Any]:
    """Pick the presentation accounts from *actual* stored outcomes (never from intended scenarios)."""
    from app.services.access import active_assignment

    presenter = db.get(User, uuid.UUID(manifest["presenter_doctor_id"]))
    featured: dict[str, Any] = {}
    abrupt, repeated, steady = [], [], []
    for p in manifest["patients"]:
        if p["doctor"] != "presenter":
            continue
        pid = uuid.UUID(p["patient_id"])
        reps = representatives(db, pid)
        analyses = db.scalars(select(Analysis).where(Analysis.patient_id == pid)).all()
        alerts = db.scalar(select(func.count()).select_from(Alert).where(Alert.patient_id == pid))
        if reps:
            k = max(reps)
            cur, prev = reps[k], reps.get(k - 1)
            ev = _analysis_evidence(db, cur)
            comparable = (
                prev is not None
                and prev.source == cur.source
                and prev.quality_details["comparability"]["key"]
                == cur.quality_details["comparability"]["key"]
            )
            if (
                ev["deviation_level"] not in (None, "NORMAL")
                and ev["alert"]
                and comparable
                and ev["alert"]["workflow_status"] != "RESOLVED"
            ):
                drop = (_index(prev) or 0) - (_index(cur) or 0)
                abrupt.append((drop, p, prev, cur, ev))
        streak = max(
            (a.persistent_count or 0 for a in analyses if a.deviation_level not in (None, "NORMAL")),
            default=0,
        )
        if streak >= 2:
            repeated.append((streak, p))
        normal = sum(1 for a in analyses if a.deviation_level == "NORMAL")
        if alerts == 0 and normal:
            steady.append((normal, p))

    def patient_ref(p: dict[str, Any]) -> dict[str, Any]:
        pid = uuid.UUID(p["patient_id"])
        return {
            "display_name": p["display_name"],
            "demo_key": p["demo_key"],
            "patient_id": p["patient_id"],
            "presenter_authorized": presenter is not None
            and active_assignment(db, presenter, pid) is not None,
            "link": f"/doctor/patients/{p['patient_id']}",
        }

    if abrupt:
        drop, p, prev, cur, ev = max(abrupt, key=lambda t: t[0])
        elapsed = cur.observed_at - prev.observed_at
        featured["abrupt_change"] = {
            **patient_ref(p),
            "previous": _scores(prev),
            "current": _scores(cur),
            "cognitive_index_change_points": round(-drop, 3),
            "elapsed_days": round(elapsed.total_seconds() / 86400, 2),
            "analysis": ev,
        }
    if repeated:
        streak, p = max(repeated, key=lambda t: t[0])
        pid = uuid.UUID(p["patient_id"])
        chain = []
        for a in db.scalars(
            select(Assessment)
            .where(Assessment.patient_id == pid, Assessment.longitudinal_eligible.is_(True))
            .order_by(Assessment.slot_index)
        ):
            ev = _analysis_evidence(db, a)
            if ev["deviation_level"] not in (None, "NORMAL"):
                chain.append(
                    {
                        "slot_index": a.slot_index,
                        "observed_at": a.observed_at.isoformat(),
                        "deviation_level": ev["deviation_level"],
                        "persistent_count": ev["persistent_count"],
                        "alert": ev["alert"],
                    }
                )
        featured["repeated_change"] = {
            **patient_ref(p),
            "max_persistent_count": streak,
            "flagged_checkins": chain,
        }
    if steady:
        normal, p = max(steady, key=lambda t: t[0])
        featured["steady_control"] = {**patient_ref(p), "normal_complete_analyses": normal, "alerts": 0}
    live = next((p for p in manifest["patients"] if p["live_ready"]), None)
    if live is not None:
        featured["live_assessment"] = {
            **patient_ref(live),
            "email": live["email"],
            "next_target_at": live["next_target_at"],
            "input_mode": live["input_mode"],
            "window": manifest["presentation_window"],
        }
    return featured
