"""Deterministic, template-based explanations (guide 04 §15). No generative model.

Every number in the summary is copied from the structured facts, which are built only from the
stored forecast (history snapshot), the current assessment/context, and the policy.
"""

from statistics import fmean
from typing import Any

from app.ml.models.anomaly import Evaluation, PolicyRules

EXPLANATION_VERSION = "explanation_template_v1"
_LABEL = {"memory": "Memory", "attention": "Attention", "reaction_time_ms": "Reaction time"}
_CONTEXT_USING_KINDS = {"GRU"}
_MEDICATION = {"YES": "yes", "NO": "no"}


def _num(x: float, digits: int = 1) -> str:
    """Display only (facts keep full precision): up to `digits` decimals, trailing zeros trimmed."""
    return f"{x:.{digits}f}".rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-9 else str(int(round(x)))


def _domain_sentence(d: str, dev: dict[str, Any], r: float) -> str | None:
    diff = dev["worsening"]
    if abs(diff) < 1e-9:
        return None
    if d == "reaction_time_ms":
        direction = "slower" if diff > 0 else "faster"
        text = f"{_LABEL[d]} was {_num(abs(diff))} ms {direction} than the stored forecast"
    else:
        direction = "below" if diff > 0 else "above"
        text = f"{_LABEL[d]} was {_num(abs(diff))} points {direction} the stored forecast"
    if diff < 0:
        return text + " (better than expected; not counted toward a decline signal)."
    if dev["z"] >= r:
        return text + f", exceeding this prototype's review threshold (deviation {dev['z']:.2f} vs {r:.2f})."
    return text + f" (deviation {dev['z']:.2f}; review threshold {r:.2f})."


def context_comparison(current: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    """Current sleep/mood/medication vs the six frozen history observations (known values only)."""
    out: dict[str, Any] = {}
    for field in ("sleep_hours", "mood_score"):
        known = [float(h[field]) for h in history if h.get(field) is not None]
        cur = current.get(field)
        out[field] = {
            "current": float(cur) if cur is not None else None,
            "history_known_count": len(known),
            "history_mean": round(fmean(known), 3) if known else None,
            "comparison_available": cur is not None and bool(known),
        }
    med = current.get("medication_change")
    out["medication_change"] = {
        "current": med,
        "reported": _MEDICATION.get(med or "", "unknown"),
        "history_yes_count": sum(1 for h in history if h.get("medication_change") == "YES"),
        "history_known_count": sum(1 for h in history if h.get("medication_change") in ("YES", "NO")),
    }
    return out


def _context_sentences(ctx: dict[str, Any]) -> list[str]:
    lines = []
    s, m, med = ctx["sleep_hours"], ctx["mood_score"], ctx["medication_change"]
    if s["current"] is None:
        lines.append("Sleep was not reported this time.")
    elif s["comparison_available"]:
        lines.append(
            f"Sleep was reported as {_num(s['current'], 2)} hours; the prior six observations with "
            f"known sleep ({s['history_known_count']}) averaged {_num(s['history_mean'], 2)} hours."
        )
    else:
        lines.append(
            f"Sleep was reported as {_num(s['current'], 2)} hours; no earlier sleep reports to compare."
        )
    if m["current"] is None:
        lines.append("Mood was not reported this time.")
    elif m["comparison_available"]:
        lines.append(
            f"Mood was reported as {_num(m['current'], 2)}/10; the prior six observations with known mood "
            f"({m['history_known_count']}) averaged {_num(m['history_mean'], 2)}."
        )
    else:
        lines.append(f"Mood was reported as {_num(m['current'], 2)}/10; no earlier mood reports to compare.")
    lines.append(f"Medication change reported: {med['reported']}.")
    return lines


def _level_sentence(ev: Evaluation) -> str:
    if ev.level == "NORMAL":
        return "No configured prototype deviation was detected for this check-in."
    streak = (
        "This is the first qualifying deviation in the current sequence."
        if ev.persistent_count == 1
        else f"This is qualifying deviation {ev.persistent_count} in consecutive weekly check-ins."
    )
    if ev.level == "HIGH_DEVIATION":
        return "This met the prototype's high-deviation rule. " + streak
    if ev.level == "PERSISTENT_DEVIATION":
        return "The deviation has repeated in consecutive weeks. " + streak
    return streak


def build_explanation(
    *,
    evaluation: Evaluation,
    rules: PolicyRules,
    model_kind: str,
    model_version: str,
    policy_version: str,
    protocol_version: str,
    scoring_version: str,
    quality: str,
    comparability_key: str,
    history: list[dict[str, Any]],
    current_context: dict[str, Any],
) -> dict[str, Any]:
    domains = evaluation.domain_json()
    ctx = context_comparison(current_context, history)
    dated = [h["observed_at"] for h in history if h.get("observed_at")]
    facts = {
        "level": evaluation.level,
        "domains": domains,
        "max_deviation": evaluation.max_deviation,
        "aggregate_deviation": evaluation.aggregate_deviation,
        "aggregate_method": rules.aggregate_method,
        "threshold_r": rules.r,
        "conditions_met": evaluation.conditions_met,
        "domains_at_or_above_r": evaluation.domains_at_or_above_r,
        "signal": "high"
        if evaluation.high_signal
        else ("moderate" if evaluation.moderate_signal else "none"),
        "persistent_count": evaluation.persistent_count,
        "pattern": "none"
        if not evaluation.moderate_signal
        else ("isolated" if evaluation.persistent_count == 1 else "persistent"),
        "history_range": {
            "first_observed_at": min(dated) if dated else None,
            "last_observed_at": max(dated) if dated else None,
            "observations": len(history),
        },
        "quality": quality,
        "comparability_key": comparability_key,
        "model": {
            "kind": model_kind,
            "version": model_version,
            "uses_context": model_kind in _CONTEXT_USING_KINDS,
        },
        "policy_version": policy_version,
        "protocol_version": protocol_version,
        "scoring_version": scoring_version,
        "context": ctx,
    }
    sentences = [s for d in domains if (s := _domain_sentence(d, domains[d], rules.r))]
    if not sentences:
        sentences.append("All three results matched the stored forecast.")
    sentences.append(_level_sentence(evaluation))
    sentences += _context_sentences(ctx)
    caveats = [
        "Context reports are shown for review; they are not identified as a cause and do not cancel a flag.",
        "Deviation values are dimensionless ratios against calibrated synthetic forecast errors, "
        "not probabilities, diagnoses or clinical cutoffs.",
    ]
    if model_kind not in _CONTEXT_USING_KINDS:
        caveats.insert(
            0,
            f"The forecast model ({model_kind}) does not use sleep, mood or medication; "
            "context is shown as separate information.",
        )
    return {
        "version": EXPLANATION_VERSION,
        "summary": " ".join(sentences),
        "sentences": sentences,
        "caveats": caveats,
        "facts": facts,
    }
