import { z } from 'zod'

// Runtime mirror of the doctor contracts in docs/openapi.json (backend/app/schemas/doctor.py).
// Scores are points (0–100), reaction time is milliseconds; nullable fields are always present.
// z.number() rejects NaN/Infinity, so nonfinite values fail at the API boundary.

const id = z.string().min(1)
const time = z.iso.datetime()
const num = z.number()

export const availability = z.enum([
  'PENDING',
  'BUILDING_BASELINE',
  'INSUFFICIENT_DATA',
  'MODEL_UNAVAILABLE',
  'ANALYSIS_ERROR',
  'COMPLETE',
])
export const deviationLevel = z.enum(['NORMAL', 'REVIEW', 'PERSISTENT_DEVIATION', 'HIGH_DEVIATION'])
export const flaggedLevel = z.enum(['REVIEW', 'PERSISTENT_DEVIATION', 'HIGH_DEVIATION'])
export const workflowStatus = z.enum(['OPEN', 'ACKNOWLEDGED', 'RESOLVED'])
export const reviewAction = z.enum(['ACKNOWLEDGED', 'NOTE_ADDED', 'RESOLVED'])
export const domain = z.enum(['memory', 'attention', 'reaction_time_ms'])
export const source = z.enum(['LIVE_DEMO', 'SYNTHETIC_HISTORY', 'SCENARIO_REPLAY'])
export const schedulePurpose = z.enum(['SCHEDULED', 'RETAKE_AFTER_UNRELIABLE', 'EXTRA_ATTEMPT', 'OFF_SCHEDULE'])
export const quality = z.enum(['VALID', 'LOW', 'INCOMPLETE'])
export const modelKind = z.enum(['LAST_VALUE', 'LINEAR_TREND', 'GRU'])

const page = <T extends z.ZodType>(item: T) => z.object({ items: z.array(item), next_cursor: z.string().nullable() })

export const doctorSummary = z.object({
  assigned_patient_count: z.int(),
  patients_with_open_alerts: z.int(),
  open_alert_count: z.int(),
  acknowledged_alert_count: z.int(),
  pending_analysis_count: z.int(),
  analysis_error_count: z.int(),
  generated_at: time,
})

export const patientListItem = z.object({
  patient_id: id,
  display_name: z.string(),
  is_demo: z.boolean(),
  account_active: z.boolean(),
  latest_assessment_at: time.nullable(),
  latest_analysis_availability: availability.nullable(),
  latest_deviation_level: deviationLevel.nullable(),
  unresolved_alert_count: z.int(),
})

export const patientHeader = z.object({
  patient_id: id,
  display_name: z.string(),
  is_demo: z.boolean(),
  timezone: z.string().min(1),
  account_active: z.boolean(),
})

const forecastSummary = z.object({
  forecast_id: id,
  issued_at: time,
  history_cutoff_at: time,
  model_kind: modelKind,
  model_version: z.string(),
  policy_version: z.string(),
  predicted_memory_score: num,
  predicted_attention_score: num,
  predicted_reaction_time_ms: num,
})

const cognitiveIndexComponents = z.object({ memory: num, attention: num, response_speed: num })

/** Descriptive composite `cognitive_index_v1` (refinement 01); null is unavailable, never zero. */
export const cognitiveIndex = z.object({
  version: z.literal('cognitive_index_v1'),
  observed_value: num.nullable(),
  forecast_value: num.nullable(),
  observed_components: cognitiveIndexComponents.nullable(),
  forecast_components: cognitiveIndexComponents.nullable(),
  observed_unavailable_reasons: z.array(z.string()),
  forecast_unavailable_reasons: z.array(z.string()),
  forecast_response_speed_clipped: z.boolean(),
})

export const cognitiveIndexMetadata = z.object({
  version: z.literal('cognitive_index_v1'),
  supported_protocol_versions: z.array(z.string()),
  supported_scoring_versions: z.array(z.string()),
  weights: z.record(z.string(), num),
  reaction_time_floor_ms: num,
  reaction_time_ceiling_ms: num,
  scale_min: num,
  scale_max: num,
  display_decimals: z.int(),
})

export const doctorPatientDetail = z.object({
  patient: patientHeader,
  assigned_at: time,
  latest_assessment_at: time.nullable(),
  latest_analysis_availability: availability.nullable(),
  latest_deviation_level: deviationLevel.nullable(),
  open_alert_count: z.int(),
  acknowledged_alert_count: z.int(),
  score_metadata: cognitiveIndexMetadata,
})

export const timelineItem = z.object({
  assessment_id: id,
  observed_at: time,
  target_at: time,
  source,
  schedule_purpose: schedulePurpose,
  quality_status: quality,
  longitudinal_eligible: z.boolean(),
  scores: z.object({ memory_score: num.nullable(), attention_score: num.nullable(), reaction_time_ms: num.nullable() }),
  forecast: forecastSummary.nullable(),
  analysis: z.object({
    availability,
    deviation_level: deviationLevel.nullable(),
    aggregate_deviation: num.nullable(),
    persistent_count: z.int().nullable(),
    reason_codes: z.array(z.string()),
  }),
  alert: z.object({ alert_id: id, workflow_status: workflowStatus, lock_version: z.int() }).nullable(),
  cognitive_index: cognitiveIndex,
})

const taskEvidence = z.object({
  completion: z.string(),
  status: quality,
  low_flags: z.array(z.string()),
  warnings: z.array(z.string()),
  counters: z.record(z.string(), z.int()),
})

export const domainDeviation = z.object({
  observed: num,
  predicted: num,
  residual: num,
  worsening: num,
  scale: num,
  z: num,
})

export const explanation = z.object({
  summary: z.string(),
  sentences: z.array(z.string()),
  caveats: z.array(z.string()),
  facts: z.record(z.string(), z.unknown()),
})

export const contextCheckin = z.object({
  sleep_hours: num.nullable(),
  mood_score: z.int().nullable(),
  medication_change: z.boolean().nullable(),
  reported_by: z.enum(['PATIENT', 'CAREGIVER_ASSISTED']),
  missing_fields: z.record(z.string(), z.enum(['SKIPPED', 'UNKNOWN'])),
})

export const assessmentDetail = timelineItem.extend({
  protocol_version: z.string(),
  scoring_version: z.string(),
  quality_details: z.object({
    overall: quality,
    tasks: z.record(z.string(), taskEvidence),
    initial_input_mode: z.string(),
    final_input_mode: z.string().nullable(),
    assistance: z.record(z.string(), z.unknown()),
    comparability_key: z.string(),
    comparability_flags: z.array(z.string()),
    practice_repeated: z.boolean(),
  }),
  context: contextCheckin.nullable(),
  analysis_details: z.object({
    computed_at: time.nullable(),
    aggregate_method: z.string().nullable(),
    max_deviation: num.nullable(),
    moderate_signal: z.boolean().nullable(),
    high_signal: z.boolean().nullable(),
    persistent_count: z.int().nullable(),
    streak_evidence_assessment_ids: z.array(id),
    domain_deviations: z.record(z.string(), domainDeviation).nullable(),
    model_kind: z.string().nullable(),
    model_version: z.string().nullable(),
    policy_version: z.string().nullable(),
    preprocessing_version: z.string().nullable(),
    explanation: explanation.nullable(),
  }),
})

export const alertListItem = z.object({
  alert_id: id,
  patient_id: id,
  patient_display_name: z.string(),
  assessment_id: id,
  observed_at: time,
  created_at: time,
  workflow_status: workflowStatus,
  lock_version: z.int(),
  deviation_level: flaggedLevel,
  affected_domains: z.array(domain),
  summary: z.string(),
})

export const alertDetail = alertListItem.extend({ assessment: assessmentDetail, events_path: z.string() })

export const alertEvent = z.object({
  event_id: id,
  action: z.enum(['CREATED', 'ACKNOWLEDGED', 'NOTE_ADDED', 'RESOLVED']),
  from_status: workflowStatus.nullable(),
  to_status: workflowStatus,
  note: z.string().nullable(),
  actor: z.object({ user_id: id, display_name: z.string() }).nullable(),
  created_at: time,
})

export const alertRef = z.object({ alert_id: id, workflow_status: workflowStatus, lock_version: z.int() })

export const alertEventResponse = z.object({ event: alertEvent, alert: alertRef, replayed: z.boolean() })

export const modelStatus = z.object({
  model_kind: modelKind.nullable(),
  model_version: z.string().nullable(),
  policy_version: z.string().nullable(),
  model_loaded: z.boolean(),
  policy_ready: z.boolean(),
  forecast_ready: z.boolean(),
  reason_code: z.string().nullable(),
})

export const insightAlert = z.object({
  alert_id: id,
  created_at: time,
  deviation_level: flaggedLevel,
  workflow_status: workflowStatus,
})

export const insightAssessment = timelineItem.extend({
  protocol_version: z.string(),
  scoring_version: z.string(),
  context: contextCheckin.nullable(),
  comparison_segment_key: z.string().nullable(),
  slot_index: z.int().nullable(),
  is_representative: z.boolean(),
  previous_comparable_assessment_id: id.nullable(),
  linked_alert: insightAlert.nullable(),
})

export const insightsResponse = z.object({
  patient_id: id,
  timezone: z.string().min(1),
  generated_at: time,
  filters: z.object({ from: time, to: time, source: z.string() }),
  complete: z.literal(true),
  assessment_count: z.int(),
  score_metadata: cognitiveIndexMetadata,
  records: z.array(insightAssessment),
})

export const patientPage = page(patientListItem)
export const timelinePage = page(timelineItem)
export const alertPage = page(alertListItem)
export const alertEventPage = page(alertEvent)

// Pieces of the grounded explanation's `facts` that the evidence panel reads (validated on use).
const contextFact = z.object({
  current: num.nullable(),
  history_known_count: z.int(),
  history_mean: num.nullable(),
  comparison_available: z.boolean(),
})
export const explanationFacts = z.object({
  threshold_r: num.optional(),
  aggregate_deviation: num.optional(),
  max_deviation: num.optional(),
  conditions_met: z.array(z.string()).optional(),
  domains_at_or_above_r: z.array(z.string()).optional(),
  pattern: z.string().optional(),
  model: z.object({ kind: z.string(), version: z.string(), uses_context: z.boolean() }).optional(),
  history_range: z
    .object({ first_observed_at: z.string().nullable(), last_observed_at: z.string().nullable(), observations: z.int() })
    .optional(),
  context: z
    .object({
      sleep_hours: contextFact.optional(),
      mood_score: contextFact.optional(),
      medication_change: z
        .object({ reported: z.string(), history_yes_count: z.int(), history_known_count: z.int() })
        .optional(),
    })
    .optional(),
  forecast: z
    .object({
      forecast_id: z.string(),
      input_assessment_ids: z.array(z.string()),
      feature_sha256: z.string().optional(),
      bounds_applied: z.unknown().optional(),
    })
    .optional(),
  version: z.string().optional(),
})

export type Availability = z.infer<typeof availability>
export type DeviationLevel = z.infer<typeof deviationLevel>
export type WorkflowStatus = z.infer<typeof workflowStatus>
export type ReviewAction = z.infer<typeof reviewAction>
export type Domain = z.infer<typeof domain>
export type Source = z.infer<typeof source>
export type SchedulePurpose = z.infer<typeof schedulePurpose>
export type Quality = z.infer<typeof quality>
export type Page<T> = { items: T[]; next_cursor: string | null }
export type DoctorSummary = z.infer<typeof doctorSummary>
export type PatientListItem = z.infer<typeof patientListItem>
export type PatientHeader = z.infer<typeof patientHeader>
export type DoctorPatientDetail = z.infer<typeof doctorPatientDetail>
export type TimelineItem = z.infer<typeof timelineItem>
export type CognitiveIndex = z.infer<typeof cognitiveIndex>
export type CognitiveIndexComponents = z.infer<typeof cognitiveIndexComponents>
export type CognitiveIndexMetadata = z.infer<typeof cognitiveIndexMetadata>
export type InsightAssessment = z.infer<typeof insightAssessment>
export type InsightAlert = z.infer<typeof insightAlert>
export type InsightsResponse = z.infer<typeof insightsResponse>
export type ContextCheckin = z.infer<typeof contextCheckin>
export type AssessmentDetail = z.infer<typeof assessmentDetail>
export type DomainDeviation = z.infer<typeof domainDeviation>
export type AlertListItem = z.infer<typeof alertListItem>
export type AlertDetail = z.infer<typeof alertDetail>
export type AlertEvent = z.infer<typeof alertEvent>
export type AlertRef = z.infer<typeof alertRef>
export type AlertEventResponse = z.infer<typeof alertEventResponse>
export type ModelStatus = z.infer<typeof modelStatus>
export type ExplanationFacts = z.infer<typeof explanationFacts>
export type AlertEventRequest = {
  request_key: string
  expected_lock_version: number
  action: ReviewAction
  note: string | null
}
