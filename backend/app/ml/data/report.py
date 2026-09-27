"""Honest data report (guide 03 §15): coverage, distributions, events, exclusions, shortcuts.

"Not analyzed" is never counted as a negative: events whose target window is unusable are
reported as hidden, with the reason, and stay in the denominator.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from app.ml.data import exports
from app.ml.data.config import PARTITIONS, config_from_dict
from app.ml.data.pipeline import load_manifest

CONTEXT_FIELDS = ("sleep_hours", "mood_score", "medication_change")


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    q = np.percentile(values, [5, 25, 50, 75, 95])
    return {f"p{p}": round(float(v), 3) for p, v in zip((5, 25, 50, 75, 95), q, strict=True)}


def _rate(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 4)


def build_report(dataset_id: str, root: Path | None = None) -> dict[str, Any]:
    path, manifest = load_manifest(dataset_id, root)
    config = config_from_dict(manifest["config"])
    patients = list(exports.read_jsonl(path / "patients.jsonl"))
    part_of = {p["patient_id"]: p["partition"] for p in patients}
    observations = list(exports.read_jsonl(path / "observations.jsonl"))
    truth = list(exports.read_jsonl(path / "truth.jsonl"))
    prepared = manifest["stages"].get("prepare", {}).get("status") == "COMPLETE"
    windows = [w for p in PARTITIONS for w in exports.read_jsonl(path / f"windows/{p}.jsonl")] if prepared else []
    obs_by_id = {o["observation_id"]: o for o in observations}
    S = config.slots_per_patient

    by_partition: dict[str, Any] = {}
    for part in PARTITIONS:
        obs = [o for o in observations if part_of[o["patient_id"]] == part]
        n_pat = sum(1 for p in patients if p["partition"] == part)
        slots_with_session = {(o["patient_id"], o["slot_index"]) for o in obs}
        wins = [w for w in windows if w["partition"] == part and w["kind"] == "slot"]
        by_partition[part] = {
            "patients": n_pat,
            "planned_slots": n_pat * S,
            "slots_with_session": len(slots_with_session),
            "missing_slots": n_pat * S - len(slots_with_session),
            "submitted_records": len(obs),
            "purposes": dict(Counter(o["schedule_purpose"] for o in obs)),
            "quality": dict(Counter(o["quality"] for o in obs)),
            "missing_context": {f: sum(1 for o in obs if o[f] is None) for f in CONTEXT_FIELDS},
            "windows": len(wins),
            "supervised_windows": sum(w["supervised"] for w in wins),
            "supervised_clean_windows": sum(w["supervised"] and w["clean"] for w in wins),
            "excluded_by_clean_rule": sum(w["supervised"] and not w["clean"] for w in wins),
            "exclusion_reasons": dict(Counter(w["exclusion_reason"] for w in wins if w["exclusion_reason"])),
            "attempt_records": dict(Counter(w["exclusion_reason"] for w in windows if w["partition"] == part and w["kind"] == "attempt")),
        }

    mem_counts = Counter(round(o["memory_score"] * 6 / 100) for o in observations if o["memory_score"] is not None)
    att = [o["task_status"]["attention"]["counters"] for o in observations if o["attention_score"] is not None]
    rts = [o["reaction_time_ms"] for o in observations if o["reaction_time_ms"] is not None]
    n_mem = sum(mem_counts.values())
    distributions = {
        "memory_correct_count": {str(k): mem_counts.get(k, 0) for k in range(7)},
        "memory_floor_rate": _rate(mem_counts.get(0, 0), n_mem),
        "memory_ceiling_rate": _rate(mem_counts.get(6, 0), n_mem),
        "attention_hits": dict(sorted(Counter(a["hits"] for a in att).items())),
        "attention_false_alarms": dict(sorted(Counter(a["false_alarms"] for a in att).items())),
        "attention_ceiling_rate": _rate(sum(1 for o in observations if o["attention_score"] == 100.0), len(att)),
        "attention_at_or_below_50_rate": _rate(sum(1 for o in observations if o["attention_score"] is not None and o["attention_score"] <= 50), len(att)),
        "reaction_median_ms": _quantiles(rts),
        "sessions_with_rt_timeout": sum(1 for o in observations if o["task_status"]["reaction"]["counters"].get("timeouts", 0)),
        "reaction_null": sum(1 for o in observations if o["reaction_time_ms"] is None),
        "reason_flags": dict(Counter(f for o in observations for f in o["reason_flags"]).most_common()),
    }

    patient_truth = [t for t in truth if t["kind"] == "patient"]
    events = [t for t in patient_truth if t["event"]]
    perf_events = [t for t in events if t["event"]["is_performance_event"]]
    win_by_slot = {(w["patient_id"], w["target_slot"]): w for w in windows if w["kind"] == "slot"}
    event_targets = analyzable = 0
    hidden: Counter[str] = Counter()
    events_with_any_analyzable = 0
    for t in perf_events:
        e = t["event"]
        any_ok = False
        for s in range(e["event_start_slot"], e["event_start_slot"] + e["event_duration"]):
            event_targets += 1
            w = win_by_slot.get((t["patient_id"], s))
            if w and w["supervised"]:
                analyzable += 1
                any_ok = True
            else:
                hidden[w["exclusion_reason"] if w else "NO_WINDOW"] += 1
        events_with_any_analyzable += any_ok
    events_report = {
        "scenario_mix": dict(Counter(t["scenario"] for t in patient_truth)),
        "trajectory_mix": dict(Counter(t["trajectory"] for t in patient_truth)),
        "event_start_slots": dict(sorted(Counter(t["event"]["event_start_slot"] for t in events).items())),
        "performance_events": len(perf_events),
        "context_only_events": sum(1 for t in events if not t["event"]["is_performance_event"]),
        "performance_event_target_slots": event_targets,
        "analyzable_event_target_slots": analyzable,
        "hidden_event_target_slots_by_reason": dict(hidden),
        "events_with_at_least_one_analyzable_target": events_with_any_analyzable,
        "note": "Hidden = the target could not be analyzed (missing/LOW/INCOMPLETE/history). Never a true negative.",
    }

    # Label-shortcut probes: event activity must not be (near-)determined by simple fields.
    obs_truth = {t["observation_id"]: t for t in truth if t["kind"] == "observation"}
    min_support = 30  # below this, a 0 or 1 rate is noise rather than a shortcut

    def p_event(rows: list[dict[str, Any]]) -> dict[str, Any]:
        rate = _rate(sum(obs_truth[o["observation_id"]]["performance_event_active"] for o in rows), len(rows))
        return {"rate": rate, "n": len(rows), "evaluated": len(rows) >= min_support}
    missing_any = [o for o in observations if o["missing_context"]]
    med_yes = [o for o in observations if o["medication_change"] == "YES"]
    low = [o for o in observations if o["quality"] != "VALID"]
    probes = {
        "p_event_overall": p_event(observations),
        "p_event_given_context_missing": p_event(missing_any),
        "p_event_given_medication_yes": p_event(med_yes),
        "p_event_given_not_valid": p_event(low),
        "distinct_event_start_slots": len({t["event"]["event_start_slot"] for t in events}),
    }
    probes["no_deterministic_shortcut"] = all(
        0 < v["rate"] < 1 for k, v in probes.items() if k.startswith("p_event_given") and v["evaluated"]
    ) and probes["distinct_event_start_slots"] > 1
    probes["rule"] = f"conditional event rates with n >= {min_support} must lie strictly between 0 and 1"

    imputation = None
    if prepared:
        params = exports.read_json(path / "preprocessing.json")
        train_clean = [w for w in windows if w["partition"] == "train" and w["supervised"] and w["clean"] and w["kind"] == "slot"]
        rows = [obs_by_id[i] for w in train_clean for i in w["input_observation_ids"]]
        imputation = {
            "train_clean_input_rows": len(rows),
            "sleep_imputed_rate": _rate(sum(o["sleep_hours"] is None for o in rows), len(rows)),
            "mood_imputed_rate": _rate(sum(o["mood_score"] is None for o in rows), len(rows)),
            "medication_masked_rate": _rate(sum(o["medication_change"] not in ("YES", "NO") for o in rows), len(rows)),
            "fit_population": params["fit_population"],
        }

    fixture_obs = list(exports.read_jsonl(path / "fixtures/observations.jsonl"))
    fixture_truth = {t["patient_id"]: t for t in exports.read_jsonl(path / "fixtures/truth.jsonl") if t["kind"] == "patient"}
    fixture_windows = list(exports.read_jsonl(path / "windows/fixtures.jsonl")) if prepared else []
    fixtures: dict[str, Any] = defaultdict(dict)
    for pid, t in sorted(fixture_truth.items(), key=lambda kv: kv[1]["scenario"]):
        reasons = Counter(w["exclusion_reason"] or "SUPERVISED" for w in fixture_windows if w["patient_id"] == pid)
        fixtures[t["scenario"]] = {
            "sessions": sum(1 for o in fixture_obs if o["patient_id"] == pid),
            "quality": dict(Counter(o["quality"] for o in fixture_obs if o["patient_id"] == pid)),
            "window_outcomes": dict(reasons),
        }

    return {
        "dataset_id": dataset_id,
        "synthetic_notice": "Fictional synthetic data under chosen assumptions. Demonstrates software behaviour; "
        "not clinical validity, progression rates, causes, or real-world alert accuracy.",
        "profile": config.profile,
        "smoke_profile": config.profile.endswith("smoke"),
        "versions": manifest["versions"],
        "counts": manifest["counts"],
        "view_counts": manifest["stages"].get("prepare", {}).get("view_counts"),
        "by_partition": by_partition,
        "distributions": distributions,
        "events": events_report,
        "label_shortcut_probes": probes,
        "context_imputation": imputation,
        "fixtures": dict(fixtures),
    }


def render_markdown(r: dict[str, Any]) -> str:
    lines = [f"# Data report — `{r['dataset_id']}` ({r['profile']})", "", f"> {r['synthetic_notice']}", ""]
    if r["smoke_profile"]:
        lines += ["> **Smoke profile:** checks pipeline mechanics only. Do not report its metrics as an evaluation.", ""]
    lines += ["## Coverage by partition", "", "| Partition | Patients | Planned slots | Records | VALID | LOW | INCOMPLETE | Supervised windows | Clean |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for part, p in r["by_partition"].items():
        q = p["quality"]
        lines.append(f"| {part} | {p['patients']} | {p['planned_slots']} | {p['submitted_records']} | {q.get('VALID', 0)} | "
                     f"{q.get('LOW', 0)} | {q.get('INCOMPLETE', 0)} | {p['supervised_windows']} | {p['supervised_clean_windows']} |")
    reasons: Counter[str] = Counter()
    for p in r["by_partition"].values():
        reasons.update(p["exclusion_reasons"])
    lines += ["", "## Window exclusions (all partitions)", ""] + [f"- {k}: {v}" for k, v in reasons.most_common()]
    d = r["distributions"]
    lines += ["", "## Score distributions", "",
              f"- Memory correct count (0–6): {d['memory_correct_count']} — floor {d['memory_floor_rate']}, ceiling {d['memory_ceiling_rate']}",
              f"- Attention ceiling (100) rate {d['attention_ceiling_rate']}; ≤50 rate {d['attention_at_or_below_50_rate']}",
              f"- RT median quantiles (ms): {d['reaction_median_ms']}; sessions with a timeout: {d['sessions_with_rt_timeout']}; RT null: {d['reaction_null']}"]
    e = r["events"]
    lines += ["", "## Injected events (evaluation truth only)", "",
              f"- Scenario mix: {e['scenario_mix']}",
              f"- Performance events: {e['performance_events']}; event target slots: {e['performance_event_target_slots']}; "
              f"analyzable: {e['analyzable_event_target_slots']}; hidden: {e['hidden_event_target_slots_by_reason']}",
              f"- {e['note']}"]
    lines += ["", "## Label-shortcut probes", "", f"- {r['label_shortcut_probes']}"]
    if r["context_imputation"]:
        lines += ["", "## Context imputation (train_clean inputs)", "", f"- {r['context_imputation']}"]
    lines += ["", "## Fixture catalog outcomes", ""] + [f"- **{k}**: {v}" for k, v in r["fixtures"].items()]
    lines += ["", "## Limitations", "",
              "- Memory has six items: observed scores are heavily quantized and noisy even when the latent trajectory is smooth.",
              "- An injected event may produce no observable change; a large forecast error can occur without an event.",
              "- Clean-window training selection uses synthetic truth; real deployments will not have such labels.",
              "- Severe slowdowns can produce RT timeouts → LOW quality → unanalyzable, not an alert (kept in denominators).", ""]
    return "\n".join(lines)


def write_report(dataset_id: str, root: Path | None = None) -> Path:
    path, _ = load_manifest(dataset_id, root)
    report = build_report(dataset_id, root)
    exports.write_json(path / "data_report.json", report)
    (path / "data_report.md").write_text(render_markdown(report))
    return path
