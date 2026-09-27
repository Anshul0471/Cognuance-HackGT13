"""Machine-readable reason codes with calm, patient-friendly text (guide 02 §11, §13).

Messages never mention thresholds, scores, diagnoses or disease progression.
"""

# ruff: noqa: E501  (one message per line reads best)

from app.schemas.assessments import Reason

MESSAGES: dict[str, str] = {
    # receipt task codes
    "MEMORY_SKIPPED": "The word activity was skipped.",
    "MEMORY_STOPPED": "The word activity was stopped before the end.",
    "ATTENTION_SKIPPED": "The shapes activity was skipped.",
    "ATTENTION_STOPPED": "The shapes activity was stopped before the end.",
    "REACTION_SKIPPED": "The GO activity was skipped.",
    "REACTION_STOPPED": "The GO activity was stopped before the end.",
    "MEMORY_NOT_ALL_TRIALS_PRESENTED": "The word activity did not finish.",
    "ATTENTION_NOT_ALL_TRIALS_PRESENTED": "The shapes activity stopped before all items were shown.",
    "REACTION_NOT_ALL_TRIALS_PRESENTED": "The GO activity stopped before all signals were shown.",
    "INCOMPLETE_TARGET": "Not every activity was finished, so this check-in can't be compared with others.",
    "LOW_QUALITY_TARGET": "Something during this check-in (such as an interruption) means it can't be compared reliably.",
    # quality
    "INCOMPLETE_ASSESSMENT": "Not every activity was finished, so this check-in can't be compared with others.",
    "LOW_QUALITY": "Something during this check-in (such as an interruption) means it can't be compared reliably.",
    "TASK_NOT_COMPLETED": "This activity was not finished.",
    "NOT_ALL_TRIALS_PRESENTED": "This activity stopped before all items were shown.",
    "INTERRUPTION": "The activity was interrupted (for example, the screen was hidden or paused).",
    "TRIAL_INTERRUPTED": "An item was interrupted.",
    "EXPOSURE_TIMING_DEVIATION": "The word display time was not as planned.",
    "DISTRACTOR_TIMING_DEVIATION": "The waiting period before recall was not as planned.",
    "RECALL_TIMING_DEVIATION": "The recall time was longer than planned.",
    "TIMING_DEVIATION": "The device's timing was irregular during the shapes activity.",
    "TIMER_INTERRUPTION": "The device's timing was irregular during the GO activity.",
    "INPUT_MODE_CHANGED": "The way of answering changed during the activities.",
    "ANSWER_ASSISTANCE": "Someone helped answer this activity.",
    "ASSISTANCE_UNCERTAIN": "It's not certain whether someone helped answer this activity.",
    "RT_TIMEOUT_PRESENT": "Some GO signals had no response in time.",
    "INSUFFICIENT_USABLE_TRIALS": "Not enough responses could be used.",
    "RESPONSE_OVERFLOW": "Too many presses were recorded to use this activity.",
    "TELEMETRY_OVERFLOW": "Too many events were recorded to use these activities.",
    # warnings (do not by themselves lower quality)
    "FALSE_START_PRESENT": "A button was pressed before GO once or twice.",
    "ANTICIPATORY_PRESENT": "A response came very quickly after GO once or twice.",
    "NO_RESPONSES": "No presses were recorded in this activity.",
    "ALL_RESPONSES": "A press was recorded for every shape.",
    "BLUR_OBSERVED": "Another window may have been in focus briefly.",
    "PRACTICE_REPEATED": "The practice was repeated.",
    "CLIENT_OUTCOME_MISMATCH": "The device and server recorded an item differently; the server's result was used.",
    # schedule / comparability
    "EXTRA_ATTEMPT": "This week's check-in was already recorded, so this one is saved as extra.",
    "OFF_SCHEDULE": "This check-in was outside the weekly window, so it's saved but not used for weekly comparison.",
    "RETAKE_AFTER_UNRELIABLE": "This is a second try this week; practice with the activities may affect results.",
    "REPRESENTATIVE_ALREADY_EXISTS": "Another check-in was already recorded for this week.",
    "COMPARABILITY_CHANGE": "The device or answering method changed, so earlier check-ins can't be compared yet.",
    "PROTOCOL_MISMATCH": "The activities' version changed, so earlier check-ins can't be compared.",
    # history / model
    "BUILDING_BASELINE": "More weekly check-ins are needed before changes can be compared.",
    "HISTORY_GAP": "A recent week was missed, so there isn't a continuous history to compare with yet.",
    "MODEL_NOT_CONFIGURED": "Your results are saved. Automatic comparison isn't available in this version yet.",
    "MODEL_UNAVAILABLE": "Your results are saved. Automatic comparison isn't available right now.",
    "FORECAST_FAILED": "The comparison could not be prepared for this check-in.",
    "HISTORICAL_IMPORT": "This earlier check-in was imported as history, so it was not compared when it was recorded.",
    "LATE_AVAILABILITY": "An earlier check-in arrived too late to be used for this comparison.",
    # analysis
    "WAITING_FOR_PREVIOUS_ANALYSIS": "Your results are saved. The comparison is waiting for an earlier check-in to be processed.",
    "ANALYSIS_ERROR": "Your results are saved. The comparison could not be finished yet and can be retried.",
    # scheduling status
    "FIRST_CHECKIN": "Your first check-in sets your weekly schedule.",
    "IN_WINDOW": "Your weekly check-in is available now.",
    "SLOT_COMPLETED": "This week's check-in is done.",
    "ATTEMPT_LIMIT_REACHED": "This week's check-in attempts have been used.",
    "OUTSIDE_SCHEDULE_WINDOW": "Your next weekly check-in isn't open yet.",
    "OUTSIDE_WINDOW": "Your next weekly check-in isn't open yet.",  # legacy stored reason
    "ACTIVE_SESSION_EXISTS": "A check-in was started and not finished.",
}


def patient_visible(codes: list[str]) -> list[str]:
    """Only codes with patient-friendly text; technical model/artifact codes stay server-side."""
    return [c for c in codes if c in MESSAGES]


def reason(code: str) -> Reason:
    return Reason(code=code, message=MESSAGES.get(code, code.replace("_", " ").capitalize()))


def reasons(codes: list[str]) -> list[Reason]:
    return [reason(c) for c in codes]
