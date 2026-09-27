"""One-way upgrade of `dataset_schema_v1` raw payloads (guide-02 field names) to the guide-05 contract.

Used only when reading synthetic datasets generated before `dataset_schema_v2`; the API accepts the
new contract only. Replaying every stored v1 payload through this converter and the current scorer
must reproduce the stored scores/quality exactly (validate_dataset checks it), which also proves
the contract change did not alter scoring behaviour.
"""

from typing import Any

_ANSWER = {"YES": "PROVIDED", "NO": "NONE", "UNSURE": "UNKNOWN"}
_MEDICATION = {"YES": True, "NO": False}


def _responses(offsets: list[float]) -> list[dict[str, float]]:
    return [{"offset_ms": o} for o in offsets]


def _interruption(flag: bool, start: float | None) -> list[dict[str, Any]]:
    return [{"kind": "HIDDEN", "start_ms": start or 0.0, "end_ms": None}] if flag else []


def upgrade_v1_payload(old: dict[str, Any]) -> dict[str, Any]:
    m = old["memory"]
    memory = {
        "completion": m["completion"],
        "exposure_start_ms": m.get("exposure_start_ms"),
        "exposure_end_ms": m.get("exposure_end_ms"),
        # v1 measured the distractor as recall_start - exposure_end.
        "distractor_start_ms": m.get("exposure_end_ms") if m.get("recall_start_ms") is not None else None,
        "distractor_end_ms": m.get("recall_start_ms"),
        "recall_start_ms": m.get("recall_start_ms"),
        "recall_end_ms": m.get("recall_end_ms"),
        "recall_entries": m.get("recall_entries", []),
        "end_reason": "NONE_RECALLED" if m["end_reason"] == "NONE_REMEMBERED" else m["end_reason"],
        "interruptions": _interruption(m.get("interrupted", False), m.get("exposure_start_ms")),
    }
    attention_trials = [
        {
            "trial_id": t["id"],
            "onset_ms": t["onset_ms"],
            "offset_ms": t.get("offset_ms"),
            "gap_end_ms": t.get("gap_end_ms"),
            "responses": _responses(t.get("responses_ms", [])),
            "interruptions": _interruption(t.get("interrupted", False), t["onset_ms"]),
            "event_overflow": t.get("response_overflow", False),
        }
        for t in old["attention"]["trials"]
    ]
    reaction_trials = [
        {
            "trial_id": t["id"],
            "wait_start_ms": t["wait_start_ms"],
            "go_onset_ms": t.get("go_onset_ms"),
            "end_ms": t["end_ms"],
            "intertrial_end_ms": None,  # not recorded in v1
            "responses": _responses(t.get("responses_ms", [])),
            "end_reason": t["end_reason"],
            "interruptions": _interruption(
                t.get("interrupted", False) or t["end_reason"] == "INTERRUPTED", t["wait_start_ms"]
            ),
            "max_frame_gap_ms": None,  # not recorded in v1
            "event_overflow": t.get("response_overflow", False),
        }
        for t in old["reaction"]["trials"]
    ]

    tel = old["telemetry"]
    visibility, pauses, modes, blur = [], [], [], 0
    for e in sorted(tel.get("events", []), key=lambda e: e["offset_ms"]):
        kind, at = e["type"], e["offset_ms"]
        if kind in ("VISIBILITY_HIDDEN", "VISIBILITY_VISIBLE"):
            visibility.append({"offset_ms": at, "state": "hidden" if kind == "VISIBILITY_HIDDEN" else "visible"})
        elif kind in ("PAUSE", "AUTH_INTERRUPTION"):
            pauses.append({"start_ms": at, "end_ms": None if kind == "PAUSE" else at})
        elif kind == "RESUME":
            open_pause = next((p for p in reversed(pauses) if p["end_ms"] is None), None)
            if open_pause is not None:
                open_pause["end_ms"] = at
        elif kind == "BLUR":
            blur += 1
        elif kind == "INPUT_MODE_CHANGED":
            modes.append({"offset_ms": at, "from": tel["input_mode"], "to": tel["input_mode"]})
    a = tel["assistance"]

    ctx = old["context"]
    missing = {f["field"]: f["reason"] for f in ctx.get("missing_fields", [])}
    med = ctx.get("medication_change")
    if med == "NOT_SURE":
        missing["medication_change"] = "UNKNOWN"

    def task_end(record: dict[str, Any]) -> str:
        return "FINISHED" if record["completion"] == "COMPLETED" else record["completion"]

    return {
        "submission_key": old["submission_key"],
        "run_id": old["run_id"],
        "protocol_version": old["protocol_version"],
        "run_duration_ms": old["run_duration_ms"],
        "memory": memory,
        "attention": {"completion": old["attention"]["completion"], "trials": attention_trials,
                      "end_reason": task_end(old["attention"])},
        "reaction": {"completion": old["reaction"]["completion"], "trials": reaction_trials,
                     "end_reason": task_end(old["reaction"])},
        "practice": {"completed": old["practice"]["completed"], "repeats": old["practice"]["repeat_count"]},
        "telemetry": {
            "initial_input_mode": tel["input_mode"],
            "final_input_mode": tel["input_mode"],
            "viewport": tel["viewport"],
            "visibility_events": visibility,
            "pause_events": pauses,
            "blur_count": blur,
            "mode_changes": modes,
            "event_overflow": tel.get("events_overflow", False),
            "assistance": {
                "navigation_help": a["navigation"],
                "context_help": a["context_entry"],
                "answer_help": {k: _ANSWER[v] for k, v in a["answers"].items()},
            },
        },
        "context": {
            "sleep_hours": ctx.get("sleep_hours"),
            "mood_score": ctx.get("mood_score"),
            "medication_change": _MEDICATION.get(med) if med is not None else None,
            "reported_by": ctx["reported_by"],
            "missing_fields": missing,
        },
    }
