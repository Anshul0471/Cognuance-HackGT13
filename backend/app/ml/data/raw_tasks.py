"""Construct guide-05 (`backend_contract_v1`) raw submissions from latent task propensities (guide 03 §6.3).

Scores are never generated directly: this module produces raw recall strings, trial offsets and
telemetry, and the canonical scorer (`app.services.scoring.score_submission`) derives every score
and quality result exactly as for a live submission. Quality faults are produced by changing raw
telemetry/completion, never by assigning LOW/INCOMPLETE afterwards.
"""

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from app.services.protocol import WORD_LISTS

# Wrong-answer vocabulary: disjoint from every scored list and the practice words.
DISTRACTOR_VOCABULARY = ("sun", "car", "house", "paper", "stone", "music", "coat", "shoe", "cup", "door")
assert not set(DISTRACTOR_VOCABULARY) & {w for words in WORD_LISTS.values() for w in words}

FaultKind = Literal[
    "HIDDEN_TAB_ATTENTION",
    "MEMORY_INTERRUPTION",
    "REACTION_STOPPED",
    "ANSWER_ASSISTANCE_UNSURE",
    "ATTENTION_SKIPPED",
]
FAULT_KINDS: tuple[FaultKind, ...] = (
    "HIDDEN_TAB_ATTENTION",
    "MEMORY_INTERRUPTION",
    "REACTION_STOPPED",
    "ANSWER_ASSISTANCE_UNSURE",
)


@dataclass(frozen=True)
class Latent:
    """One session's latent task propensities (truth-only; never exported as features)."""

    recall_p: float
    hit_p: float
    false_alarm_p: float
    log_rt: float  # natural log of the typical reaction median in ms


@dataclass(frozen=True)
class TaskOptions:
    within_trial_log_rt_sd: float
    false_start_p: float = 0.02
    anticipatory_p: float = 0.01
    incorrect_word_p: float = 0.15
    duplicate_word_p: float = 0.05
    case_variation_p: float = 0.10
    force_no_attention_responses: bool = False


def _r3(x: float) -> float:
    return round(float(x), 3)


def api_context(context: dict[str, Any]) -> dict[str, Any]:
    """Internal context (YES/NO strings, missing list) → guide 05 contract (boolean, reason map)."""
    med = context["medication_change"]
    return {
        "sleep_hours": context["sleep_hours"],
        "mood_score": context["mood_score"],
        "medication_change": None if med is None else med == "YES",
        "reported_by": context["reported_by"],
        "missing_fields": {m["field"]: m["reason"] for m in context["missing_fields"]},
    }


def build_raw_submission(
    protocol: dict[str, Any],
    latent: Latent,
    context: dict[str, Any],
    input_mode: str,
    rng: np.random.Generator,
    options: TaskOptions,
    fault: FaultKind | None,
    submission_key: str,
    run_id: str,
) -> tuple[dict[str, Any], float]:
    """Returns (raw submission payload, run duration in ms)."""
    visibility: list[dict[str, Any]] = []
    pauses: list[dict[str, Any]] = []
    t = 1000.0 + float(rng.uniform(30000, 90000))  # after preparation + practice

    # --- memory: independent recall of each frozen target -----------------------------------
    words = protocol["memory"]["words"]
    recalled = [w for w in words if rng.random() < latent.recall_p]
    rng.shuffle(recalled)
    entries = [w.capitalize() if rng.random() < options.case_variation_p else w for w in recalled]
    if recalled and rng.random() < options.duplicate_word_p:
        entries.append(recalled[0].upper())
    if rng.random() < options.incorrect_word_p:
        entries.append(str(rng.choice(DISTRACTOR_VOCABULARY)))
    entries = entries[:6]
    exposure_start = t
    exposure_end = exposure_start + 20000 + float(rng.uniform(0, 17))
    recall_start = exposure_end + 30000 + float(rng.uniform(0, 17))
    recall_end = recall_start + float(rng.uniform(8000, 45000))
    memory: dict[str, Any] = {
        "completion": "COMPLETED",
        "exposure_start_ms": _r3(exposure_start),
        "exposure_end_ms": _r3(exposure_end),
        "distractor_start_ms": _r3(exposure_end),
        "distractor_end_ms": _r3(recall_start),
        "recall_start_ms": _r3(recall_start),
        "recall_end_ms": _r3(recall_end),
        "recall_entries": entries,
        "end_reason": "DONE" if entries else "NONE_RECALLED",
        "interruptions": [],
    }
    if fault == "MEMORY_INTERRUPTION":
        hidden_at = exposure_end + float(rng.uniform(1000, 25000))
        memory["interruptions"] = [{"kind": "HIDDEN", "start_ms": _r3(hidden_at), "end_ms": _r3(hidden_at + 4000)}]
        visibility += [
            {"offset_ms": _r3(hidden_at), "state": "hidden"},
            {"offset_ms": _r3(hidden_at + 4000), "state": "visible"},
        ]
    t = recall_end + float(rng.uniform(3000, 30000))  # break

    # --- attention: exact frozen sequence, first press inside [onset, onset+1000) --------------
    attention_trials = []
    interrupt_index = 14 if fault == "HIDDEN_TAB_ATTENTION" else None
    for i, spec in enumerate(protocol["attention"]["trials"]):
        onset = t
        if i == interrupt_index:
            cut = onset + 300
            attention_trials.append(
                {"trial_id": spec["id"], "onset_ms": _r3(onset), "offset_ms": _r3(cut), "gap_end_ms": _r3(cut),
                 "responses": [], "event_overflow": False,
                 "interruptions": [{"kind": "HIDDEN", "start_ms": _r3(cut), "end_ms": _r3(cut + 5000)}]}
            )
            visibility += [
                {"offset_ms": _r3(cut), "state": "hidden"},
                {"offset_ms": _r3(cut + 5000), "state": "visible"},
            ]
            pauses.append({"start_ms": _r3(cut + 5000), "end_ms": _r3(cut + 8000)})
            t = cut + 10000
            continue
        offset = onset + 1000 + float(rng.uniform(0, 17))
        gap_end = offset + 500 + float(rng.uniform(0, 17))
        p = latent.hit_p if spec["is_target"] else latent.false_alarm_p
        responses = []
        if not options.force_no_attention_responses and rng.random() < p:
            latency = min(990.0, max(150.0, 0.6 * math.exp(latent.log_rt + rng.normal(0, 0.2))))
            responses.append(_r3(onset + latency))
        attention_trials.append(
            {"trial_id": spec["id"], "onset_ms": _r3(onset), "offset_ms": _r3(offset), "gap_end_ms": _r3(gap_end),
             "responses": [{"offset_ms": r} for r in responses], "interruptions": [], "event_overflow": False}
        )
        t = gap_end
    attention = {"completion": "COMPLETED", "trials": attention_trials, "end_reason": "FINISHED"}
    if fault == "ATTENTION_SKIPPED":
        attention = {"completion": "SKIPPED", "trials": [], "end_reason": "SKIPPED"}
    t += float(rng.uniform(3000, 30000))

    # --- reaction: log-space latencies, real false-start/anticipatory/timeout outcomes -----------
    reaction_trials = []
    stop_after = 6 if fault == "REACTION_STOPPED" else None
    for i, spec in enumerate(protocol["reaction"]["trials"]):
        if stop_after is not None and i >= stop_after:
            break
        wait_start = t
        go = wait_start + spec["foreperiod_ms"] + float(rng.uniform(0, 17))
        if rng.random() < options.false_start_p:
            press = wait_start + float(rng.uniform(200, spec["foreperiod_ms"] - 50))
            trial = {"go_onset_ms": None, "end_ms": _r3(press), "responses": [_r3(press)], "end_reason": "FALSE_START"}
        else:
            if rng.random() < options.anticipatory_p:
                latency = float(rng.uniform(40, 99.9))
            else:
                latency = math.exp(rng.normal(latent.log_rt, options.within_trial_log_rt_sd))
            if latency >= 3000:  # not truncated: a slow draw becomes a real timeout
                end = go + 3000 + float(rng.uniform(0, 17))
                trial = {"go_onset_ms": _r3(go), "end_ms": _r3(end), "responses": [], "end_reason": "TIMEOUT"}
            else:
                press = go + latency
                trial = {"go_onset_ms": _r3(go), "end_ms": _r3(press), "responses": [_r3(press)], "end_reason": "RESPONSE"}
        trial["responses"] = [{"offset_ms": r} for r in trial["responses"]]
        reaction_trials.append(
            {"trial_id": spec["id"], "wait_start_ms": _r3(wait_start), **trial,
             "intertrial_end_ms": _r3(trial["end_ms"] + 750), "interruptions": [],
             "max_frame_gap_ms": 16.7, "event_overflow": False}
        )
        t = trial["end_ms"] + 750
    stopped = stop_after is not None
    reaction = {"completion": "STOPPED" if stopped else "COMPLETED", "trials": reaction_trials,
                "end_reason": "STOPPED" if stopped else "FINISHED"}

    run_duration = t + float(rng.uniform(20000, 90000))  # context check-in
    answers = {"memory": "NONE", "attention": "NONE", "reaction": "NONE"}
    if fault == "ANSWER_ASSISTANCE_UNSURE":
        answers["memory"] = "UNKNOWN"
    payload = {
        "submission_key": submission_key,
        "run_id": run_id,
        "protocol_version": protocol["protocol_version"],
        "run_duration_ms": _r3(run_duration),
        "memory": memory,
        "attention": attention,
        "reaction": reaction,
        "practice": {"completed": True, "repeats": 0},
        "telemetry": {
            "initial_input_mode": input_mode,
            "final_input_mode": input_mode,
            "viewport": {"width": 1300, "height": 800},
            "visibility_events": sorted(visibility, key=lambda e: e["offset_ms"]),
            "pause_events": pauses,
            "blur_count": 0,
            "mode_changes": [],
            "event_overflow": False,
            "assistance": {"navigation_help": False, "context_help": False, "answer_help": answers},
        },
        "context": api_context(context),
    }
    return payload, run_duration
