"""Builds timeline-consistent raw submissions for a frozen protocol (test helper, not app code)."""

import uuid
from collections.abc import Callable
from typing import Any

# Per-trial reaction behaviour: latency in ms after GO, or one of these markers.
FALSE_START = "false_start"
TIMEOUT = "timeout"

ReactionSpec = float | str


def default_context() -> dict[str, Any]:
    return {
        "sleep_hours": 7.25,
        "mood_score": 7,
        "medication_change": False,
        "reported_by": "PATIENT",
        "missing_fields": {},
    }


def build_payload(
    protocol: dict[str, Any],
    *,
    input_mode: str = "keyboard",
    final_input_mode: str | None = None,
    memory_entries: list[str] | None = None,
    memory_completion: str = "COMPLETED",
    memory_end_reason: str | None = None,
    memory_interruptions: list[dict[str, Any]] | None = None,
    exposure_ms: float = 20000,
    distractor_ms: float = 30000,
    attention_trials: int = 30,
    attention_completion: str = "COMPLETED",
    attention_press: Callable[[dict[str, Any]], list[float]] | None = None,
    reaction: list[ReactionSpec] | None = None,
    reaction_completion: str = "COMPLETED",
    visibility_events: list[dict[str, Any]] | None = None,
    pause_events: list[dict[str, Any]] | None = None,
    mode_changes: list[dict[str, Any]] | None = None,
    blur_count: int = 0,
    answer_assistance: dict[str, str] | None = None,
    context: dict[str, Any] | None = None,
    submission_key: str | None = None,
) -> dict[str, Any]:
    """A complete, timeline-consistent guide-05 submission built from the frozen session protocol.

    `answer_assistance` values are NONE / PROVIDED / UNKNOWN. Offsets start at 1000 ms.
    """
    t = 1000.0
    words = protocol["memory"]["words"]
    entries = list(words) if memory_entries is None else memory_entries
    if memory_completion == "COMPLETED":
        exp_start, exp_end = t, t + exposure_ms
        recall_start = exp_end + distractor_ms
        recall_end = recall_start + 15000
        memory = {
            "completion": "COMPLETED",
            "exposure_start_ms": exp_start,
            "exposure_end_ms": exp_end,
            "distractor_start_ms": exp_end,
            "distractor_end_ms": recall_start,
            "recall_start_ms": recall_start,
            "recall_end_ms": recall_end,
            "recall_entries": entries,
            "end_reason": memory_end_reason or ("DONE" if entries else "NONE_RECALLED"),
            "interruptions": memory_interruptions or [],
        }
        t = recall_end + 2000
    else:
        memory = {
            "completion": memory_completion,
            **{
                k: None
                for k in (
                    "exposure_start_ms",
                    "exposure_end_ms",
                    "distractor_start_ms",
                    "distractor_end_ms",
                    "recall_start_ms",
                    "recall_end_ms",
                )
            },
            "recall_entries": [],
            "end_reason": memory_completion,
            "interruptions": memory_interruptions or [],
        }

    # Attention: by default press on targets only, 450 ms after onset.
    press = attention_press or (lambda spec: [450.0] if spec["is_target"] else [])
    att_trials = []
    for spec in protocol["attention"]["trials"][:attention_trials]:
        onset = t
        offset = onset + 1000
        gap_end = offset + 500
        att_trials.append(
            {
                "trial_id": spec["id"],
                "onset_ms": onset,
                "offset_ms": offset,
                "gap_end_ms": gap_end,
                "responses": [{"offset_ms": onset + r} for r in press(spec)],
                "interruptions": [],
                "event_overflow": False,
            }
        )
        t = gap_end
    t += 2000

    reaction = reaction if reaction is not None else [300.0 + 20 * i for i in range(10)]
    rt_trials = []
    for spec, behaviour in zip(protocol["reaction"]["trials"], reaction, strict=False):
        wait_start = t
        go = wait_start + spec["foreperiod_ms"]
        if behaviour == FALSE_START:
            response = wait_start + 500
            trial = {
                "go_onset_ms": None,
                "end_ms": response,
                "responses": [response],
                "end_reason": "FALSE_START",
            }
        elif behaviour == TIMEOUT:
            trial = {"go_onset_ms": go, "end_ms": go + 3000, "responses": [], "end_reason": "TIMEOUT"}
        else:
            response = go + float(behaviour)
            trial = {"go_onset_ms": go, "end_ms": response, "responses": [response], "end_reason": "RESPONSE"}
        rt_trials.append(
            {
                "trial_id": spec["id"],
                "wait_start_ms": wait_start,
                **trial,
                "responses": [{"offset_ms": r} for r in trial["responses"]],
                "intertrial_end_ms": trial["end_ms"] + 750,
                "interruptions": [],
                "max_frame_gap_ms": 17.0,
                "event_overflow": False,
            }
        )
        t = trial["end_ms"] + 750

    def task_end(completion: str) -> str:
        return "FINISHED" if completion == "COMPLETED" else completion

    return {
        "submission_key": submission_key or str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "protocol_version": protocol["protocol_version"],
        "run_duration_ms": t + 30000,
        "memory": memory,
        "attention": {
            "completion": attention_completion,
            "trials": att_trials,
            "end_reason": task_end(attention_completion),
        },
        "reaction": {
            "completion": reaction_completion,
            "trials": rt_trials,
            "end_reason": task_end(reaction_completion),
        },
        "practice": {"completed": True, "repeats": 0},
        "telemetry": {
            "initial_input_mode": input_mode,
            "final_input_mode": final_input_mode or input_mode,
            "viewport": {"width": 1200, "height": 800},
            "visibility_events": visibility_events or [],
            "pause_events": pause_events or [],
            "blur_count": blur_count,
            "mode_changes": mode_changes or [],
            "event_overflow": False,
            "assistance": {
                "navigation_help": False,
                "context_help": False,
                "answer_help": answer_assistance
                or {"memory": "NONE", "attention": "NONE", "reaction": "NONE"},
            },
        },
        "context": context or default_context(),
    }
