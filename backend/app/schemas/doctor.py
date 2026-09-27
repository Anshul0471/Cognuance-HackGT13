"""Doctor-facing contracts (guide 05 §11–§13). Assignment-scoped; operational counts, not risk scores.

Units: memory/attention scores 0–100 points, reaction time in milliseconds. Deviation values are
dimensionless ratios against calibrated synthetic forecast errors (not probabilities or diagnoses).
"""

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import Page, UtcDateTime

Availability = Literal[
    "PENDING", "BUILDING_BASELINE", "INSUFFICIENT_DATA", "MODEL_UNAVAILABLE", "ANALYSIS_ERROR", "COMPLETE"
]
DeviationLevel = Literal["NORMAL", "REVIEW", "PERSISTENT_DEVIATION", "HIGH_DEVIATION"]
WorkflowStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]
ReviewAction = Literal["ACKNOWLEDGED", "NOTE_ADDED", "RESOLVED"]


class CognitiveIndexComponents(BaseModel):
    """Normalized 0–100 values before weighting; raw scores/ms stay in `scores` and `forecast`."""

    memory: float
    attention: float
    response_speed: float = Field(description="Derived from reaction time; higher = faster")


class CognitiveIndex(BaseModel):
    """Descriptive composite `cognitive_index_v1` (refinement 01): (memory + attention + speed)/3.

    A display summary of the three task outcomes — not a clinical test, disease stage or
    probability, and not an input to the forecasting model or the alert rules. Observed and
    forecast values are independently nullable; null is unavailable, never zero.
    """

    version: Literal["cognitive_index_v1"]
    observed_value: float | None
    forecast_value: float | None = Field(
        description="Composite of the stored pre-assessment forecast's predictions (a projection)"
    )
    observed_components: CognitiveIndexComponents | None
    forecast_components: CognitiveIndexComponents | None
    observed_unavailable_reasons: list[str]
    forecast_unavailable_reasons: list[str]
    forecast_response_speed_clipped: bool = Field(
        description="Whether the projection clipped the predicted reaction time; false also when "
        "no projection exists (see forecast_unavailable_reasons) — never a readiness flag"
    )


class CognitiveIndexMetadata(BaseModel):
    """Formula provenance for the UI's calculation disclosure (identical on every screen)."""

    version: Literal["cognitive_index_v1"]
    supported_protocol_versions: list[str]
    supported_scoring_versions: list[str]
    weights: dict[str, float] = Field(description="Equal one-third weights (an MVP design choice)")
    reaction_time_floor_ms: float
    reaction_time_ceiling_ms: float
    scale_min: float
    scale_max: float
    display_decimals: int


class DoctorSummary(BaseModel):
    assigned_patient_count: int
    patients_with_open_alerts: int = Field(description="Patients with any OPEN or ACKNOWLEDGED alert")
    open_alert_count: int
    acknowledged_alert_count: int
    pending_analysis_count: int
    analysis_error_count: int
    generated_at: UtcDateTime


class PatientListItem(BaseModel):
    patient_id: uuid.UUID
    display_name: str
    is_demo: bool
    account_active: bool = Field(description="Patient login status; history stays visible while assigned")
    latest_assessment_at: UtcDateTime | None
    latest_analysis_availability: Availability | None
    latest_deviation_level: DeviationLevel | None
    unresolved_alert_count: int


class PatientHeader(BaseModel):
    patient_id: uuid.UUID
    display_name: str
    is_demo: bool
    timezone: str
    account_active: bool


class DoctorPatientDetail(BaseModel):
    patient: PatientHeader
    assigned_at: UtcDateTime = Field(description="When the caller's current assignment began")
    latest_assessment_at: UtcDateTime | None
    latest_analysis_availability: Availability | None
    latest_deviation_level: DeviationLevel | None
    open_alert_count: int
    acknowledged_alert_count: int
    score_metadata: CognitiveIndexMetadata = Field(
        description="Composite-score formula provenance for this screen's calculation disclosure"
    )


class Scores(BaseModel):
    memory_score: float | None = Field(description="0–100 points; null if the task was not completed")
    attention_score: float | None = Field(description="0–100 points; null if the task was not completed")
    reaction_time_ms: float | None = Field(
        description="Median usable reaction time in ms; null if unavailable"
    )


class ForecastSummary(BaseModel):
    forecast_id: uuid.UUID
    issued_at: UtcDateTime
    history_cutoff_at: UtcDateTime
    model_kind: Literal["LAST_VALUE", "LINEAR_TREND", "GRU"]
    model_version: str
    policy_version: str
    predicted_memory_score: float
    predicted_attention_score: float
    predicted_reaction_time_ms: float


class AnalysisSummary(BaseModel):
    availability: Availability
    deviation_level: DeviationLevel | None = Field(description="Only for COMPLETE analyses")
    aggregate_deviation: float | None = Field(description="Mean of the two largest directional deviations")
    persistent_count: int | None
    reason_codes: list[str]


class AlertRef(BaseModel):
    alert_id: uuid.UUID
    workflow_status: WorkflowStatus
    lock_version: int


class TimelineItem(BaseModel):
    assessment_id: uuid.UUID
    observed_at: UtcDateTime
    target_at: UtcDateTime
    source: Literal["LIVE_DEMO", "SYNTHETIC_HISTORY", "SCENARIO_REPLAY"]
    schedule_purpose: Literal["SCHEDULED", "RETAKE_AFTER_UNRELIABLE", "EXTRA_ATTEMPT", "OFF_SCHEDULE"]
    quality_status: Literal["VALID", "LOW", "INCOMPLETE"]
    longitudinal_eligible: bool
    scores: Scores
    forecast: ForecastSummary | None
    analysis: AnalysisSummary
    alert: AlertRef | None
    cognitive_index: CognitiveIndex


class ContextOut(BaseModel):
    sleep_hours: float | None
    mood_score: int | None
    medication_change: bool | None = Field(description="true = change reported; null = unknown/skipped")
    reported_by: Literal["PATIENT", "CAREGIVER_ASSISTED"]
    missing_fields: dict[str, Literal["SKIPPED", "UNKNOWN"]]


class TaskEvidence(BaseModel):
    completion: str
    status: Literal["VALID", "LOW", "INCOMPLETE"]
    low_flags: list[str]
    warnings: list[str]
    counters: dict[str, int] = Field(description="Score components (counts only; no raw answers)")


class QualityDetails(BaseModel):
    overall: Literal["VALID", "LOW", "INCOMPLETE"]
    tasks: dict[str, TaskEvidence]
    initial_input_mode: str
    final_input_mode: str | None
    assistance: dict[str, Any] = Field(description="Declared help (navigation/context/answers)")
    comparability_key: str
    comparability_flags: list[str]
    practice_repeated: bool


class AnalysisDetails(BaseModel):
    computed_at: UtcDateTime | None
    aggregate_method: str | None
    max_deviation: float | None
    moderate_signal: bool | None
    high_signal: bool | None
    persistent_count: int | None
    streak_evidence_assessment_ids: list[uuid.UUID] = Field(
        description="Consecutive earlier assessments whose qualifying analyses form the current streak"
    )
    domain_deviations: dict[str, dict[str, float]] | None = Field(
        description="Per domain: observed, predicted, residual (actual−predicted), worsening, scale, z"
    )
    model_kind: str | None
    model_version: str | None
    policy_version: str | None
    preprocessing_version: str | None
    explanation: dict[str, Any] | None = Field(description="Deterministic grounded template explanation")


class AssessmentDetail(TimelineItem):
    protocol_version: str
    scoring_version: str
    quality_details: QualityDetails
    context: ContextOut | None
    analysis_details: AnalysisDetails


class AlertListItem(BaseModel):
    alert_id: uuid.UUID
    patient_id: uuid.UUID
    patient_display_name: str
    assessment_id: uuid.UUID
    observed_at: UtcDateTime
    created_at: UtcDateTime
    workflow_status: WorkflowStatus
    lock_version: int
    deviation_level: Literal["REVIEW", "PERSISTENT_DEVIATION", "HIGH_DEVIATION"]
    affected_domains: list[Literal["memory", "attention", "reaction_time_ms"]]
    summary: str


class AlertDetail(AlertListItem):
    assessment: AssessmentDetail
    events_path: str = Field(description="Paginated review history: GET this path")


class Actor(BaseModel):
    user_id: uuid.UUID
    display_name: str


class AlertEventOut(BaseModel):
    event_id: uuid.UUID
    action: Literal["CREATED", "ACKNOWLEDGED", "NOTE_ADDED", "RESOLVED"]
    from_status: WorkflowStatus | None
    to_status: WorkflowStatus
    note: str | None
    actor: Actor | None = Field(description="null for the system CREATED event")
    created_at: UtcDateTime


class AlertEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_key: uuid.UUID
    expected_lock_version: Annotated[int, Field(ge=1, strict=True)]
    action: ReviewAction
    note: Annotated[str, StringConstraints(max_length=4000, strict=True)] | None = Field(
        description="Plain text. Required (non-empty after trimming) for NOTE_ADDED and RESOLVED"
    )


class AlertEventResponse(BaseModel):
    event: AlertEventOut = Field(description="The recorded event (the original one on replay)")
    alert: AlertRef = Field(description="The alert's *current* workflow status and lock version")
    replayed: bool


class InsightAlert(BaseModel):
    """Panel F needs the alert's creation time and original category beside its current status."""

    alert_id: uuid.UUID
    created_at: UtcDateTime
    deviation_level: Literal["REVIEW", "PERSISTENT_DEVIATION", "HIGH_DEVIATION"]
    workflow_status: WorkflowStatus = Field(description="Current status, not the status on that date")


class InsightAssessment(TimelineItem):
    """A timeline item plus the fields the Insights panels need (no raw answers, no notes)."""

    protocol_version: str
    scoring_version: str
    context: ContextOut | None
    comparison_segment_key: str | None = Field(
        description="Opaque comparability segment (protocol|scoring|input mode|device epoch)"
    )
    slot_index: int | None
    is_representative: bool = Field(description="The weekly representative for its slot")
    previous_comparable_assessment_id: uuid.UUID | None = Field(
        description="Adjacent eligible predecessor *within this filtered range* (same segment, "
        "same source, previous canonical slot, both composites available); null otherwise"
    )
    linked_alert: InsightAlert | None


class InsightsFilters(BaseModel):
    frm: UtcDateTime = Field(alias="from", description="Inclusive UTC lower bound")
    to: UtcDateTime = Field(description="Exclusive UTC upper bound")
    source: str = Field(description="`ALL` or one assessment source enum")


class InsightsResponse(BaseModel):
    """One complete bounded snapshot for the selected patient and range (never partial)."""

    patient_id: uuid.UUID
    timezone: str = Field(description="Patient IANA zone for displayed dates")
    generated_at: UtcDateTime
    filters: InsightsFilters
    complete: Literal[True] = Field(description="Always true; overflow is a 422, never a truncation")
    assessment_count: int = Field(description="Equals len(records)")
    score_metadata: CognitiveIndexMetadata
    records: list[InsightAssessment] = Field(description="Ordered (observed_at ASC, assessment_id ASC)")


PatientPage = Page[PatientListItem]
TimelinePage = Page[TimelineItem]
AlertPage = Page[AlertListItem]
AlertEventPage = Page[AlertEventOut]
