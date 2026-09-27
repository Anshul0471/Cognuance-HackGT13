"""Synthetic population generator `synthetic_generator_v1` (guide 03 §5–§7).

Reproducibility convention (§5): every random draw comes from
`np.random.Generator(PCG64(SeedSequence(root_seed, spawn_key=(population, patient_index, component))))`
so adding a patient, fixture, or component never shifts another patient's streams. IDs are UUIDv5 of
`ID_NAMESPACE` + "<dataset identity>/<kind>/<patient>/<slot>/<attempt>"; Python's `hash()` is never used.

Latent parameters and injected events are evaluation truth only (`truth.jsonl`); observations carry
only what the live app would store.
"""

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from app.ml.data.config import GeneratorConfig
from app.ml.data.raw_tasks import FAULT_KINDS, Latent, TaskOptions, build_raw_submission
from app.models import Quality
from app.schemas.assessments import AssessmentSubmission
from app.services import schedule
from app.services.protocol import PROTOCOL_VERSION, SCORING_VERSION, build_task_protocol, word_set_for
from app.services.scoring import score_submission

ID_NAMESPACE = uuid.UUID("5b0e4c8a-3f1d-5a2e-9c47-7e6b1d2a9f30")

# Disjoint populations: the main ML population, the stress set, hand-authored fixtures, app demo data,
# and the presentation showcase (refinement 03) — never part of any training/calibration/test view.
POPULATION = {"main": 0, "stress": 1, "fixtures": 2, "demo": 3, "showcase": 4}
PROFILE_POPULATION = {"full": "main", "smoke": "main", "stress": "stress", "stress-smoke": "stress"}

# Stream components (§5: separate streams per patient and component).
C_PARAMS, C_SCENARIO, C_LATENT, C_CONTEXT, C_TASKS, C_QUALITY, C_PROTOCOL, C_MISSING, C_TIMING, C_ANCHOR = range(10)
C_SPLIT = 99

DOMAINS = ("memory", "attention", "reaction")
PERFORMANCE_SCENARIOS = {"isolated_worsening", "persistent_worsening", "single_domain_worsening", "improvement"}


def stream(root_seed: int, population: str, patient_index: int, component: int) -> np.random.Generator:
    seq = np.random.SeedSequence(root_seed, spawn_key=(POPULATION[population], patient_index, component))
    return np.random.Generator(np.random.PCG64(seq))


def make_id(identity: str, *parts: object) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, "/".join([identity, *map(str, parts)])))


def iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds")


@dataclass
class Event:
    kind: str
    start_slot: int
    duration: int
    domains: tuple[str, ...]
    recall_hit_delta: float = 0.0  # negative = worse
    false_alarm_delta: float = 0.0  # positive = worse
    log_rt_delta: float = 0.0  # positive = worse
    sleep_delta: float = 0.0
    mood_delta: float = 0.0

    def active(self, slot: int) -> bool:
        return self.start_slot <= slot < self.start_slot + self.duration

    @property
    def is_performance(self) -> bool:
        return self.kind in PERFORMANCE_SCENARIOS


@dataclass
class Overrides:
    """Hand-authored fixture controls (§7 fixture catalog). Empty for population patients."""

    missing_slots: set[int] = field(default_factory=set)
    faults: dict[int, str] = field(default_factory=dict)
    retake_slots: set[int] = field(default_factory=set)
    extra_slots: set[int] = field(default_factory=set)
    late_slots: dict[int, float] = field(default_factory=dict)  # slot -> availability delay in days
    mode_switch_slot: int | None = None
    device_change_slot: int | None = None
    missing_context: dict[int, tuple[str, ...]] = field(default_factory=dict)
    no_attention_response_slots: set[int] = field(default_factory=set)
    rt_slowdown_slots: dict[int, float] = field(default_factory=dict)  # slot -> log-RT shift
    force_clean: bool = False  # no random faults/missingness except those listed


@dataclass
class PatientPlan:
    index: int
    patient_id: str
    family_id: str
    population: str
    scenario: str
    trajectory: str
    params: dict[str, float]
    event: Event | None
    anchor: datetime
    overrides: Overrides = field(default_factory=Overrides)


@dataclass
class Generated:
    patients: list[dict[str, Any]]
    raw_sessions: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    truth: list[dict[str, Any]]
    clip_count: int = 0
    clip_total: int = 0


def _uniform(rng: np.random.Generator, r) -> float:
    return float(rng.uniform(r.low, r.high))


def _pick(rng: np.random.Generator, mix: dict[str, float]) -> str:
    names = sorted(mix)
    return str(rng.choice(names, p=[mix[n] for n in names]))


def plan_patient(config: GeneratorConfig, identity: str, population: str, index: int) -> PatientPlan:
    p_rng = stream(config.root_seed, population, index, C_PARAMS)
    params = {
        "recall_p0": _uniform(p_rng, config.initial_recall_p),
        "hit_p0": _uniform(p_rng, config.initial_hit_p),
        "false_alarm_p0": _uniform(p_rng, config.initial_false_alarm_p),
        "rt_median0_ms": _uniform(p_rng, config.initial_rt_median_ms),
        "recall_hit_trend": _uniform(p_rng, config.weekly_recall_hit_trend),
        "false_alarm_trend": _uniform(p_rng, config.weekly_false_alarm_trend),
        "log_rt_trend": _uniform(p_rng, config.weekly_log_rt_trend),
        "innovation_multiplier": _uniform(p_rng, config.innovation_multiplier),
        "sleep_center": _uniform(p_rng, config.sleep_center_hours),
        "mood_center": _uniform(p_rng, config.mood_center),
    }
    trajectory = _pick(p_rng, config.trajectory_mix)

    s_rng = stream(config.root_seed, population, index, C_SCENARIO)
    scenario = _pick(s_rng, config.scenario_mix)
    event = None
    if scenario != "background":
        start = int(s_rng.integers(int(config.event_start_slot.low), int(config.event_start_slot.high) + 1))
        if scenario == "isolated_worsening":
            duration = 1
        elif scenario == "persistent_worsening":
            duration = 3
        else:
            duration = int(s_rng.integers(1, 4))
        if scenario == "single_domain_worsening":
            domains: tuple[str, ...] = (str(s_rng.choice(DOMAINS)),)
        elif scenario == "context_only_change":
            domains = ()
        else:
            chosen = tuple(d for d in DOMAINS if s_rng.random() < 0.6)
            domains = chosen or (str(s_rng.choice(DOMAINS)),)
        sign = -1.0 if scenario == "improvement" else 1.0
        event = Event(kind=scenario, start_slot=start, duration=duration, domains=domains)
        if "memory" in domains or "attention" in domains:
            event.recall_hit_delta = -sign * _uniform(s_rng, config.recall_hit_drop)
        if "attention" in domains:
            event.false_alarm_delta = sign * _uniform(s_rng, config.false_alarm_rise)
        if "reaction" in domains:
            event.log_rt_delta = sign * _uniform(s_rng, config.log_rt_rise)
        if scenario == "context_only_change":
            event.sleep_delta = -float(s_rng.uniform(1.5, 3.0))
            event.mood_delta = -float(s_rng.uniform(1.5, 3.0))

    # Anchors are staggered by patient so no weekday/hour is a label shortcut.
    t_rng = stream(config.root_seed, population, index, C_ANCHOR)
    anchor = datetime.fromisoformat(config.anchor_epoch) + timedelta(hours=float(t_rng.uniform(0, 24 * 28)))
    return PatientPlan(
        index=index,
        patient_id=make_id(identity, "patient", population, index),
        family_id=make_id(identity, "family", population, index),
        population=population,
        scenario=scenario,
        trajectory=trajectory,
        params=params,
        event=event,
        anchor=anchor,
    )


def _shape(trajectory: str, trend: float, slot: int, slots: int) -> float:
    if trajectory == "stable":
        return 0.25 * trend * slot
    if trajectory == "linear":
        return trend * slot
    return 2.0 * trend * slot * slot / max(1, slots)  # mildly accelerating


def _innovation(rng: np.random.Generator, config: GeneratorConfig, sd: float) -> float:
    if config.noise_distribution == "student_t":
        df = config.student_t_df
        return float(rng.standard_t(df)) * sd / math.sqrt(df / (df - 2))
    return float(rng.normal(0, sd))


class _Clipper:
    def __init__(self) -> None:
        self.clipped = 0
        self.total = 0

    def __call__(self, value: float) -> float:
        self.total += 1
        if value < 0.01 or value > 0.99:
            self.clipped += 1
        return min(0.99, max(0.01, value))


def latent_series(plan: PatientPlan, config: GeneratorConfig, clip: _Clipper) -> tuple[list[Latent], list[float]]:
    """Per-slot latent propensities with AR(1) variation plus shared weekly shocks (returned for context)."""
    rng = stream(config.root_seed, plan.population, plan.index, C_LATENT)
    p = plan.params
    mult = p["innovation_multiplier"]
    ar = {"r": 0.0, "h": 0.0, "f": 0.0, "rt": 0.0}
    latents, shocks = [], []
    phi = config.ar1_coefficient
    for k in range(config.slots_per_patient):
        shock = float(rng.normal())
        shocks.append(shock)
        for key in ("r", "h", "f"):
            ar[key] = phi * ar[key] + _innovation(rng, config, config.innovation_sd_probability * mult)
        ar["rt"] = phi * ar["rt"] + _innovation(rng, config, config.innovation_sd_log_rt * mult)
        ev = plan.event if plan.event and plan.event.active(k) else None
        rh = ev.recall_hit_delta if ev else 0.0
        memory_affected = ev is not None and "memory" in ev.domains
        attention_affected = ev is not None and "attention" in ev.domains
        log_rt = (
            math.log(p["rt_median0_ms"])
            + _shape(plan.trajectory, p["log_rt_trend"], k, config.slots_per_patient)
            + ar["rt"]
            + (ev.log_rt_delta if ev else 0.0)
            - 0.01 * shock
            + plan.overrides.rt_slowdown_slots.get(k, 0.0)
        )
        latents.append(
            Latent(
                recall_p=clip(
                    p["recall_p0"]
                    + _shape(plan.trajectory, p["recall_hit_trend"], k, config.slots_per_patient)
                    + ar["r"]
                    + (rh if memory_affected else 0.0)
                    + 0.01 * shock
                ),
                hit_p=clip(
                    p["hit_p0"]
                    + _shape(plan.trajectory, p["recall_hit_trend"], k, config.slots_per_patient)
                    + ar["h"]
                    + (rh if attention_affected else 0.0)
                ),
                false_alarm_p=clip(
                    p["false_alarm_p0"]
                    + _shape(plan.trajectory, p["false_alarm_trend"], k, config.slots_per_patient)
                    + ar["f"]
                    + (ev.false_alarm_delta if ev else 0.0)
                ),
                log_rt=log_rt,
            )
        )
    return latents, shocks


def context_series(
    plan: PatientPlan, config: GeneratorConfig, shocks: list[float], stressed_slots: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(check-in payloads with explicit missingness, hidden originals for truth)."""
    rng = stream(config.root_seed, plan.population, plan.index, C_CONTEXT)
    m_rng = stream(config.root_seed, plan.population, plan.index, C_MISSING)
    w = config.shared_shock_weight
    payloads, originals = [], []
    for k, shock in enumerate(shocks):
        ev = plan.event if plan.event and plan.event.active(k) else None
        mix = lambda: w * shock + math.sqrt(1 - w * w) * float(rng.normal())  # noqa: E731
        sleep = min(24.0, max(0.0, plan.params["sleep_center"] + config.sleep_weekly_sd * mix() + (ev.sleep_delta if ev else 0)))
        mood = int(min(10, max(1, round(plan.params["mood_center"] + config.mood_weekly_sd * mix() + (ev.mood_delta if ev else 0)))))
        medication = "YES" if rng.random() < config.medication_change_probability else "NO"
        values = {"sleep_hours": round(sleep, 2), "mood_score": mood, "medication_change": medication}
        missing = []
        p_missing = config.missing_context_probability_per_field
        if config.correlated_missingness and k in stressed_slots:
            p_missing = min(0.9, p_missing * 3)
        forced = plan.overrides.missing_context.get(k)
        for name in ("sleep_hours", "mood_score", "medication_change"):
            draw = m_rng.random()  # always drawn so streams stay aligned
            reason = "SKIPPED" if m_rng.random() < 0.5 else "UNKNOWN"
            is_missing = name in forced if forced is not None else (not plan.overrides.force_clean and draw < p_missing)
            if is_missing:
                missing.append({"field": name, "reason": reason})
        payload = {**values, "reported_by": "PATIENT", "missing_fields": missing}
        for m in missing:
            payload[m["field"]] = None
        payloads.append(payload)
        originals.append(values)
    return payloads, originals


def _to_float(value: Any) -> float | None:
    return None if value is None else float(value)


def generate_population(
    config: GeneratorConfig, identity: str, population: str, plans: list[PatientPlan] | None = None
) -> Generated:
    """Generate every patient's sessions, score them canonically, select representatives."""
    if plans is None:
        plans = [plan_patient(config, identity, population, i) for i in range(config.patient_count)]
    out = Generated([], [], [], [])
    clip = _Clipper()
    for plan in plans:
        _generate_patient(plan, config, identity, out, clip)
    out.clip_count, out.clip_total = clip.clipped, clip.total
    return out


def _generate_patient(plan: PatientPlan, config: GeneratorConfig, identity: str, out: Generated, clip: _Clipper) -> None:
    ov = plan.overrides
    latents, shocks = latent_series(plan, config, clip)
    q_rng = stream(config.root_seed, plan.population, plan.index, C_QUALITY)
    task_rng = stream(config.root_seed, plan.population, plan.index, C_TASKS)
    proto_rng = stream(config.root_seed, plan.population, plan.index, C_PROTOCOL)
    time_rng = stream(config.root_seed, plan.population, plan.index, C_TIMING)
    miss_rng = stream(config.root_seed, plan.population, plan.index, C_MISSING)

    # Per-slot random decisions are all drawn up front so overrides never shift later draws.
    S = config.slots_per_patient
    slot_missing = [miss_rng.random() < config.missing_slot_probability for _ in range(S)]
    slot_fault_draw = [q_rng.random() for _ in range(S)]
    slot_fault_kind = [FAULT_KINDS[int(q_rng.integers(len(FAULT_KINDS)))] for _ in range(S)]
    retake_draw = [q_rng.random() for _ in range(S)]
    extra_draw = [q_rng.random() for _ in range(S)]
    switch_draw = q_rng.random()
    switch_slot_draw = int(q_rng.integers(config.history_length + 2, max(config.history_length + 3, S - 1)))
    mode_switch = ov.mode_switch_slot
    if mode_switch is None and not ov.force_clean and switch_draw < config.input_mode_switch_probability:
        mode_switch = switch_slot_draw
    stressed = {k for k in range(S) if (plan.event and plan.event.active(k)) or slot_fault_draw[k] < config.technical_issue_probability}
    contexts, originals = context_series(plan, config, shocks, stressed)
    # Fixtures are clean exemplars: no random false starts/anticipations beyond their named fault.
    noise = {'false_start_p': 0.0, 'anticipatory_p': 0.0} if ov.force_clean else {}
    options = TaskOptions(within_trial_log_rt_sd=config.within_trial_log_rt_sd, **noise)

    out.truth.append(
        {
            "kind": "patient",
            "patient_id": plan.patient_id,
            "family_id": plan.family_id,
            "population": plan.population,
            "scenario": plan.scenario,
            "trajectory": plan.trajectory,
            "latent_params": plan.params,
            "event": None
            if plan.event is None
            else {
                "event_id": make_id(identity, "event", plan.population, plan.index),
                "event_kind": plan.event.kind,
                "event_start_slot": plan.event.start_slot,
                "event_duration": plan.event.duration,
                "affected_domains": list(plan.event.domains),
                "is_performance_event": plan.event.is_performance,
                "magnitudes": {
                    "recall_hit_delta": plan.event.recall_hit_delta,
                    "false_alarm_delta": plan.event.false_alarm_delta,
                    "log_rt_delta": plan.event.log_rt_delta,
                    "sleep_delta": plan.event.sleep_delta,
                    "mood_delta": plan.event.mood_delta,
                },
            },
            "input_mode_switch_slot": mode_switch,
            "device_change_slot": ov.device_change_slot,
        }
    )

    sessions_started = 0
    epoch = 0
    submissions: list[schedule.SubmissionRef] = []
    patient_obs: list[dict[str, Any]] = []
    for k in range(S):
        missing_slot = k in ov.missing_slots or (not ov.force_clean and slot_missing[k])
        input_mode = "pointer" if mode_switch is not None and k >= mode_switch else "keyboard"
        device_changed = ov.device_change_slot == k
        if device_changed:
            epoch += 1
        target_at = schedule.target_for(plan.anchor, k)
        if missing_slot:
            continue
        attempts: list[str] = ["SCHEDULED"]
        start = target_at + timedelta(hours=float(time_rng.uniform(-10, 10)))
        attempt = 0
        while attempt < len(attempts):
            purpose = attempts[attempt]
            fault = ov.faults.get(k) if attempt == 0 else None
            if fault is None and not ov.force_clean and slot_fault_draw[k] < config.technical_issue_probability and attempt == 0:
                fault = slot_fault_kind[k]
            if k in ov.no_attention_response_slots:
                opts = TaskOptions(**{**options.__dict__, 'force_no_attention_responses': True})
            else:
                opts = options
            session_id = make_id(identity, "session", plan.population, plan.index, k, attempt)
            protocol = build_task_protocol(word_set_for(sessions_started), random.Random(int(proto_rng.integers(2**63))))
            sessions_started += 1
            payload, run_ms = build_raw_submission(
                protocol,
                latents[k],
                contexts[k],
                input_mode,
                task_rng,
                opts,
                fault,  # type: ignore[arg-type]
                submission_key=make_id(identity, "submission", plan.population, plan.index, k, attempt),
                run_id=make_id(identity, "run", plan.population, plan.index, k, attempt),
            )
            submission = AssessmentSubmission.model_validate(payload)
            result = score_submission(protocol, submission, input_mode)
            observed = start + timedelta(milliseconds=run_ms)
            available = observed + timedelta(days=ov.late_slots.get(k, 0.0))
            key = schedule.comparability_key(PROTOCOL_VERSION, SCORING_VERSION, input_mode, epoch)
            flags = sorted({f for t in (result.memory, result.attention, result.reaction) for f in t.flags})
            obs_id = make_id(identity, "observation", plan.population, plan.index, k, attempt)
            raw_record = {
                "session_id": session_id,
                "observation_id": obs_id,
                "patient_id": plan.patient_id,
                "slot_index": k,
                "attempt": attempt,
                "schedule_purpose": purpose,
                "clock": "SIMULATED",
                "source": "SYNTHETIC_HISTORY",
                "target_at": iso(target_at),
                "started_at": iso(start),
                "observed_at": iso(observed),
                "available_at": iso(available),
                "input_mode": input_mode,
                "device_changed": device_changed,
                "protocol_snapshot": protocol,
                "raw_submission": payload,
            }
            out.raw_sessions.append(raw_record)
            obs = {
                "observation_id": obs_id,
                "session_id": session_id,
                "patient_id": plan.patient_id,
                "family_id": plan.family_id,
                "slot_index": k,
                "attempt": attempt,
                "schedule_purpose": purpose,
                "clock": "SIMULATED",
                "source": "SYNTHETIC_HISTORY",
                "target_at": iso(target_at),
                "session_started_at": iso(start),
                "observed_at": iso(observed),
                "available_at": iso(available),
                "protocol_version": PROTOCOL_VERSION,
                "scoring_version": SCORING_VERSION,
                "input_mode": input_mode,
                "comparability_key": key,
                "memory_score": _to_float(result.memory.score),
                "attention_score": _to_float(result.attention.score),
                "reaction_time_ms": _to_float(result.reaction.score),
                "sleep_hours": contexts[k]["sleep_hours"],
                "mood_score": contexts[k]["mood_score"],
                "medication_change": contexts[k]["medication_change"],
                "missing_context": contexts[k]["missing_fields"],
                "quality": result.quality.value,
                "task_status": {
                    name: {"completion": t.completion, "status": t.status.value, "counters": t.counters}
                    for name, t in (("memory", result.memory), ("attention", result.attention), ("reaction", result.reaction))
                },
                "reason_flags": flags,
                "raw_sha256": _sha(payload),
            }
            patient_obs.append(obs)
            submissions.append(schedule.SubmissionRef(obs_id, k, purpose, result.quality.value, available))
            out.truth.append(
                {
                    "kind": "observation",
                    "observation_id": obs_id,
                    "patient_id": plan.patient_id,
                    "slot_index": k,
                    "event_active": bool(plan.event and plan.event.active(k)),
                    "performance_event_active": bool(plan.event and plan.event.active(k) and plan.event.is_performance),
                    "event_id": make_id(identity, "event", plan.population, plan.index) if plan.event and plan.event.active(k) else None,
                    "latent": {
                        "recall_p": latents[k].recall_p,
                        "hit_p": latents[k].hit_p,
                        "false_alarm_p": latents[k].false_alarm_p,
                        "rt_median_ms": math.exp(latents[k].log_rt),
                    },
                    "quality_fault_kind": fault,
                    "hidden_context": {m["field"]: originals[k][m["field"]] for m in contexts[k]["missing_fields"]},
                }
            )
            # Next attempt in this slot, following the live rules (guide 02 §5).
            if attempt == 0 and result.quality != Quality.VALID and (
                k in ov.retake_slots or (not ov.force_clean and retake_draw[k] < config.retake_probability)
            ):
                attempts.append("RETAKE_AFTER_UNRELIABLE")
            elif (
                result.quality == Quality.VALID
                and "EXTRA_ATTEMPT" not in attempts  # at most one extra per slot
                and (k in ov.extra_slots or (not ov.force_clean and extra_draw[k] < config.extra_attempt_probability))
            ):
                attempts.append("EXTRA_ATTEMPT")
            start = observed + timedelta(minutes=float(time_rng.uniform(10, 60)))
            attempt += 1

    reps = schedule.select_representatives(submissions)
    rep_ids = set(reps.values())
    for obs in patient_obs:
        obs["representative"] = obs["observation_id"] in rep_ids
        obs["longitudinal_eligible"] = obs["representative"]
    out.observations.extend(patient_obs)


def _sha(payload: dict[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- §7 fixture catalog -------------------------------------------------------------------------

def fixture_plans(config: GeneratorConfig, identity: str) -> list[PatientPlan]:
    """Hand-authored, disjoint fixture patients; each exercises one workflow edge case."""
    S = config.slots_per_patient
    mid = max(config.history_length + 1, min(int(config.event_start_slot.low) + 1, S - 4))

    def base(index: int, name: str, event: Event | None = None, **ov: Any) -> PatientPlan:
        plan = plan_patient(config, identity, "fixtures", index)
        plan.scenario = name
        plan.trajectory = "stable"
        plan.params.update({"recall_p0": 0.8, "hit_p0": 0.9, "false_alarm_p0": 0.08, "rt_median0_ms": 550.0,
                            "recall_hit_trend": 0.0, "false_alarm_trend": 0.0, "log_rt_trend": 0.0})
        plan.event = event
        plan.overrides = Overrides(force_clean=True, **ov)
        return plan

    worse = dict(recall_hit_delta=-0.35, false_alarm_delta=0.2, log_rt_delta=0.3)
    return [
        base(0, "fixture_background"),
        base(1, "fixture_isolated_event", Event("isolated_worsening", mid, 1, DOMAINS, **worse)),
        base(2, "fixture_persistent_event", Event("persistent_worsening", mid, 3, DOMAINS, **worse)),
        base(3, "fixture_context_only", Event("context_only_change", mid, 2, (), sleep_delta=-3.0, mood_delta=-3.0)),
        base(4, "fixture_missing_week", missing_slots={mid}),
        base(5, "fixture_hidden_tab_and_retake", faults={mid: "HIDDEN_TAB_ATTENTION"}, retake_slots={mid}),
        base(6, "fixture_extra_after_valid", extra_slots={mid}),
        base(7, "fixture_late_submission", late_slots={mid: 8.0}),
        base(8, "fixture_input_mode_switch", mode_switch_slot=mid),
        base(9, "fixture_device_change", device_change_slot=mid),
        base(10, "fixture_context_missing", missing_context={mid: ("sleep_hours", "mood_score", "medication_change")}),
        base(11, "fixture_no_attention_responses", no_attention_response_slots={mid}),
        base(12, "fixture_rt_timeouts", rt_slowdown_slots={mid: 2.0}),
        base(13, "fixture_skipped_task", faults={mid: "ATTENTION_SKIPPED"}),
        # Worsening that coincides with an unusable assessment: the event is hidden from analysis.
        base(14, "fixture_event_hidden_by_quality", Event("isolated_worsening", mid, 1, DOMAINS, **worse),
             faults={mid: "MEMORY_INTERRUPTION"}),
    ]
