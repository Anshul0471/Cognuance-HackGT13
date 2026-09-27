"""Pure scoring fixtures from guide 02 §16. Engineering checks only; none establishes medical validity."""

import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models import Quality
from app.schemas.assessments import AssessmentSubmission
from app.services.protocol import WORD_LISTS, attention_sequence, build_task_protocol, word_set_for
from app.services.scoring import ScoringInputError, classify_latency, normalize_word, score_submission
from tests.factories import FALSE_START, TIMEOUT, build_payload


@pytest.fixture
def protocol():
    return build_task_protocol("A", random.Random(7))


def score(protocol, **kwargs):
    sub = AssessmentSubmission.model_validate(build_payload(protocol, **kwargs))
    return score_submission(protocol, sub, kwargs.get("input_mode", "keyboard"))


def attention_counts(protocol, hits, correct_rejections):
    """A press function producing exactly `hits` hits and `correct_rejections` correct rejections."""
    state = {"t": 0, "d": 0}

    def press(spec):
        if spec["is_target"]:
            state["t"] += 1
            return [400.0] if state["t"] <= hits else []
        state["d"] += 1
        return [] if state["d"] <= correct_rejections else [400.0]

    return press


# --- protocol -----------------------------------------------------------------------------------


def test_attention_sequence_is_balanced_and_bounded():
    for seed in range(200):
        trials, _ = attention_sequence(random.Random(seed))
        shapes = [t["shape"] for t in trials]
        assert (shapes.count("circle"), shapes.count("square"), shapes.count("triangle")) == (10, 10, 10)
        run = longest = 0
        for s in shapes:
            run = run + 1 if s == "circle" else 0
            longest = max(longest, run)
        assert longest <= 3


def test_word_rotation_and_practice_words_disjoint():
    assert [word_set_for(i) for i in range(5)] == ["A", "B", "C", "D", "A"]
    scored = {w for words in WORD_LISTS.values() for w in words}
    assert not scored & set(build_task_protocol("A", random.Random(1))["practice"]["memory_words"])


def test_reaction_foreperiods_are_integers_in_range(protocol):
    assert all(1500 <= t["foreperiod_ms"] <= 3500 for t in protocol["reaction"]["trials"])


# --- memory -------------------------------------------------------------------------------------


def test_memory_four_unique_correct_one_duplicate_one_wrong(protocol):
    r = score(protocol, memory_entries=["apple", "Chair", "river", "candle", "APPLE", "banana"])
    assert r.memory.score == Decimal("66.667")
    assert r.memory.counters == {"correct": 4, "incorrect": 1, "duplicates": 1}


def test_memory_six_normalized_exact_matches(protocol):
    r = score(protocol, memory_entries=["  Apple.", "CHAIR", "river!", "ｃａｎｄｌｅ", "garden", '"spoon"'])
    assert r.memory.score == Decimal("100.000")


def test_memory_no_fuzzy_or_synonym_credit(protocol):
    r = score(protocol, memory_entries=["apples", "chiar", "stream", "candle holder", "", ""])
    assert r.memory.score == Decimal("0.000")


def test_memory_completed_none_remembered_is_zero_and_valid(protocol):
    r = score(protocol, memory_entries=[])
    assert r.memory.score == Decimal("0.000")
    assert r.quality == Quality.VALID


def test_memory_skipped_recall_is_null_and_incomplete(protocol):
    r = score(protocol, memory_completion="SKIPPED")
    assert r.memory.score is None
    assert r.quality == Quality.INCOMPLETE


def test_memory_visibility_interruption_during_delay_is_low(protocol):
    r = score(protocol, visibility_events=[{"offset_ms": 30000.0, "state": "hidden"}])
    assert "INTERRUPTION" in r.memory.flags
    assert r.memory.score == Decimal("100.000")  # descriptive score kept
    assert r.quality == Quality.LOW


def test_memory_exposure_timing_deviation_is_low(protocol):
    r = score(protocol, exposure_ms=21500)
    assert "EXPOSURE_TIMING_DEVIATION" in r.memory.flags
    assert r.quality == Quality.LOW


def test_normalize_word_keeps_internal_characters():
    assert normalize_word("  Ice-cream!! ") == "ice-cream"
    assert normalize_word("...") == ""


# --- attention ----------------------------------------------------------------------------------


def test_attention_8_hits_16_correct_rejections(protocol):
    r = score(protocol, attention_press=attention_counts(protocol, 8, 16))
    assert r.attention.score == Decimal("80.000")


def test_attention_perfect(protocol):
    assert score(protocol).attention.score == Decimal("100.000")


def test_attention_no_presses_is_50_and_not_low(protocol):
    r = score(protocol, attention_press=lambda spec: [])
    assert r.attention.score == Decimal("50.000")
    assert r.attention.counters["misses"] == 10 and r.attention.counters["correct_rejections"] == 20
    assert "NO_RESPONSES" in r.attention.flags
    assert r.attention.status == Quality.VALID


def test_attention_press_every_trial_is_50_with_false_alarms(protocol):
    r = score(protocol, attention_press=lambda spec: [300.0])
    assert r.attention.score == Decimal("50.000")
    assert r.attention.counters["false_alarms"] == 20
    assert r.attention.status == Quality.VALID


def test_attention_29_trials_is_null_and_incomplete(protocol):
    r = score(protocol, attention_trials=29)
    assert r.attention.score is None
    assert r.quality == Quality.INCOMPLETE


def test_attention_duplicate_presses_counted_once(protocol):
    r = score(protocol, attention_press=lambda spec: [300.0, 300.0, 350.0] if spec["is_target"] else [])
    assert r.attention.counters["hits"] == 10
    assert r.attention.counters["extra_presses"] == 20
    assert r.attention.score == Decimal("100.000")


def test_attention_window_is_half_open(protocol):
    # A press exactly at onset+1000 ms falls in the gap, not the window.
    r = score(protocol, attention_press=lambda spec: [1000.0] if spec["is_target"] else [])
    assert r.attention.counters["hits"] == 0
    assert r.attention.counters["gap_presses"] == 10


def test_attention_unknown_trial_id_is_request_error(protocol):
    payload = build_payload(protocol)
    payload["attention"]["trials"][0]["trial_id"] = "att-99"
    with pytest.raises(ScoringInputError):
        score_submission(protocol, AssessmentSubmission.model_validate(payload), "keyboard")


# --- reaction time ------------------------------------------------------------------------------


def test_rt_median_of_ten(protocol):
    r = score(protocol, reaction=[300, 320, 340, 360, 380, 400, 420, 440, 460, 480])
    assert r.reaction.score == Decimal("390.000")


@pytest.mark.parametrize(
    "latency,expected",
    [("99.999", "ANTICIPATORY"), ("100", "USABLE"), ("2999.999", "USABLE"), ("3000", "TIMEOUT")],
)
def test_rt_boundaries(latency, expected):
    assert classify_latency(Decimal(latency), 100, 3000) == expected


def test_rt_eight_usable_two_false_starts_valid_with_warning(protocol):
    r = score(protocol, reaction=[FALSE_START, FALSE_START, 300, 310, 320, 330, 340, 350, 360, 370])
    assert r.reaction.score == Decimal("335.000")
    assert "FALSE_START_PRESENT" in r.reaction.flags
    assert r.reaction.status == Quality.VALID
    assert r.quality == Quality.VALID


def test_rt_eight_usable_two_timeouts_low_median_retained(protocol):
    r = score(protocol, reaction=[TIMEOUT, TIMEOUT, 300, 310, 320, 330, 340, 350, 360, 370])
    assert r.reaction.score == Decimal("335.000")
    assert "RT_TIMEOUT_PRESENT" in r.reaction.flags
    assert r.quality == Quality.LOW


def test_rt_seven_usable_is_null_and_low(protocol):
    r = score(protocol, reaction=[FALSE_START, FALSE_START, FALSE_START, 300, 310, 320, 330, 340, 350, 360])
    assert r.reaction.score is None
    assert "INSUFFICIENT_USABLE_TRIALS" in r.reaction.flags
    assert r.quality == Quality.LOW


def test_rt_anticipatory_response_counted_not_usable(protocol):
    r = score(protocol, reaction=[99.999, 100, 300, 310, 320, 330, 340, 350, 360, 2999.999])
    assert r.reaction.counters["anticipatory"] == 1
    assert r.reaction.counters["usable"] == 9


def test_rt_stopped_early_is_incomplete(protocol):
    r = score(protocol, reaction=[300, 310, 320], reaction_completion="STOPPED")
    assert r.reaction.score is None
    assert r.quality == Quality.INCOMPLETE


# --- overall ------------------------------------------------------------------------------------


def test_low_performance_without_technical_problems_is_valid(protocol):
    r = score(
        protocol,
        memory_entries=["apple"],
        attention_press=attention_counts(protocol, 3, 12),
        reaction=[1500 + 100 * i for i in range(10)],
    )
    assert r.quality == Quality.VALID
    assert r.memory.score == Decimal("16.667")


def test_answer_assistance_makes_task_low(protocol):
    r = score(protocol, answer_assistance={"memory": "PROVIDED", "attention": "NONE", "reaction": "UNKNOWN"})
    assert "ANSWER_ASSISTANCE" in r.memory.flags
    assert "ASSISTANCE_UNCERTAIN" in r.reaction.flags
    assert r.attention.status == Quality.VALID
    assert r.quality == Quality.LOW


def test_input_mode_change_makes_timed_tasks_low(protocol):
    # Attention runs from 68 s; switch to pointer and back during it (initial/final still keyboard).
    changes = [
        {"offset_ms": 70000.0, "from": "keyboard", "to": "pointer"},
        {"offset_ms": 71000.0, "from": "pointer", "to": "keyboard"},
    ]
    r = score(protocol, mode_changes=changes)
    assert "INPUT_MODE_CHANGED" in r.attention.flags
    assert r.quality == Quality.LOW


def test_missing_context_does_not_change_quality(protocol):
    context = {
        "sleep_hours": None,
        "mood_score": None,
        "medication_change": None,
        "reported_by": "PATIENT",
        "missing_fields": {"sleep_hours": "SKIPPED", "mood_score": "UNKNOWN", "medication_change": "SKIPPED"},
    }
    assert score(protocol, context=context).quality == Quality.VALID


# --- structural validation (request errors, not stored) -----------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(final_score=100),  # undeclared field
        lambda p: p["context"].update(mood_score=11),
        lambda p: p["context"].update(sleep_hours=-1),
        lambda p: p["context"]["missing_fields"].update(mood_score="SKIPPED"),  # present field marked missing
        lambda p: p["context"].update(medication_change="false"),  # no string coercion
        lambda p: p["context"].update(medication_change="YES"),
        lambda p: p["memory"].update(distractor_start_ms=None),  # later stage without an earlier one
        lambda p: p["attention"].update(end_reason="STOPPED"),  # contradicts completion
        lambda p: p["reaction"]["trials"][0].update(end_reason="INTERRUPTED"),  # no interruption listed
        lambda p: p["telemetry"].update(pause_events=[{"start_ms": 5.0, "end_ms": 1.0}]),
        lambda p: p["memory"].pop("interruptions"),  # every field is required
        lambda p: p["memory"]["recall_entries"].extend(["x", "y"]),  # > 6 entries
        lambda p: p["memory"].update(recall_entries=["a" * 41]),
        lambda p: p["attention"]["trials"][0].update(onset_ms=-5),
        lambda p: p["reaction"]["trials"][0].update(end_ms=1e12),
        lambda p: p.update(patient_id="someone-else"),
    ],
)
def test_structural_errors_rejected(protocol, mutate):
    payload = build_payload(protocol)
    mutate(payload)
    with pytest.raises(ValidationError):
        AssessmentSubmission.model_validate(payload)


def test_null_context_without_reason_is_canonicalized_to_skipped(protocol):
    payload = build_payload(protocol)
    payload["context"].update(sleep_hours=None)
    sub = AssessmentSubmission.model_validate(payload)
    assert sub.context.missing_fields == {"sleep_hours": "SKIPPED"}
    assert sub.canonical()["context"]["missing_fields"] == {"sleep_hours": "SKIPPED"}


def test_pause_and_blur_evidence(protocol):
    paused = score(protocol, pause_events=[{"start_ms": 80000.0, "end_ms": 90000.0}])
    assert "INTERRUPTION" in paused.attention.flags and paused.quality == Quality.LOW
    blurred = score(protocol, blur_count=3)
    assert blurred.quality == Quality.VALID and blurred.details["telemetry_warnings"] == ["BLUR_OBSERVED"]


def test_event_budget_is_enforced(protocol):
    payload = build_payload(protocol)
    payload["telemetry"]["visibility_events"] = [{"offset_ms": 10.0, "state": "visible"}] * 501
    with pytest.raises(ValidationError):
        AssessmentSubmission.model_validate(payload)
