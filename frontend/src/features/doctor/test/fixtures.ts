import type {
  AlertDetail,
  AssessmentDetail,
  CognitiveIndex,
  CognitiveIndexMetadata,
  InsightAssessment,
  InsightsResponse,
  TimelineItem,
} from '../schemas'

// Test-only fictional records shaped exactly like the backend contract.

export const WEEK_MS = 7 * 24 * 3600 * 1000
export const ANCHOR = Date.parse('2026-08-01T15:00:00Z')
export const iso = (ms: number) => new Date(ms).toISOString()

export const SCORE_META: CognitiveIndexMetadata = {
  version: 'cognitive_index_v1',
  supported_protocol_versions: ['cognitive_tasks_en_v1'],
  supported_scoring_versions: ['cognitive_scoring_v1'],
  weights: { memory: 1 / 3, attention: 1 / 3, response_speed: 1 / 3 },
  reaction_time_floor_ms: 100,
  reaction_time_ceiling_ms: 3000,
  scale_min: 0,
  scale_max: 100,
  display_decimals: 1,
}

/** Fixture-only projection so mocked timeline rows carry the same shape the API returns. */
export function fixtureIndex(
  scores: TimelineItem['scores'],
  quality: TimelineItem['quality_status'] = 'VALID',
  forecast: TimelineItem['forecast'] = null,
): CognitiveIndex {
  const reasons: string[] = []
  if (quality === 'INCOMPLETE') reasons.push('INCOMPLETE_ASSESSMENT')
  else if (quality !== 'VALID') reasons.push('LOW_QUALITY')
  const { memory_score: memory, attention_score: attention, reaction_time_ms: rt } = scores
  if (memory === null || attention === null || rt === null) reasons.push('MISSING_DOMAIN')
  else if (memory < 0 || memory > 100 || attention < 0 || attention > 100 || rt < 100 || rt >= 3000) {
    reasons.push('INVALID_DOMAIN_VALUE')
  }
  const speed = rt === null ? null : 100 * Math.min(1, Math.max(0, (3000 - rt) / 2900))
  const observed =
    reasons.length || memory === null || attention === null || speed === null ? null : (memory + attention + speed) / 3
  const forecastSpeed =
    forecast === null ? null : 100 * Math.min(1, Math.max(0, (3000 - forecast.predicted_reaction_time_ms) / 2900))
  const forecastValue =
    forecast === null || forecastSpeed === null
      ? null
      : (forecast.predicted_memory_score + forecast.predicted_attention_score + forecastSpeed) / 3
  return {
    version: 'cognitive_index_v1',
    observed_value: observed,
    forecast_value: forecastValue,
    observed_components:
      observed === null || memory === null || attention === null || speed === null
        ? null
        : { memory, attention, response_speed: speed },
    forecast_components:
      forecast === null || forecastSpeed === null
        ? null
        : {
            memory: forecast.predicted_memory_score,
            attention: forecast.predicted_attention_score,
            response_speed: forecastSpeed,
          },
    observed_unavailable_reasons: reasons,
    forecast_unavailable_reasons: forecastValue === null ? ['FORECAST_MISSING'] : [],
    forecast_response_speed_clipped: forecast !== null && (forecast.predicted_reaction_time_ms < 100 || forecast.predicted_reaction_time_ms > 3000),
  }
}

export function timelineItem(slot: number, overrides: Partial<TimelineItem> = {}): TimelineItem {
  const target = ANCHOR + slot * WEEK_MS
  const merged: TimelineItem = {
    assessment_id: `a-${slot}`,
    observed_at: iso(target + 3600 * 1000),
    target_at: iso(target),
    source: 'SYNTHETIC_HISTORY',
    schedule_purpose: 'SCHEDULED',
    quality_status: 'VALID',
    longitudinal_eligible: true,
    scores: { memory_score: 66.667, attention_score: 85, reaction_time_ms: 540.5 },
    forecast: null,
    analysis: {
      availability: 'MODEL_UNAVAILABLE',
      deviation_level: null,
      aggregate_deviation: null,
      persistent_count: null,
      reason_codes: ['HISTORICAL_IMPORT'],
    },
    alert: null,
    cognitive_index: fixtureIndex({ memory_score: 66.667, attention_score: 85, reaction_time_ms: 540.5 }),
    ...overrides,
  }
  if (!overrides.cognitive_index) {
    merged.cognitive_index = fixtureIndex(merged.scores, merged.quality_status, merged.forecast)
  }
  return merged
}

export function forecast(model = 'forecast-run-v1-gru', policy = 'policy-v1') {
  return {
    forecast_id: `f-${model}`,
    issued_at: iso(ANCHOR),
    history_cutoff_at: iso(ANCHOR),
    model_kind: 'GRU' as const,
    model_version: model,
    policy_version: policy,
    predicted_memory_score: 70.2,
    predicted_attention_score: 80,
    predicted_reaction_time_ms: 600,
  }
}

export function assessmentDetail(base: TimelineItem): AssessmentDetail {
  return {
    ...base,
    protocol_version: 'cognitive_tasks_en_v1',
    scoring_version: 'cognitive_scoring_v1',
    quality_details: {
      overall: base.quality_status,
      tasks: {
        memory: { completion: 'COMPLETED', status: 'VALID', low_flags: [], warnings: [], counters: { correct: 2, incorrect: 1, duplicates: 0 } },
        attention: { completion: 'COMPLETED', status: 'VALID', low_flags: [], warnings: [], counters: { hits: 9, misses: 1, false_alarms: 2, correct_rejections: 18 } },
        reaction: { completion: 'COMPLETED', status: 'VALID', low_flags: [], warnings: [], counters: { usable: 10, timeouts: 0 } },
      },
      initial_input_mode: 'keyboard',
      final_input_mode: 'keyboard',
      assistance: { navigation_help: false, context_help: false, answer_help: { memory: 'NONE', attention: 'NONE', reaction: 'NONE' } },
      comparability_key: 'cognitive_tasks_en_v1|cognitive_scoring_v1|keyboard|0',
      comparability_flags: [],
      practice_repeated: false,
    },
    context: { sleep_hours: 5.5, mood_score: 6, medication_change: null, reported_by: 'PATIENT', missing_fields: { medication_change: 'UNKNOWN' } },
    analysis_details: {
      computed_at: base.observed_at,
      aggregate_method: 'mean_top_two_v1',
      max_deviation: 3.0,
      moderate_signal: true,
      high_signal: true,
      persistent_count: 1,
      streak_evidence_assessment_ids: [],
      domain_deviations: {
        memory: { observed: 33.333, predicted: 70.2, residual: -36.867, worsening: 36.867, scale: 18.84, z: 1.957 },
        attention: { observed: 85, predicted: 80, residual: 5, worsening: -5, scale: 8.75, z: 0 },
        reaction_time_ms: { observed: 1247.5, predicted: 600, residual: 647.5, worsening: 647.5, scale: 46.85, z: 13.82 },
      },
      model_kind: 'GRU',
      model_version: 'forecast-run-v1-gru',
      policy_version: 'policy-v1',
      preprocessing_version: 'preprocessing_v1',
      explanation: {
        summary: 'Memory was 36.9 points below the stored forecast.',
        sentences: ['Memory was 36.9 points below the stored forecast (deviation 1.96; review threshold 2.50).'],
        caveats: ['Context reports are shown for review; they are not identified as a cause and do not cancel a flag.'],
        facts: {
          threshold_r: 2.5,
          conditions_met: ['MAX_AT_OR_ABOVE_R', 'MAX_AT_OR_ABOVE_2R'],
          domains_at_or_above_r: ['reaction_time_ms'],
          model: { kind: 'GRU', version: 'forecast-run-v1-gru', uses_context: true },
          context: {
            sleep_hours: { current: 5.5, history_known_count: 5, history_mean: 7.1, comparison_available: true },
            mood_score: { current: 6, history_known_count: 6, history_mean: 7, comparison_available: true },
            medication_change: { reported: 'unknown', history_yes_count: 0, history_known_count: 6 },
          },
          forecast: { forecast_id: 'f-1', input_assessment_ids: ['a-1', 'a-2'], feature_sha256: 'abc' },
        },
      },
    },
  }
}

export function alertDetail(overrides: Partial<AlertDetail> = {}): AlertDetail {
  const base = timelineItem(8, {
    assessment_id: 'a-flag',
    source: 'LIVE_DEMO',
    scores: { memory_score: 33.333, attention_score: 85, reaction_time_ms: 1247.5 },
    forecast: forecast(),
    analysis: { availability: 'COMPLETE', deviation_level: 'HIGH_DEVIATION', aggregate_deviation: 7.9, persistent_count: 1, reason_codes: [] },
    alert: { alert_id: 'al-1', workflow_status: 'OPEN', lock_version: 1 },
  })
  return {
    alert_id: 'al-1',
    patient_id: 'p-walter',
    patient_display_name: 'Walter Hughes',
    assessment_id: 'a-flag',
    observed_at: base.observed_at,
    created_at: base.observed_at,
    workflow_status: 'OPEN',
    lock_version: 1,
    deviation_level: 'HIGH_DEVIATION',
    affected_domains: ['reaction_time_ms'],
    summary: 'Reaction time was 647.5 ms slower than the stored forecast.',
    assessment: assessmentDetail(base),
    events_path: '/api/v1/doctor/alerts/al-1/events',
    ...overrides,
  }
}

export const patientDetail = {
  patient: { patient_id: 'p-walter', display_name: 'Walter Hughes', is_demo: true, timezone: 'America/New_York', account_active: true },
  assigned_at: '2026-09-01T12:00:00Z',
  latest_assessment_at: '2026-09-26T16:00:00Z',
  latest_analysis_availability: 'COMPLETE',
  latest_deviation_level: 'HIGH_DEVIATION',
  open_alert_count: 1,
  acknowledged_alert_count: 0,
  score_metadata: SCORE_META,
} as const

export function insightRecord(slot: number, overrides: Partial<InsightAssessment> = {}): InsightAssessment {
  const base = timelineItem(slot, overrides)
  return {
    ...base,
    protocol_version: 'cognitive_tasks_en_v1',
    scoring_version: 'cognitive_scoring_v1',
    context: {
      sleep_hours: 7,
      mood_score: 6,
      medication_change: false,
      reported_by: 'PATIENT',
      missing_fields: {},
    },
    comparison_segment_key: 'cognitive_tasks_en_v1|cognitive_scoring_v1|keyboard|0',
    slot_index: slot,
    is_representative: base.longitudinal_eligible,
    previous_comparable_assessment_id: null,
    linked_alert: null,
    ...overrides,
  }
}

export function insightsResponse(records: InsightAssessment[], overrides: Partial<InsightsResponse> = {}): InsightsResponse {
  return {
    patient_id: 'p-walter',
    timezone: 'America/New_York',
    generated_at: '2026-09-26T20:00:00Z',
    filters: { from: '2026-06-28T04:00:00.000Z', to: '2026-09-27T04:00:00.000Z', source: 'ALL' },
    complete: true,
    assessment_count: records.length,
    score_metadata: SCORE_META,
    records,
    ...overrides,
  }
}
