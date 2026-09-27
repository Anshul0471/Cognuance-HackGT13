"""Pure forecasting/anomaly calculations (guide 04 §4, §5, §7, §10–§13, §15, §19)."""

import math

import numpy as np
import pytest
import torch

from app.ml.data.preprocessing import X_CHANNELS
from app.ml.models import baselines, calibration, gru
from app.ml.models.anomaly import PolicyError, PolicyRules, evaluate, evaluate_z
from app.ml.models.evaluation import ReplayRow, alert_metrics, replay
from app.ml.models.explanations import build_explanation, context_comparison
from app.ml.models.metrics import selection_metric
from app.ml.models.postprocessing import (
    RT_BOUNDS_MS,
    PredictionError,
    from_log_rt,
    from_raw_rt,
    from_standardized,
    round3,
    to_standardized,
)
from app.ml.models.runs import choose_candidate

FIXTURE_RULES = PolicyRules(scales={"memory": 10.0, "attention": 5.0, "reaction_time_ms": 50.0}, r=2.0)
STATS = {
    "memory_score": {"mean": 60.0, "scale": 20.0},
    "attention_score": {"mean": 80.0, "scale": 10.0},
    "log_reaction_time": {"mean": math.log(600.0), "scale": 0.2},
}


# --- GRU shape, schema and isolation --------------------------------------------------------------


def test_gru_shapes_and_rejections():
    torch.manual_seed(0)
    model = gru.CognitiveForecaster().eval()
    assert model(torch.zeros(4, 6, 9)).shape == (4, 3)
    for bad in (torch.zeros(4, 6, 8), torch.zeros(4, 5, 9), torch.zeros(6, 9)):
        with pytest.raises(ValueError, match=r"\[batch, 6, 9\]"):
            model(bad)
    config = gru.architecture_config()
    assert gru.build_model(config) is not None
    with pytest.raises(ValueError, match="feature schema"):
        gru.build_model({**config, "x_channels": list(reversed(X_CHANNELS))})
    with pytest.raises(ValueError, match="architecture"):
        gru.build_model({**config, "architecture_version": "other"})


def test_gru_has_no_state_carry_between_sequences():
    torch.manual_seed(1)
    model = gru.CognitiveForecaster().eval()
    x = torch.randn(5, 6, 9)
    with torch.inference_mode():
        batch = model(x)
        single = torch.cat([model(x[i : i + 1]) for i in range(5)])
        reversed_batch = model(x.flip(0)).flip(0)
    assert torch.allclose(batch, single, atol=1e-6)
    assert torch.allclose(batch, reversed_batch, atol=1e-6)


# --- baselines --------------------------------------------------------------------------------------


def test_baselines_match_hand_computed_fixtures():
    history = np.array([[40, 80, 500 * math.exp(0.1 * k)] for k in range(6)], dtype=np.float64)
    history[:, 0] = [40, 42, 44, 46, 48, 50]
    last = baselines.last_value(history)
    assert last.values() == (50.0, 80.0, round3(500 * math.exp(0.5)))
    trend = baselines.linear_trend(history)
    # memory slope 2 → 52; attention constant → 80; log-RT slope 0.1 → 500·e^0.6.
    assert trend.values() == (52.0, 80.0, round3(500 * math.exp(0.6)))
    assert trend.bounds == {}
    # hand OLS: slope = 15.5 / 17.5, prediction = 3.5 + slope · 3.5 = 6.6
    assert baselines.ols_next(np.array([1, 3, 2, 5, 4, 6])) == pytest.approx(6.6)


def test_trend_extrapolation_is_bounded_not_rewritten():
    history = np.array(
        [
            [100, 100, 400],
            [100, 100, 400],
            [100, 100, 400],
            [100, 100, 400],
            [100, 100, 400],
            [100, 100, 400],
        ],
        dtype=np.float64,
    )
    history[:, 0] = [50, 60, 70, 80, 90, 100]
    p = baselines.linear_trend(history)
    assert p.memory == 100.0 and p.bounds == {"memory": "upper"}


# --- postprocessing ---------------------------------------------------------------------------------


def test_postprocess_bounds_rounding_and_nonfinite():
    p = from_log_rt(120.0, -5.0, 50.0)  # exp(50) would overflow without the log clamp
    assert p.values() == (100.0, 0.0, RT_BOUNDS_MS[1])
    assert p.bounds == {"memory": "upper", "attention": "lower", "reaction_time_ms": "upper"}
    assert from_raw_rt(50, 50, 50.0).reaction_time_ms == 100.0
    assert round3(1.0005) == 1.001 and round3(2.0015) == 2.002  # decimal-string HALF_UP, not binary
    for bad in (float("nan"), float("inf")):
        with pytest.raises(PredictionError):
            from_log_rt(bad, 50, 6.0)
        with pytest.raises(PredictionError):
            from_standardized([0.0, bad, 0.0], STATS)


def test_standardized_round_trip_uses_target_stats():
    p = from_standardized([1.0, -1.0, 0.0], STATS)
    assert p.values() == (80.0, 70.0, 600.0)
    back = to_standardized(np.array([p.values()]), STATS)
    assert np.allclose(back, [[1.0, -1.0, 0.0]])


# --- metrics / selection ---------------------------------------------------------------------------


def test_selection_metric_is_patient_macro():
    stats = {k: {"mean": 0.0, "scale": 1.0} for k in ("memory_score", "attention_score")}
    stats["log_reaction_time"] = {"mean": 0.0, "scale": 1.0}
    y = np.array([[0, 0, 1.0]] * 4)
    pred = np.array([[3, 3, 1.0]] * 3 + [[9, 9, 1.0]])  # A: 3 windows err 2 avg, B: 1 window err 6 avg
    got = selection_metric(pred, y, ["A", "A", "A", "B"], stats)
    assert got == pytest.approx((2.0 + 6.0) / 2)  # not the window mean 3.0


def test_candidate_tie_rule_prefers_simpler():
    assert (
        choose_candidate({"LAST_VALUE": 0.905, "LINEAR_TREND": 0.95, "GRU": 0.9})["selected_kind"]
        == "LAST_VALUE"
    )
    assert choose_candidate({"LAST_VALUE": 1.0, "LINEAR_TREND": 0.95, "GRU": 0.9})["selected_kind"] == "GRU"
    assert (
        choose_candidate({"LAST_VALUE": 0.01, "LINEAR_TREND": 0.0, "GRU": 0.0})["selected_kind"]
        == "LINEAR_TREND"
    )


# --- section 13 boundary fixtures ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("z", "prior", "level", "count"),
    [
        ((0, 0, 0), 0, "NORMAL", 0),
        ((1.599, 1.599, 0), 0, "NORMAL", 0),
        ((1.6, 1.6, 0), 0, "REVIEW", 1),
        ((2, 0, 0), 0, "REVIEW", 1),
        ((2, 0, 0), 1, "PERSISTENT_DEVIATION", 2),
        ((2, 2, 0), 0, "HIGH_DEVIATION", 1),
        ((4, 0, 0), 0, "HIGH_DEVIATION", 1),
        ((0, 0, 0), 3, "NORMAL", 0),
        ((4, 0, 0), 2, "HIGH_DEVIATION", 3),  # HIGH outranks persistent; streak preserved
        ((0, 0, 1.6), 0, "NORMAL", 0),  # A = 0.8 < 1.6
    ],
)
def test_section_13_boundaries(z, prior, level, count):
    zd = dict(zip(("memory", "attention", "reaction_time_ms"), map(float, z), strict=True))
    _, _, _, _, got_count, got_level = evaluate_z(zd, FIXTURE_RULES, prior)
    assert (got_level, got_count) == (level, count)


def test_concrete_task_example_and_directionality():
    ev = evaluate((75.0, 85.0, 500.0), (50.0, 85.0, 500.0), FIXTURE_RULES, 0)
    assert ev.domains["memory"].z == 2.5 and ev.level == "REVIEW" and ev.persistent_count == 1
    assert ev.domains["memory"].residual == -25.0 and ev.domains["memory"].worsening == 25.0
    better = evaluate((75.0, 85.0, 500.0), (100.0, 100.0, 300.0), FIXTURE_RULES, 5)
    assert all(d.z == 0.0 for d in better.domains.values())
    assert better.level == "NORMAL" and better.persistent_count == 0
    assert better.domains["reaction_time_ms"].residual == -200.0  # recorded, not an alert
    slower = evaluate((75.0, 85.0, 500.0), (75.0, 85.0, 700.0), FIXTURE_RULES, 0)
    assert slower.domains["reaction_time_ms"].z == 4.0 and slower.level == "HIGH_DEVIATION"


@pytest.mark.parametrize(
    "scales",
    [
        {"memory": 0.0, "attention": 5.0, "reaction_time_ms": 50.0},
        {"memory": float("nan"), "attention": 5.0, "reaction_time_ms": 50.0},
        {"memory": -1.0, "attention": 5.0, "reaction_time_ms": 50.0},
        {"memory": 10.0, "attention": 5.0},
    ],
)
def test_malformed_policy_is_rejected(scales):
    with pytest.raises(PolicyError):
        PolicyRules(scales=scales, r=2.0)
    with pytest.raises(PolicyError):
        PolicyRules.from_configuration({"scales": {}, "rules": {}})


# --- calibration selection ------------------------------------------------------------------------


def _cand(r, clean, analyzable, detected, alerts):
    return {
        "r": r,
        "metrics": {
            "clean_target_alert_fraction": {"fraction": clean},
            "worsening_events": {
                "analyzable": analyzable,
                "detected": detected,
                "conditional_detection_fraction": detected / analyzable if analyzable else None,
            },
            "alerts": alerts,
        },
    }


def test_threshold_selection_rules():
    cands = [
        _cand(1.5, 0.10, 20, 18, 90),
        _cand(2.0, 0.05, 20, 12, 40),
        _cand(2.5, 0.02, 20, 12, 30),
        _cand(3.0, 0.01, 20, 8, 10),
    ]
    assert calibration.select_threshold(cands) == (2.5, "SELECTED")  # tie on detection → fewer alerts
    assert calibration.select_threshold([_cand(2.0, 0.01, 9, 5, 5)]) == (
        None,
        "INSUFFICIENT_WORSENING_EVENTS",
    )
    assert (
        calibration.select_threshold([_cand(2.0, 0.2, 20, 5, 5)])[1]
        == "NO_THRESHOLD_MEETS_CLEAN_ALERT_OBJECTIVE"
    )
    assert calibration.select_threshold([_cand(6.0, 0.0, 20, 0, 0)]) == (
        None,
        "ZERO_DETECTED_WORSENING_EVENTS",
    )


def test_scales_use_rmse_with_floor():
    pred = np.array([[50.0, 80.0, 500.0], [50.0, 80.0, 500.0]])
    y = np.array([[60.0, 80.0, 500.5], [40.0, 80.0, 499.5]])
    s = calibration.fit_scales(pred, y)
    assert s["memory"]["scale"] == pytest.approx(10.0) and not s["memory"]["floor_applied"]
    assert s["attention"]["scale"] == 1.0 and s["attention"]["floor_applied"]
    assert s["reaction_time_ms"]["raw_rmse"] == pytest.approx(0.5) and s["reaction_time_ms"]["scale"] == 1.0


# --- chronological replay / persistence -----------------------------------------------------------


def _w(pid, k, supervised=True, clean=True):
    return {
        "window_id": f"{pid}-{k}",
        "patient_id": pid,
        "target_slot": k,
        "supervised": supervised,
        "clean": clean,
        "forecast_eligible": supervised,
        "exclusion_reason": None if supervised else "HISTORY_GAP",
    }


def test_replay_persistence_resets_on_gap_and_normal():
    from app.ml.models.postprocessing import Prediction

    pred = Prediction(75.0, 85.0, 500.0)
    bad, ok = (50.0, 85.0, 500.0), (75.0, 85.0, 500.0)
    windows = [
        _w("p", 6),
        _w("p", 7),
        _w("p", 8, supervised=False),
        _w("p", 9),
        _w("p", 10),
        _w("p", 11),
        _w("p", 12),
    ]
    observed = {"p-6": bad, "p-7": bad, "p-9": bad, "p-10": bad, "p-11": ok, "p-12": bad}
    preds = {w["window_id"]: pred for w in windows if w["supervised"]}
    rows = replay(windows, preds, observed, FIXTURE_RULES)
    got = [(r.slot, r.evaluation.level, r.evaluation.persistent_count) for r in rows]
    assert got == [
        (6, "REVIEW", 1),
        (7, "PERSISTENT_DEVIATION", 2),
        (9, "REVIEW", 1),
        (10, "PERSISTENT_DEVIATION", 2),
        (11, "NORMAL", 0),
        (12, "REVIEW", 1),
    ]


def test_alert_metrics_keep_unanalyzed_events_in_denominators():
    from app.ml.models.postprocessing import Prediction

    windows = [_w("a", 8), _w("a", 9, clean=False), _w("b", 8, supervised=False), _w("c", 8)]
    truth = {
        "a": {
            "event": {
                "event_kind": "persistent_worsening",
                "event_start_slot": 9,
                "event_duration": 1,
                "event_id": "e1",
            }
        },
        "b": {
            "event": {
                "event_kind": "isolated_worsening",
                "event_start_slot": 8,
                "event_duration": 1,
                "event_id": "e2",
            }
        },
        "c": {"event": None},
    }
    preds = {w["window_id"]: Prediction(75.0, 85.0, 500.0) for w in windows if w["supervised"]}
    observed = {"a-8": (75.0, 85.0, 500.0), "a-9": (40.0, 85.0, 500.0), "c-8": (75.0, 85.0, 500.0)}
    rows = replay(windows, preds, observed, FIXTURE_RULES)
    assert all(isinstance(r, ReplayRow) for r in rows)
    m = alert_metrics(rows, windows, truth)
    w = m["worsening_events"]
    assert (w["total"], w["analyzable"], w["detected"]) == (2, 1, 1)
    assert w["all_event_detection_fraction"] == 0.5 and w["conditional_detection_fraction"] == 1.0
    assert m["not_analyzed_targets"] == 1
    assert m["point_level"]["precision"] == 1.0
    empty = alert_metrics([], windows, truth)
    assert empty["point_level"]["precision"] == "N/A (no alerts)"


# --- explanations -----------------------------------------------------------------------------------


def test_explanation_is_grounded_and_honest_about_context():
    ev = evaluate((75.0, 85.0, 500.0), (50.0, 85.0, 480.0), FIXTURE_RULES, 0)
    history = [
        {
            "observed_at": f"2026-01-{d:02d}T10:00:00+00:00",
            "sleep_hours": s,
            "mood_score": None,
            "medication_change": None,
        }
        for d, s in zip(range(1, 7), [7, 7, None, 7, 7, 7], strict=True)
    ]
    exp = build_explanation(
        evaluation=ev,
        rules=FIXTURE_RULES,
        model_kind="LINEAR_TREND",
        model_version="m1",
        policy_version="p1",
        protocol_version="cognitive_tasks_en_v1",
        scoring_version="cognitive_scoring_v1",
        quality="VALID",
        comparability_key="k",
        history=history,
        current_context={"sleep_hours": 5.0, "mood_score": 6, "medication_change": "NOT_SURE"},
    )
    s = exp["summary"]
    assert "Memory was 25 points below the stored forecast" in s
    assert "first qualifying deviation" in s
    assert "Reaction time was 20 ms faster" in s and "not counted toward a decline" in s
    assert (
        "Sleep was reported as 5 hours; the prior six observations with known sleep (5) averaged 7 hours."
        in s
    )
    assert "no earlier mood reports to compare" in s
    assert "Medication change reported: unknown." in s
    assert any("does not use sleep, mood or medication" in c for c in exp["caveats"])
    assert "cause" not in s.lower() and "%" not in s
    f = exp["facts"]
    assert f["domains"]["memory"]["z"] == 2.5 and f["threshold_r"] == 2.0 and f["pattern"] == "isolated"
    assert f["context"]["sleep_hours"]["history_known_count"] == 5
    ctx = context_comparison({"sleep_hours": None, "mood_score": None, "medication_change": None}, history)
    assert (
        ctx["sleep_hours"]["comparison_available"] is False
        and ctx["medication_change"]["reported"] == "unknown"
    )
