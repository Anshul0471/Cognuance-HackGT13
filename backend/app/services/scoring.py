"""`cognitive_scoring_v1`: deterministic, pure scoring and quality classification (guide 02 §7–§11).

Inputs are the frozen session snapshot and a validated submission; outputs are scores, per-task
quality evidence, and overall quality. No HTTP, database, or model code belongs here.

Numbers: offsets are converted with Decimal(repr(float)) so boundary comparisons (e.g. 99.999 vs
100 ms) use the submitted decimal value exactly. Scores are rounded to 3 places, ROUND_HALF_UP.
"""

import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.models import Quality
from app.schemas.assessments import AssessmentSubmission

SCORING_DETAILS_VERSION = "quality_v1"
_THOUSANDTH = Decimal("0.001")

# Flags that lower a task to LOW. Everything else recorded is a warning only.
LOW_FLAGS = frozenset(
    {
        "INTERRUPTION",
        "TRIAL_INTERRUPTED",
        "EXPOSURE_TIMING_DEVIATION",
        "DISTRACTOR_TIMING_DEVIATION",
        "RECALL_TIMING_DEVIATION",
        "TIMING_DEVIATION",
        "TIMER_INTERRUPTION",
        "INPUT_MODE_CHANGED",
        "ANSWER_ASSISTANCE",
        "ASSISTANCE_UNCERTAIN",
        "RT_TIMEOUT_PRESENT",
        "INSUFFICIENT_USABLE_TRIALS",
        "RESPONSE_OVERFLOW",
        "TELEMETRY_OVERFLOW",
    }
)


class ScoringInputError(ValueError):
    """Structural mismatch with the frozen protocol: a request error, not a LOW assessment."""


def d(value: float) -> Decimal:
    return Decimal(repr(value))


def q3(value: Decimal) -> Decimal:
    return value.quantize(_THOUSANDTH, rounding=ROUND_HALF_UP)


@dataclass
class TaskResult:
    completion: str
    complete: bool
    score: Decimal | None
    flags: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    components: dict[str, Any] = field(default_factory=dict)

    def flag(self, code: str) -> None:
        if code not in self.flags:
            self.flags.append(code)

    @property
    def status(self) -> Quality:
        if not self.complete:
            return Quality.INCOMPLETE
        if any(f in LOW_FLAGS for f in self.flags):
            return Quality.LOW
        return Quality.VALID

    def as_details(self) -> dict[str, Any]:
        return {
            "completion": self.completion,
            "status": self.status.value,
            "score": str(self.score) if self.score is not None else None,
            "low_flags": [f for f in self.flags if f in LOW_FLAGS],
            "warnings": [f for f in self.flags if f not in LOW_FLAGS],
            "counters": self.counters,
        }


@dataclass
class ScoringResult:
    memory: TaskResult
    attention: TaskResult
    reaction: TaskResult
    quality: Quality
    quality_reasons: list[str]
    details: dict[str, Any]


# --- helpers ------------------------------------------------------------------------------------


def normalize_word(text: str) -> str:
    """NFKC, casefold, trim whitespace, strip leading/trailing punctuation. No fuzzy matching."""
    s = unicodedata.normalize("NFKC", text).casefold().strip()
    start, end = 0, len(s)
    while start < end and unicodedata.category(s[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(s[end - 1]).startswith("P"):
        end -= 1
    return s[start:end].strip()


def _in_window(offset: float, window: tuple[float, float] | None) -> bool:
    return window is not None and window[0] <= offset <= window[1]


def _hidden_or_paused(sub: AssessmentSubmission, window: tuple[float, float] | None) -> bool:
    """Page hidden or run paused during the task's span (telemetry evidence, window-based)."""
    tel = sub.telemetry
    if any(e.state == "hidden" and _in_window(e.offset_ms, window) for e in tel.visibility_events):
        return True
    for p in tel.pause_events:
        end = p.end_ms if p.end_ms is not None else sub.run_duration_ms
        if window is not None and p.start_ms <= window[1] and end >= window[0]:
            return True
    return False


def _apply_common_flags(
    result: TaskResult,
    task: str,
    window: tuple[float, float] | None,
    sub: AssessmentSubmission,
    input_mode: str,
) -> None:
    tel = sub.telemetry
    if _hidden_or_paused(sub, window):
        result.flag("INTERRUPTION")
    if task in ("attention", "reaction") and (
        tel.initial_input_mode != input_mode
        or tel.final_input_mode != input_mode
        or any(_in_window(m.offset_ms, window) for m in tel.mode_changes)
    ):
        result.flag("INPUT_MODE_CHANGED")
    if tel.event_overflow:
        result.flag("TELEMETRY_OVERFLOW")
    answer = getattr(tel.assistance.answer_help, task)
    if answer == "PROVIDED":
        result.flag("ANSWER_ASSISTANCE")
    elif answer == "UNKNOWN":
        result.flag("ASSISTANCE_UNCERTAIN")


def _check_ids(submitted: list[str], expected: list[str], task: str) -> None:
    if submitted != expected[: len(submitted)]:
        raise ScoringInputError(f"{task} trial IDs do not match the session protocol order")


# --- memory -------------------------------------------------------------------------------------


def score_memory(protocol: dict[str, Any], sub: AssessmentSubmission, input_mode: str) -> TaskResult:
    cfg = protocol["memory"]
    m = sub.memory
    complete = m.completion == "COMPLETED"
    result = TaskResult(completion=m.completion, complete=complete, score=None)

    targets = [normalize_word(w) for w in cfg["words"]]
    matched: list[str] = []
    incorrect: list[str] = []
    duplicates: list[str] = []
    for entry in m.recall_entries:
        norm = normalize_word(entry)
        if not norm:
            continue
        if norm in targets:
            (duplicates if norm in matched else matched).append(norm)
        else:
            incorrect.append(entry)

    if complete:
        result.score = q3(Decimal(100) * len(matched) / len(targets))
        tol = cfg["duration_tolerance_ms"]
        exposure = m.exposure_end_ms - m.exposure_start_ms  # type: ignore[operator]  # validated present
        distractor = m.distractor_end_ms - m.distractor_start_ms  # type: ignore[operator]
        recall = m.recall_end_ms - m.recall_start_ms  # type: ignore[operator]
        if abs(exposure - cfg["exposure_ms"]) > tol:
            result.flag("EXPOSURE_TIMING_DEVIATION")
        if abs(distractor - cfg["distractor_ms"]) > tol:
            result.flag("DISTRACTOR_TIMING_DEVIATION")
        if recall > cfg["recall_limit_ms"] + tol:
            result.flag("RECALL_TIMING_DEVIATION")
        result.components["durations_ms"] = {"exposure": exposure, "distractor": distractor, "recall": recall}
    else:
        result.flag("TASK_NOT_COMPLETED")

    if m.interruptions:
        result.flag("INTERRUPTION")
    window = None
    if m.exposure_start_ms is not None:
        end = m.recall_end_ms if m.recall_end_ms is not None else sub.run_duration_ms
        window = (m.exposure_start_ms, end)
    _apply_common_flags(result, "memory", window, sub, input_mode)

    result.counters = {"correct": len(matched), "incorrect": len(incorrect), "duplicates": len(duplicates)}
    # Server-side only: never returned in patient receipts.
    result.components.update(
        {
            "word_set_id": cfg["word_set_id"],
            "matched": matched,
            "incorrect": incorrect,
            "duplicates": duplicates,
        }
    )
    return result


# --- attention ----------------------------------------------------------------------------------


def score_attention(protocol: dict[str, Any], sub: AssessmentSubmission, input_mode: str) -> TaskResult:
    cfg = protocol["attention"]
    a = sub.attention
    expected = cfg["trials"]
    _check_ids([t.trial_id for t in a.trials], [t["id"] for t in expected], "attention")

    window_ms = d(cfg["stimulus_ms"])
    counts = {
        "hits": 0,
        "misses": 0,
        "false_alarms": 0,
        "correct_rejections": 0,
        "extra_presses": 0,
        "gap_presses": 0,
    }
    per_trial = []
    for trial, spec in zip(a.trials, expected, strict=False):
        onset = d(trial.onset_ms)
        responses = sorted(d(r.offset_ms) for r in trial.responses)
        in_window = [r for r in responses if onset <= r < onset + window_ms]
        responded = bool(in_window)
        counts["extra_presses"] += max(0, len(in_window) - 1)
        counts["gap_presses"] += len(responses) - len(in_window)
        if spec["is_target"]:
            outcome = "hit" if responded else "miss"
        else:
            outcome = "false_alarm" if responded else "correct_rejection"
        counts[
            {"hit": "hits", "miss": "misses", "false_alarm": "false_alarms"}.get(
                outcome, "correct_rejections"
            )
        ] += 1
        per_trial.append({"id": trial.trial_id, "outcome": outcome})

        # Interrupted trials are recorded (not redone) and flagged separately below.
        if not trial.interruptions and trial.offset_ms is not None and trial.gap_end_ms is not None:
            stim = trial.offset_ms - trial.onset_ms
            gap = trial.gap_end_ms - trial.offset_ms
            per_trial[-1]["timing_ok"] = (
                abs(stim - cfg["stimulus_ms"]) <= cfg["stimulus_tolerance_ms"]
                and abs(gap - cfg["gap_ms"]) <= cfg["gap_tolerance_ms"]
            )

    result = TaskResult(completion=a.completion, complete=False, score=None)
    if any(t.interruptions for t in a.trials):
        result.flag("TRIAL_INTERRUPTED")
    if any(p.get("timing_ok") is False for p in per_trial):
        result.flag("TIMING_DEVIATION")
    if any(t.event_overflow for t in a.trials):
        result.flag("RESPONSE_OVERFLOW")

    result.complete = a.completion == "COMPLETED" and len(a.trials) == cfg["trial_count"]
    if result.complete:
        hits, cr = Decimal(counts["hits"]), Decimal(counts["correct_rejections"])
        targets = Decimal(cfg["target_count"])
        distractors = Decimal(cfg["trial_count"] - cfg["target_count"])
        result.score = q3(Decimal(100) * Decimal("0.5") * (hits / targets + cr / distractors))
        if counts["hits"] + counts["false_alarms"] == 0:
            result.flag("NO_RESPONSES")
        if counts["misses"] + counts["correct_rejections"] == 0:
            result.flag("ALL_RESPONSES")
    elif a.completion == "COMPLETED":
        result.flag("NOT_ALL_TRIALS_PRESENTED")
    else:
        result.flag("TASK_NOT_COMPLETED")

    window = None
    if a.trials:
        last = a.trials[-1]
        window = (a.trials[0].onset_ms, last.gap_end_ms or last.offset_ms or last.onset_ms)
    _apply_common_flags(result, "attention", window, sub, input_mode)
    result.counters = {**counts, "trials_presented": len(a.trials)}
    result.components["trials"] = per_trial
    return result


# --- reaction time ------------------------------------------------------------------------------


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def classify_latency(latency_ms: Decimal, minimum_ms: int, window_ms: int) -> str:
    if latency_ms < minimum_ms:
        return "ANTICIPATORY"
    if latency_ms >= window_ms:
        return "TIMEOUT"
    return "USABLE"


def score_reaction(protocol: dict[str, Any], sub: AssessmentSubmission, input_mode: str) -> TaskResult:
    cfg = protocol["reaction"]
    rx = sub.reaction
    expected = cfg["trials"]
    _check_ids([t.trial_id for t in rx.trials], [t["id"] for t in expected], "reaction")

    minimum, window = cfg["minimum_response_ms"], cfg["response_window_ms"]
    result = TaskResult(completion=rx.completion, complete=False, score=None)
    usable: list[Decimal] = []
    counts = {
        "usable": 0,
        "false_starts": 0,
        "anticipatory": 0,
        "timeouts": 0,
        "interrupted": 0,
        "aborted": 0,
    }
    per_trial = []

    for trial, spec in zip(rx.trials, expected, strict=False):
        responses = sorted(d(r.offset_ms) for r in trial.responses)
        latency: Decimal | None = None
        if trial.interrupted:
            outcome = "INTERRUPTED"
        elif trial.go_onset_ms is None:
            outcome = "FALSE_START" if responses else "ABORTED"
        else:
            go = d(trial.go_onset_ms)
            before_go = [r for r in responses if r < go]
            after_go = [r for r in responses if r >= go]
            if before_go:
                outcome = "FALSE_START"
            elif after_go:
                latency = after_go[0] - go
                outcome = classify_latency(latency, minimum, window)
            elif d(trial.end_ms) - go >= window - cfg["foreperiod_tolerance_ms"]:
                outcome = "TIMEOUT"
            else:
                outcome = "ABORTED"
            realized_foreperiod = trial.go_onset_ms - trial.wait_start_ms
            if abs(realized_foreperiod - spec["foreperiod_ms"]) > cfg["foreperiod_tolerance_ms"]:
                result.flag("TIMER_INTERRUPTION")

        key = {
            "USABLE": "usable",
            "FALSE_START": "false_starts",
            "ANTICIPATORY": "anticipatory",
            "TIMEOUT": "timeouts",
            "INTERRUPTED": "interrupted",
            "ABORTED": "aborted",
        }[outcome]
        counts[key] += 1
        if outcome == "USABLE" and latency is not None:
            usable.append(latency)
        client_view = {"RESPONSE": ("USABLE", "ANTICIPATORY", "TIMEOUT")}.get(
            trial.end_reason, (trial.end_reason,)
        )
        if outcome != "ABORTED" and outcome not in client_view:
            result.flag("CLIENT_OUTCOME_MISMATCH")
        per_trial.append(
            {
                "id": trial.trial_id,
                "outcome": outcome,
                "latency_ms": str(latency) if latency is not None else None,
                "max_frame_gap_ms": trial.max_frame_gap_ms,  # evidence only; TIMING_GAP interruptions flag
            }
        )

    if counts["interrupted"]:
        result.flag("TRIAL_INTERRUPTED")
    if any(t.event_overflow for t in rx.trials):
        result.flag("RESPONSE_OVERFLOW")

    result.complete = (
        rx.completion == "COMPLETED" and len(rx.trials) == cfg["trial_count"] and not counts["aborted"]
    )
    if result.complete:
        if counts["timeouts"]:
            result.flag("RT_TIMEOUT_PRESENT")
        if counts["false_starts"]:
            result.flag("FALSE_START_PRESENT")
        if counts["anticipatory"]:
            result.flag("ANTICIPATORY_PRESENT")
        if len(usable) >= cfg["minimum_usable_trials"]:
            result.score = q3(_median(usable))
        else:
            result.flag("INSUFFICIENT_USABLE_TRIALS")
    elif rx.completion == "COMPLETED":
        result.flag("NOT_ALL_TRIALS_PRESENTED")
    else:
        result.flag("TASK_NOT_COMPLETED")

    window_span = None
    if rx.trials:
        window_span = (rx.trials[0].wait_start_ms, rx.trials[-1].end_ms)
    _apply_common_flags(result, "reaction", window_span, sub, input_mode)
    result.counters = {**counts, "trials_presented": len(rx.trials)}
    result.components["trials"] = per_trial
    return result


# --- overall ------------------------------------------------------------------------------------


def score_submission(protocol: dict[str, Any], sub: AssessmentSubmission, input_mode: str) -> ScoringResult:
    """Score all three tasks against the frozen protocol and derive overall quality (§11 priority)."""
    memory = score_memory(protocol, sub, input_mode)
    attention = score_attention(protocol, sub, input_mode)
    reaction = score_reaction(protocol, sub, input_mode)
    tasks = {"memory": memory, "attention": attention, "reaction": reaction}

    statuses = [t.status for t in tasks.values()]
    if Quality.INCOMPLETE in statuses:
        quality, reasons = Quality.INCOMPLETE, ["INCOMPLETE_ASSESSMENT"]
    elif Quality.LOW in statuses:
        quality, reasons = Quality.LOW, ["LOW_QUALITY"]
    else:
        quality, reasons = Quality.VALID, []

    practice_warnings = ["PRACTICE_REPEATED"] if sub.practice.repeats else []
    telemetry_warnings = ["BLUR_OBSERVED"] if sub.telemetry.blur_count else []
    details = {
        "version": SCORING_DETAILS_VERSION,
        "scoring_version": protocol["scoring_version"],
        "overall": quality.value,
        "tasks": {name: t.as_details() for name, t in tasks.items()},
        "practice": {**sub.practice.model_dump(), "warnings": practice_warnings},
        "score_components": {name: t.components for name, t in tasks.items()},
        "input_mode": sub.telemetry.initial_input_mode.value,
        "final_input_mode": sub.telemetry.final_input_mode.value,
        "telemetry_warnings": telemetry_warnings,
        "assistance": sub.telemetry.assistance.model_dump(),
    }
    return ScoringResult(memory, attention, reaction, quality, reasons, details)
