"""Weekly schedule `weekly_v1` and forecast-history eligibility (guide 02 §5). Pure functions.

Slot k has target_at = anchor_at + k·7 days; a scheduled session may start within ±12 h
(inclusive). A forecast needs representatives for the SEQUENCE_LENGTH (default 6) immediately
previous slots, all with an identical comparability key.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models import ForecastState

SCHEDULE_VERSION = "weekly_v1"
WEEK = timedelta(days=7)
WINDOW = timedelta(hours=12)


def target_for(anchor: datetime, slot: int) -> datetime:
    return anchor + slot * WEEK


def nearest_slot(anchor: datetime, now: datetime) -> tuple[int, datetime]:
    """Nearest canonical slot; ties go to the earlier target."""
    if now <= anchor:
        return 0, anchor
    k = (now - anchor) // WEEK
    earlier, later = target_for(anchor, k), target_for(anchor, k + 1)
    return (k, earlier) if now - earlier <= later - now else (k + 1, later)


def in_window(target: datetime, now: datetime) -> bool:
    return abs(now - target) <= WINDOW


def comparability_key(protocol_version: str, scoring_version: str, input_mode: str, epoch: int) -> str:
    return f"{protocol_version}|{scoring_version}|{input_mode}|{epoch}"


@dataclass(frozen=True)
class Representative:
    slot_index: int
    protocol_version: str
    scoring_version: str
    comparability_key: str


def evaluate_history(
    slot: int,
    reps: dict[int, Representative],
    current_key: str,
    protocol_version: str,
    scoring_version: str,
    history_slots: int,
) -> tuple[ForecastState, list[str]]:
    """Forecast availability from prior-slot representatives only (never the current slot)."""
    prior = {k: r for k, r in reps.items() if k < slot}
    if len(prior) < history_slots:
        return ForecastState.BUILDING_BASELINE, ["BUILDING_BASELINE"]
    window = [prior.get(k) for k in range(slot - history_slots, slot)]
    if any(r is None for r in window):
        return ForecastState.INSUFFICIENT_DATA, ["HISTORY_GAP"]
    if any(
        r.protocol_version != protocol_version or r.scoring_version != scoring_version for r in window if r
    ):
        return ForecastState.INSUFFICIENT_DATA, ["PROTOCOL_MISMATCH"]
    if any(r.comparability_key != current_key for r in window if r):
        return ForecastState.INSUFFICIENT_DATA, ["COMPARABILITY_CHANGE"]
    # History is sufficient; the forecast service turns this into READY + a stored forecast row
    # (services/forecasts.py), or keeps a sanitized model-unavailable reason.
    return ForecastState.MODEL_UNAVAILABLE, ["MODEL_NOT_CONFIGURED"]


@dataclass(frozen=True)
class SubmissionRef:
    """Minimal view of a stored submission for representative selection."""

    id: str
    slot_index: int
    schedule_purpose: str
    quality: str
    available_at: datetime


REPRESENTATIVE_PURPOSE_VALUES = ("SCHEDULED", "RETAKE_AFTER_UNRELIABLE")


def select_representatives(submissions: list[SubmissionRef]) -> dict[int, str]:
    """Slot → id of its representative: the first quality-VALID SCHEDULED/RETAKE submission ordered by
    (available_at, id). Never the highest score. The live app enforces the same rule incrementally
    under a patient lock (`longitudinal_eligible` + a partial unique index)."""
    reps: dict[int, str] = {}
    for sub in sorted(submissions, key=lambda s: (s.available_at, s.id)):
        if sub.quality == "VALID" and sub.schedule_purpose in REPRESENTATIVE_PURPOSE_VALUES:
            reps.setdefault(sub.slot_index, sub.id)
    return reps
