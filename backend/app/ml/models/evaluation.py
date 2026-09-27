"""Chronological replay of the anomaly rules and honest alert metrics (guide 04 §12, §17).

The forecaster/detector never sees truth. Truth (injected events) is joined here, offline, only to
score what the replay produced. Unanalyzed targets are reported, never counted as negatives.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

from app.ml.models.anomaly import Evaluation, PolicyRules, evaluate
from app.ml.models.postprocessing import Prediction

WORSENING_KINDS = ("isolated_worsening", "persistent_worsening", "single_domain_worsening")


@dataclass
class ReplayRow:
    window_id: str
    patient_id: str
    slot: int
    clean: bool
    evaluation: Evaluation

    @property
    def alert(self) -> bool:
        return self.evaluation.level != "NORMAL"


def replay(
    slot_windows: list[dict[str, Any]],
    predictions: dict[str, Prediction],
    observed: dict[str, tuple[float, float, float]],
    rules: PolicyRules,
) -> list[ReplayRow]:
    """Process each patient's weekly slots in order. Any slot without an analysis breaks the streak."""
    by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for w in slot_windows:
        by_patient[w["patient_id"]].append(w)
    rows: list[ReplayRow] = []
    for pid in sorted(by_patient):
        prior, prev_slot = 0, None
        for w in sorted(by_patient[pid], key=lambda x: x["target_slot"]):
            k = w["target_slot"]
            pred = predictions.get(w["window_id"])
            if pred is None:
                prior, prev_slot = 0, None
                continue
            effective = prior if prev_slot == k - 1 else 0
            ev = evaluate(pred.values(), observed[w["window_id"]], rules, effective)
            rows.append(ReplayRow(w["window_id"], pid, k, bool(w["clean"]), ev))
            prior, prev_slot = (ev.persistent_count if ev.moderate_signal else 0), k
    return rows


def _frac(n: int, d: int) -> float | None:
    return round(n / d, 6) if d else None


def _rate(n: int, d: int) -> dict[str, Any]:
    return {"count": n, "n": d, "fraction": _frac(n, d)}


def alert_metrics(
    rows: list[ReplayRow], slot_windows: list[dict[str, Any]], truth: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    patients = sorted({w["patient_id"] for w in slot_windows})
    intervals: dict[str, tuple[str, set[int], str]] = {}
    for pid in patients:
        e = (truth.get(pid) or {}).get("event")
        if e:
            slots = set(range(e["event_start_slot"], e["event_start_slot"] + e["event_duration"]))
            intervals[pid] = (e["event_kind"], slots, e["event_id"])

    def kind_at(row: ReplayRow) -> str | None:
        iv = intervals.get(row.patient_id)
        return iv[0] if iv and row.slot in iv[1] else None

    alerts = [r for r in rows if r.alert]
    clean = [r for r in rows if r.clean]
    no_event = [r for r in rows if kind_at(r) is None]
    by_kind: dict[str, list[ReplayRow]] = defaultdict(list)
    for r in rows:
        if (k := kind_at(r)) is not None:
            by_kind[k].append(r)

    # Event-level detection within the annotated interval only.
    rows_by_patient: dict[str, list[ReplayRow]] = defaultdict(list)
    for r in rows:
        rows_by_patient[r.patient_id].append(r)
    events_total = analyzable = detected = 0
    time_to_first: list[int] = []
    per_kind_detection: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "analyzable": 0, "detected": 0}
    )
    for pid, (kind, slots, _eid) in intervals.items():
        if kind not in WORSENING_KINDS:
            continue
        events_total += 1
        per_kind_detection[kind]["events"] += 1
        inside = sorted((r for r in rows_by_patient.get(pid, []) if r.slot in slots), key=lambda r: r.slot)
        if not inside:
            continue
        analyzable += 1
        per_kind_detection[kind]["analyzable"] += 1
        hits = [r for r in inside if r.alert]
        if hits:
            detected += 1
            per_kind_detection[kind]["detected"] += 1
            time_to_first.append(hits[0].slot - min(slots))

    positives = [r for r in rows if kind_at(r) in WORSENING_KINDS]
    tp = sum(1 for r in positives if r.alert)
    category_counts = Counter(r.evaluation.level for r in rows)
    alerts_per_patient = Counter(r.patient_id for r in alerts)
    return {
        "patients": len(patients),
        "slot_records": len(slot_windows),
        "analyzed_targets": len(rows),
        "not_analyzed_targets": len(slot_windows) - len(rows),
        "alerts": len(alerts),
        "category_counts": {
            k: category_counts.get(k, 0)
            for k in ("NORMAL", "REVIEW", "PERSISTENT_DEVIATION", "HIGH_DEVIATION")
        },
        "clean_target_alert_fraction": _rate(sum(r.alert for r in clean), len(clean)),
        "no_event_alert_fraction": _rate(sum(r.alert for r in no_event), len(no_event)),
        "context_only_interval_alert_fraction": _rate(
            sum(r.alert for r in by_kind.get("context_only_change", [])),
            len(by_kind.get("context_only_change", [])),
        ),
        "improvement_interval_alert_fraction": _rate(
            sum(r.alert for r in by_kind.get("improvement", [])), len(by_kind.get("improvement", []))
        ),
        "worsening_events": {
            "total": events_total,
            "analyzable": analyzable,
            "detected": detected,
            "conditional_detection_fraction": _frac(detected, analyzable),
            "all_event_detection_fraction": _frac(detected, events_total),
            "analyzable_coverage_fraction": _frac(analyzable, events_total),
            "by_kind": dict(per_kind_detection),
            "time_to_first_alert_slots": {
                "n": len(time_to_first),
                "median": median(time_to_first) if time_to_first else None,
                "distribution": dict(sorted(Counter(time_to_first).items())),
            },
        },
        "point_level": {
            "positive_targets": len(positives),
            "true_positive_alerts": tp,
            "precision": _frac(tp, len(alerts)) if alerts else "N/A (no alerts)",
            "recall": _frac(tp, len(positives)) if positives else "N/A (no positive targets)",
        },
        "alert_burden": {
            "alerts_per_analyzed_target": _frac(len(alerts), len(rows)),
            "patients_with_alert": len(alerts_per_patient),
            "max_alerts_one_patient": max(alerts_per_patient.values(), default=0),
            "mean_alerts_per_patient": _frac(len(alerts), len(patients)),
        },
    }
