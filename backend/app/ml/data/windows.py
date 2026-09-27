"""Chronological forecast windows and eligibility records (guide 03 §10–§11).

One record per (patient, canonical target slot), even when no tensor sample can be built, so
coverage reports keep ineligible targets in their denominators. Inputs are the representatives of
exactly slots k-6..k-1 that were available by the simulated forecast cutoff (the target session's
start). Nothing about the target (context, responses, quality) is used to build inputs.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.ml.data.generator import make_id

# Guide 03 §10 exclusion reasons (+ MISSING_TARGET: no attempt at all in the target slot).
HISTORY_REASONS = (
    "BUILDING_BASELINE",
    "HISTORY_GAP",
    "LOW_QUALITY_INPUT",
    "LATE_AVAILABILITY",
    "PROTOCOL_MISMATCH",
    "COMPARABILITY_CHANGE",
)
TARGET_REASONS = ("MISSING_TARGET", "INCOMPLETE_TARGET", "LOW_QUALITY_TARGET", "OFF_SCHEDULE", "EXTRA_ATTEMPT")

# Mapped onto the application's existing availability enum (no new enum per reason).
AVAILABILITY = {"BUILDING_BASELINE": "BUILDING_BASELINE"}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def build_windows(
    observations: list[dict[str, Any]],
    partitions: dict[str, str],
    truth_performance_slots: dict[str, set[int]],
    slots: int,
    history_length: int,
    identity: str,
    preprocessing_version: str,
) -> list[dict[str, Any]]:
    by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        by_patient[obs["patient_id"]].append(obs)

    records: list[dict[str, Any]] = []
    for patient_id in sorted(by_patient):
        rows = sorted(by_patient[patient_id], key=lambda o: (_ts(o["available_at"]), o["observation_id"]))
        by_slot: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for o in rows:
            by_slot[o["slot_index"]].append(o)
        reps = {o["slot_index"]: o for o in rows if o["representative"]}
        event_slots = truth_performance_slots.get(patient_id, set())

        for k in range(slots):
            attempts = sorted(by_slot.get(k, []), key=lambda o: (o["attempt"], o["observation_id"]))
            first = attempts[0] if attempts else None
            cutoff = _ts(first["session_started_at"]) if first else None
            current_key = first["comparability_key"] if first else None
            target = reps.get(k)

            reasons: list[str] = []
            prior = [j for j in reps if j < k]
            window_slots = list(range(k - history_length, k))
            inputs: list[dict[str, Any]] = []
            if len(prior) < history_length:
                reasons.append("BUILDING_BASELINE")
            else:
                for j in window_slots:
                    rep = reps.get(j)
                    if rep is None:
                        reasons.append("LOW_QUALITY_INPUT" if by_slot.get(j) else "HISTORY_GAP")
                        continue
                    inputs.append(rep)
                    if cutoff is not None and _ts(rep["available_at"]) > cutoff:
                        reasons.append("LATE_AVAILABILITY")
                    if first is not None and (rep["protocol_version"], rep["scoring_version"]) != (
                        first["protocol_version"],
                        first["scoring_version"],
                    ):
                        reasons.append("PROTOCOL_MISMATCH")
                    if current_key is not None and rep["comparability_key"] != current_key:
                        reasons.append("COMPARABILITY_CHANGE")
            history_reasons = [r for r in HISTORY_REASONS if r in reasons]

            target_reasons: list[str] = []
            if first is None:
                target_reasons.append("MISSING_TARGET")
            elif target is None:
                qualities = {a["quality"] for a in attempts}
                target_reasons.append("LOW_QUALITY_TARGET" if "LOW" in qualities else "INCOMPLETE_TARGET")

            forecast_eligible = not history_reasons and first is not None
            supervised = forecast_eligible and target is not None
            exclusion = (history_reasons + target_reasons + [None])[0]
            window_touches_event = any(s in event_slots for s in [*window_slots, k] if s >= 0)
            records.append(
                {
                    "window_id": make_id(identity, "window", patient_id, k),
                    "kind": "slot",
                    "patient_id": patient_id,
                    "partition": partitions[patient_id],
                    "target_slot": k,
                    "target_observation_id": target["observation_id"] if target else None,
                    "input_observation_ids": [o["observation_id"] for o in inputs] if forecast_eligible else [],
                    "forecast_cutoff": cutoff.isoformat(timespec="milliseconds") if cutoff else None,
                    "forecast_eligible": forecast_eligible,
                    "supervised": supervised,
                    "exclusion_reason": exclusion,
                    "reasons": history_reasons + target_reasons,
                    # No model yet: a fully eligible window is MODEL_UNAVAILABLE, never "normal".
                    "availability_state": "MODEL_UNAVAILABLE"
                    if exclusion is None
                    else AVAILABILITY.get(exclusion, "INSUFFICIENT_DATA"),
                    # Offline experiment selection only (§11): never a serving feature.
                    "clean": not window_touches_event,
                    "target_event_active": k in event_slots,
                    "preprocessing_version": preprocessing_version,
                }
            )
            # Extra/off-schedule attempts never add weekly slots; record them for coverage.
            for a in attempts:
                if a["schedule_purpose"] in ("EXTRA_ATTEMPT", "OFF_SCHEDULE"):
                    records.append(
                        {
                            "window_id": make_id(identity, "window", patient_id, k, "attempt", a["attempt"]),
                            "kind": "attempt",
                            "patient_id": patient_id,
                            "partition": partitions[patient_id],
                            "target_slot": k,
                            "target_observation_id": a["observation_id"],
                            "input_observation_ids": [],
                            "forecast_cutoff": None,
                            "forecast_eligible": False,
                            "supervised": False,
                            "exclusion_reason": a["schedule_purpose"],
                            "reasons": [a["schedule_purpose"]],
                            "availability_state": "INSUFFICIENT_DATA",
                            "clean": False,
                            "target_event_active": k in event_slots,
                            "preprocessing_version": preprocessing_version,
                        }
                    )
    return records
