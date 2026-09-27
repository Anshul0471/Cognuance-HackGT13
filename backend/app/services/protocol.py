"""Protocol `cognitive_tasks_en_v1`: frozen task material and per-session randomization (guide 02 §4, §7–§9).

Pure functions only. Randomization happens once at session start and the concrete result is stored
in the session snapshot; it is never regenerated.
"""

import random
from typing import Any

PROTOCOL_VERSION = "cognitive_tasks_en_v1"
SCORING_VERSION = "cognitive_scoring_v1"
LANGUAGE = "en"
SESSION_EXPIRY_MINUTES = 20

WORD_LISTS: dict[str, tuple[str, ...]] = {
    "A": ("apple", "chair", "river", "candle", "garden", "spoon"),
    "B": ("bread", "window", "mountain", "button", "rabbit", "pencil"),
    "C": ("orange", "table", "ocean", "basket", "flower", "clock"),
    "D": ("bottle", "forest", "train", "pillow", "lemon", "horse"),
}
WORD_LIST_ORDER = ("A", "B", "C", "D")
WORD_ASSIGNMENT_RULE = "abcd_rotation_by_started_sessions_v1"

# Practice material must never overlap the scored lists.
PRACTICE_MEMORY_WORDS = ("lamp", "cloud")
PRACTICE_ATTENTION_TRIALS = (
    {"id": "patt-1", "shape": "circle", "is_target": True},
    {"id": "patt-2", "shape": "square", "is_target": False},
    {"id": "patt-3", "shape": "circle", "is_target": True},
    {"id": "patt-4", "shape": "triangle", "is_target": False},
)
PRACTICE_REACTION_FOREPERIODS_MS = (2000, 2600)

MEMORY_CONFIG = {
    "exposure_ms": 20000,
    "distractor_ms": 30000,
    "recall_limit_ms": 60000,
    "max_entries": 6,
    "max_entry_chars": 40,
    "duration_tolerance_ms": 1000,
    "distractor_step_ms": 2000,
}
ATTENTION_CONFIG = {
    "trial_count": 30,
    "target_count": 10,
    "stimulus_ms": 1000,
    "gap_ms": 500,
    "stimulus_tolerance_ms": 100,
    "gap_tolerance_ms": 150,
    "max_consecutive_targets": 3,
}
REACTION_CONFIG = {
    "trial_count": 10,
    "foreperiod_min_ms": 1500,
    "foreperiod_max_ms": 3500,
    "response_window_ms": 3000,
    "minimum_response_ms": 100,
    "minimum_usable_trials": 8,
    "intertrial_ms": 750,
    "foreperiod_tolerance_ms": 100,
}
LIMITS = {
    "max_body_bytes": 256 * 1024,
    "max_events_per_trial": 20,
    "max_telemetry_events": 500,
    "max_run_duration_ms": SESSION_EXPIRY_MINUTES * 60 * 1000,
}

_MAX_SHUFFLE_ATTEMPTS = 1000
# Deterministic valid fallback (never more than 3 consecutive targets): 10 circles, 10 squares, 10 triangles.
_FALLBACK_SHAPES = ("circle", "square", "triangle") * 10


def word_set_for(previous_started_sessions: int) -> str:
    """Rotate A→B→C→D over all previously started scored sessions (a retake therefore differs)."""
    return WORD_LIST_ORDER[previous_started_sessions % len(WORD_LIST_ORDER)]


def _max_consecutive_targets(shapes: list[str]) -> int:
    longest = run = 0
    for shape in shapes:
        run = run + 1 if shape == "circle" else 0
        longest = max(longest, run)
    return longest


def attention_sequence(rng: random.Random) -> tuple[list[dict[str, Any]], str]:
    shapes = ["circle"] * 10 + ["square"] * 10 + ["triangle"] * 10
    method = "fallback_v1"
    for _ in range(_MAX_SHUFFLE_ATTEMPTS):
        rng.shuffle(shapes)
        if _max_consecutive_targets(shapes) <= ATTENTION_CONFIG["max_consecutive_targets"]:
            method = "rejection_sampling_v1"
            break
    else:
        shapes = list(_FALLBACK_SHAPES)
    trials = [
        {"id": f"att-{i + 1:02d}", "shape": shape, "is_target": shape == "circle"}
        for i, shape in enumerate(shapes)
    ]
    return trials, method


def reaction_trials(rng: random.Random) -> list[dict[str, Any]]:
    low, high = REACTION_CONFIG["foreperiod_min_ms"], REACTION_CONFIG["foreperiod_max_ms"]
    return [{"id": f"rt-{i + 1:02d}", "foreperiod_ms": rng.randint(low, high)} for i in range(10)]


def build_task_protocol(word_set_id: str, rng: random.Random) -> dict[str, Any]:
    """Task material portion of the snapshot (memory, attention, reaction, practice, limits)."""
    attention, method = attention_sequence(rng)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "scoring_version": SCORING_VERSION,
        "language": LANGUAGE,
        "memory": {
            "word_set_id": word_set_id,
            "words": list(WORD_LISTS[word_set_id]),
            "assignment_rule": WORD_ASSIGNMENT_RULE,
            **MEMORY_CONFIG,
        },
        "attention": {**ATTENTION_CONFIG, "randomization": method, "trials": attention},
        "reaction": {**REACTION_CONFIG, "trials": reaction_trials(rng)},
        "practice": {
            "memory_words": list(PRACTICE_MEMORY_WORDS),
            "attention_trials": [dict(t) for t in PRACTICE_ATTENTION_TRIALS],
            "reaction_foreperiods_ms": list(PRACTICE_REACTION_FOREPERIODS_MS),
            "max_repeats": 1,
        },
        "limits": dict(LIMITS),
    }
