"""Strict patient-assessment API models (guide 02 §13, guide 05 §6–§8). Undeclared fields are rejected.

The submission carries raw responses and telemetry only: never scores, quality, patient ID,
forecast, model version, source, target or timestamps. All offsets are milliseconds on the
browser's monotonic clock relative to one `run_id` origin, and at most the 20-minute session budget.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.models import InputMode, ReportedBy
from app.schemas.common import UtcDateTime
from app.services.protocol import LIMITS

MAX_EVENTS_PER_TRIAL = LIMITS["max_events_per_trial"]
MAX_TELEMETRY_EVENTS = LIMITS["max_telemetry_events"]
MAX_RUN_DURATION_MS = LIMITS["max_run_duration_ms"]

Offset = Annotated[float, Field(ge=0, le=MAX_RUN_DURATION_MS, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _ordered(*values: float | None) -> bool:
    present = [v for v in values if v is not None]
    return all(a <= b for a, b in zip(present, present[1:], strict=False))


# --- session start ------------------------------------------------------------------------------


class StartSessionRequest(StrictModel):
    """All fields required. The client cannot set target time, source, protocol, model or forecast."""

    start_key: uuid.UUID
    input_mode: InputMode
    device_changed: StrictBool
    navigation_assistance: StrictBool
    allow_unscheduled: StrictBool


# --- submission (backend_contract_v1, guide 05 §7) --------------------------------------------------
# Every field is required; skipped/absent stages use explicit null / empty arrays.

Completion = Literal["COMPLETED", "SKIPPED", "STOPPED"]
AnswerHelp = Literal["NONE", "PROVIDED", "UNKNOWN"]
TrialId = Annotated[str, StringConstraints(min_length=1, max_length=16)]
MAX_INTERRUPTIONS = 20


class ResponseEvent(StrictModel):
    offset_ms: Offset


class TimingInterruption(StrictModel):
    kind: Literal["HIDDEN", "PAUSE", "TIMING_GAP"]
    start_ms: Offset
    end_ms: Offset | None = Field(description="null if the run ended while interrupted")

    @model_validator(mode="after")
    def _check(self) -> "TimingInterruption":
        if self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("interruption ends before it starts")
        return self


Interruptions = Annotated[list[TimingInterruption], Field(max_length=MAX_INTERRUPTIONS)]
Responses = Annotated[list[ResponseEvent], Field(max_length=MAX_EVENTS_PER_TRIAL)]


def _ordered_interruptions(items: list[TimingInterruption]) -> bool:
    return all(a.start_ms <= b.start_ms for a, b in zip(items, items[1:], strict=False))


class MemoryRecord(StrictModel):
    completion: Completion
    exposure_start_ms: Offset | None
    exposure_end_ms: Offset | None
    distractor_start_ms: Offset | None
    distractor_end_ms: Offset | None
    recall_start_ms: Offset | None
    recall_end_ms: Offset | None
    recall_entries: list[Annotated[str, StringConstraints(max_length=40)]] = Field(max_length=6)
    end_reason: Literal["DONE", "NONE_RECALLED", "TIMEOUT", "SKIPPED", "STOPPED"]
    interruptions: Interruptions

    def stages(self) -> list[float | None]:
        return [
            self.exposure_start_ms,
            self.exposure_end_ms,
            self.distractor_start_ms,
            self.distractor_end_ms,
            self.recall_start_ms,
            self.recall_end_ms,
        ]

    @model_validator(mode="after")
    def _check(self) -> "MemoryRecord":
        stages = self.stages()
        present = [v is not None for v in stages]
        if any(later and not earlier for earlier, later in zip(present, present[1:], strict=False)):
            raise ValueError("memory stages must occur in order (a later stage needs the earlier ones)")
        if not _ordered(*stages) or not _ordered_interruptions(self.interruptions):
            raise ValueError("memory offsets must be ordered")
        if self.completion == "COMPLETED":
            if not all(present):
                raise ValueError("completed memory task requires all stage offsets")
            if self.end_reason not in ("DONE", "NONE_RECALLED", "TIMEOUT"):
                raise ValueError("completed memory task has an invalid end_reason")
        elif self.end_reason != self.completion:
            raise ValueError("end_reason must match a skipped/stopped completion")
        if self.completion == "SKIPPED" and (any(present) or self.recall_entries):
            raise ValueError("a skipped memory task has no stages or entries")
        if self.end_reason == "NONE_RECALLED" and any(e.strip() for e in self.recall_entries):
            raise ValueError("NONE_RECALLED cannot carry recall entries")
        return self


class AttentionTrial(StrictModel):
    trial_id: TrialId
    onset_ms: Offset
    offset_ms: Offset | None = Field(description="stimulus removal; null only for an interrupted trial")
    gap_end_ms: Offset | None
    responses: Responses
    interruptions: Interruptions
    event_overflow: StrictBool

    @model_validator(mode="after")
    def _check(self) -> "AttentionTrial":
        if not _ordered(self.onset_ms, self.offset_ms, self.gap_end_ms):
            raise ValueError("attention trial offsets must be ordered")
        if not self.interruptions and (self.offset_ms is None or self.gap_end_ms is None):
            raise ValueError("uninterrupted attention trial requires offset_ms and gap_end_ms")
        end = self.gap_end_ms if self.gap_end_ms is not None else self.offset_ms
        for r in self.responses:
            if r.offset_ms < self.onset_ms or (end is not None and r.offset_ms > end):
                raise ValueError("attention response outside its trial")
        return self


class AttentionRecord(StrictModel):
    completion: Completion
    trials: list[AttentionTrial] = Field(max_length=30)
    end_reason: Literal["FINISHED", "SKIPPED", "STOPPED"]

    @model_validator(mode="after")
    def _check(self) -> "AttentionRecord":
        if (self.completion == "COMPLETED") != (self.end_reason == "FINISHED") or (
            self.completion != "COMPLETED" and self.end_reason != self.completion
        ):
            raise ValueError("attention end_reason does not match completion")
        if self.completion == "SKIPPED" and self.trials:
            raise ValueError("a skipped attention task has no trials")
        return self


class ReactionTrial(StrictModel):
    trial_id: TrialId
    wait_start_ms: Offset
    go_onset_ms: Offset | None = Field(description="null when the trial ended before GO")
    end_ms: Offset
    intertrial_end_ms: Offset | None = Field(description="null if the run stopped before the pause ended")
    responses: Responses
    # Client's view, stored for diagnostics only; the server recomputes the outcome.
    end_reason: Literal["RESPONSE", "FALSE_START", "TIMEOUT", "INTERRUPTED"]
    interruptions: Interruptions
    max_frame_gap_ms: Annotated[float, Field(ge=0, le=MAX_RUN_DURATION_MS, allow_inf_nan=False)] | None
    event_overflow: StrictBool

    @model_validator(mode="after")
    def _check(self) -> "ReactionTrial":
        if not _ordered(self.wait_start_ms, self.go_onset_ms, self.end_ms, self.intertrial_end_ms):
            raise ValueError("reaction trial offsets must be ordered")
        for r in self.responses:
            if r.offset_ms < self.wait_start_ms or r.offset_ms > self.end_ms:
                raise ValueError("reaction response outside its trial")
        if self.end_reason == "INTERRUPTED" and not self.interruptions:
            raise ValueError("an INTERRUPTED trial must list its interruption")
        return self

    @property
    def interrupted(self) -> bool:
        return bool(self.interruptions) or self.end_reason == "INTERRUPTED"


class ReactionRecord(StrictModel):
    completion: Completion
    trials: list[ReactionTrial] = Field(max_length=10)
    end_reason: Literal["FINISHED", "SKIPPED", "STOPPED"]

    @model_validator(mode="after")
    def _check(self) -> "ReactionRecord":
        if (self.completion == "COMPLETED") != (self.end_reason == "FINISHED") or (
            self.completion != "COMPLETED" and self.end_reason != self.completion
        ):
            raise ValueError("reaction end_reason does not match completion")
        if self.completion == "SKIPPED" and self.trials:
            raise ValueError("a skipped reaction task has no trials")
        return self


class PracticeRecord(StrictModel):
    completed: StrictBool
    repeats: Annotated[StrictInt, Field(ge=0, le=1)]


class VisibilityEvent(StrictModel):
    offset_ms: Offset
    state: Literal["visible", "hidden"]


class PauseEvent(StrictModel):
    start_ms: Offset
    end_ms: Offset | None

    @model_validator(mode="after")
    def _check(self) -> "PauseEvent":
        if self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("pause ends before it starts")
        return self


class ModeChange(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    offset_ms: Offset
    from_mode: InputMode = Field(alias="from")
    to_mode: InputMode = Field(alias="to")


class AnswerHelpDeclaration(StrictModel):
    memory: AnswerHelp
    attention: AnswerHelp
    reaction: AnswerHelp


class Assistance(StrictModel):
    navigation_help: StrictBool
    context_help: StrictBool
    answer_help: AnswerHelpDeclaration


class Viewport(StrictModel):
    # Coarse (rounded to 100 px) only; no device fingerprinting.
    width: Annotated[StrictInt, Field(ge=100, le=10000, multiple_of=100)]
    height: Annotated[StrictInt, Field(ge=100, le=10000, multiple_of=100)]


class Telemetry(StrictModel):
    initial_input_mode: InputMode
    final_input_mode: InputMode
    viewport: Viewport
    visibility_events: list[VisibilityEvent] = Field(max_length=MAX_TELEMETRY_EVENTS)
    pause_events: list[PauseEvent] = Field(max_length=MAX_TELEMETRY_EVENTS)
    blur_count: Annotated[StrictInt, Field(ge=0, le=MAX_TELEMETRY_EVENTS)]
    mode_changes: list[ModeChange] = Field(max_length=MAX_TELEMETRY_EVENTS)
    event_overflow: StrictBool
    assistance: Assistance


ContextField = Literal["sleep_hours", "mood_score", "medication_change"]
CONTEXT_FIELDS: tuple[ContextField, ...] = ("sleep_hours", "mood_score", "medication_change")


class ContextCheckinIn(StrictModel):
    sleep_hours: Annotated[Decimal, Field(ge=0, le=24, max_digits=4, decimal_places=2)] | None
    mood_score: Annotated[StrictInt, Field(ge=1, le=10)] | None
    medication_change: StrictBool | None = Field(
        description="true = a change was reported; null = unknown/skipped"
    )
    reported_by: ReportedBy
    missing_fields: dict[ContextField, Literal["SKIPPED", "UNKNOWN"]] = Field(
        description="Reason per null field. A null field whose reason is omitted is canonicalized to SKIPPED."
    )

    @model_validator(mode="after")
    def _missing_matches_nulls(self) -> "ContextCheckinIn":
        nulls = [f for f in CONTEXT_FIELDS if getattr(self, f) is None]
        if any(f not in nulls for f in self.missing_fields):
            raise ValueError("a present context field cannot be marked missing")
        # Canonicalization (part of the request hash): explicit null without a reason → SKIPPED.
        self.missing_fields = {f: self.missing_fields.get(f, "SKIPPED") for f in nulls}
        return self


class AssessmentSubmission(StrictModel):
    submission_key: uuid.UUID
    run_id: uuid.UUID
    protocol_version: Annotated[str, StringConstraints(max_length=64)]
    run_duration_ms: Offset
    memory: MemoryRecord
    attention: AttentionRecord
    reaction: ReactionRecord
    practice: PracticeRecord
    telemetry: Telemetry
    context: ContextCheckinIn

    @model_validator(mode="after")
    def _offsets_within_run(self) -> "AssessmentSubmission":
        d = self.run_duration_ms
        tel = self.telemetry
        offsets: list[float | None] = list(self.memory.stages())
        interruptions = list(self.memory.interruptions)
        for t in self.attention.trials:
            offsets += [t.onset_ms, t.offset_ms, t.gap_end_ms, *(r.offset_ms for r in t.responses)]
            interruptions += t.interruptions
        for t in self.reaction.trials:
            offsets += [
                t.wait_start_ms,
                t.go_onset_ms,
                t.end_ms,
                t.intertrial_end_ms,
                *(r.offset_ms for r in t.responses),
            ]
            interruptions += t.interruptions
        offsets += [i.start_ms for i in interruptions] + [i.end_ms for i in interruptions]
        offsets += [e.offset_ms for e in tel.visibility_events] + [m.offset_ms for m in tel.mode_changes]
        offsets += [p.start_ms for p in tel.pause_events] + [p.end_ms for p in tel.pause_events]
        if any(o is not None and o > d for o in offsets):
            raise ValueError("an offset exceeds run_duration_ms")
        total_events = (
            len(interruptions) + len(tel.visibility_events) + len(tel.pause_events) + len(tel.mode_changes)
        )
        if total_events > MAX_TELEMETRY_EVENTS:
            raise ValueError("too many telemetry/interruption events")
        for trials in (self.attention.trials, self.reaction.trials):
            ids = [t.trial_id for t in trials]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate trial id")
        if not all(
            a.offset_ms <= b.offset_ms
            for a, b in zip(tel.visibility_events, tel.visibility_events[1:], strict=False)
        ):
            raise ValueError("visibility events must be ordered")
        return self

    def canonical(self) -> dict[str, Any]:
        """JSON form used for storage and the idempotency hash (aliases such as `from`/`to`)."""
        return self.model_dump(mode="json", by_alias=True)


# --- responses ----------------------------------------------------------------------------------


class Reason(BaseModel):
    code: str
    message: str


class MemoryProtocolOut(BaseModel):
    word_set_id: str
    words: list[str]
    exposure_ms: int
    distractor_ms: int
    recall_limit_ms: int
    max_entries: int
    max_entry_chars: int
    distractor_step_ms: int


class AttentionTrialOut(BaseModel):
    trial_id: str = Field(validation_alias=AliasChoices("trial_id", "id"))
    shape: Literal["circle", "square", "triangle"]


class AttentionProtocolOut(BaseModel):
    trial_count: int
    stimulus_ms: int
    gap_ms: int
    trials: list[AttentionTrialOut]


class ReactionTrialOut(BaseModel):
    trial_id: str = Field(validation_alias=AliasChoices("trial_id", "id"))
    foreperiod_ms: int


class ReactionProtocolOut(BaseModel):
    trial_count: int
    response_window_ms: int
    minimum_response_ms: int
    intertrial_ms: int
    trials: list[ReactionTrialOut]


class PracticeAttentionTrialOut(AttentionTrialOut):
    is_target: bool


class PracticeProtocolOut(BaseModel):
    memory_words: list[str]
    attention_trials: list[PracticeAttentionTrialOut]
    reaction_foreperiods_ms: list[int]
    max_repeats: int


class LimitsOut(BaseModel):
    max_events_per_trial: int
    max_telemetry_events: int
    max_run_duration_ms: int


class RenderProtocolOut(BaseModel):
    """Client-rendering configuration only: no forecast, calibration, patient history or model data."""

    protocol_version: str
    language: str
    memory: MemoryProtocolOut
    attention: AttentionProtocolOut
    reaction: ReactionProtocolOut
    practice: PracticeProtocolOut
    limits: LimitsOut


SchedulePurposeOut = Literal["SCHEDULED", "RETAKE_AFTER_UNRELIABLE", "EXTRA_ATTEMPT", "OFF_SCHEDULE"]
SessionStatusOut = Literal["STARTED", "SUBMITTED", "ABANDONED", "EXPIRED"]


class SessionSchedule(BaseModel):
    anchor_at: UtcDateTime
    slot_index: int
    target_at: UtcDateTime
    purpose: SchedulePurposeOut
    longitudinal_eligible: bool = Field(
        description="Provisional until submission; final (representative) value once submitted"
    )
    reason_codes: list[str]


class _SessionBase(BaseModel):
    session_id: uuid.UUID
    status: SessionStatusOut = Field(
        description="Effective status at server time (expiry is not a GET write)"
    )
    started_at: UtcDateTime
    expires_at: UtcDateTime
    target_at: UtcDateTime
    protocol_version: str
    scoring_version: str
    input_mode: InputMode
    schedule: SessionSchedule


class StartAssessmentResponse(_SessionBase):
    protocol: RenderProtocolOut | None = Field(
        description="Task-launch material; null when a replayed session is no longer STARTED"
    )
    replayed: bool


class SessionRecoveryResponse(_SessionBase):
    """Owned session metadata. Never task words or raw answers (reload recovery = abandon/new)."""

    assessment_id: uuid.UUID | None
    receipt_path: str | None


class QualitySummary(BaseModel):
    status: Literal["VALID", "LOW", "INCOMPLETE"]
    reason_codes: list[str]
    message: str


class AnalysisSummary(BaseModel):
    """Availability only: never deviation categories, anomaly numbers or internal failures."""

    availability: Literal[
        "PENDING", "BUILDING_BASELINE", "INSUFFICIENT_DATA", "MODEL_UNAVAILABLE", "ANALYSIS_ERROR", "COMPLETE"
    ]
    reason_codes: list[str]
    message: str


class AssessmentReceipt(BaseModel):
    assessment_id: uuid.UUID
    session_id: uuid.UUID
    received_at: UtcDateTime
    saved: Literal[True] = True
    quality: QualitySummary
    analysis: AnalysisSummary = Field(description="Current persisted analysis availability")
    replayed: bool


class CurrentSession(BaseModel):
    session_id: uuid.UUID
    status: SessionStatusOut
    started_at: UtcDateTime
    expires_at: UtcDateTime
    target_at: UtcDateTime


class PatientSchedule(BaseModel):
    anchor_at: UtcDateTime | None
    next_target_at: UtcDateTime | None
    window_opens_at: UtcDateTime | None
    window_closes_at: UtcDateTime | None
    scheduled_start_allowed: bool
    reason_codes: list[str]


class AssessmentStatus(BaseModel):
    patient_id: uuid.UUID
    server_time: UtcDateTime
    current_session: CurrentSession | None
    last_receipt: AssessmentReceipt | None
    schedule: PatientSchedule
