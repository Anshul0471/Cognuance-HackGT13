import type {
  Availability,
  InsightAssessment,
  InsightsResponse,
  Quality,
  Source,
  WorkflowStatus,
} from '../schemas'

// Presentation arrays for Visual Insights. Eligibility, segment keys, scores and predecessor IDs
// come from the backend snapshot; this module only bins, counts and shapes them for the charts.

export const HEATMAP_ROWS = [
  { key: 'memory', label: 'Memory' },
  { key: 'attention', label: 'Attention' },
  { key: 'response_speed', label: 'Response speed (normalized)' },
] as const

export type HeatmapRowKey = (typeof HEATMAP_ROWS)[number]['key']

export type HeatmapColumn = {
  assessmentId: string
  observedAt: string
  source: Source
  segmentKey: string | null
  usable: boolean
  memory: number | null
  attention: number | null
  responseSpeed: number | null
  reactionTimeMs: number | null
  quality: Quality
  reasons: string[]
}

export function heatmapColumns(records: readonly InsightAssessment[]): {
  columns: HeatmapColumn[]
  extras: InsightAssessment[]
} {
  const extras: InsightAssessment[] = []
  const columns: HeatmapColumn[] = []
  for (const record of records) {
    if (record.schedule_purpose === 'EXTRA_ATTEMPT' || record.schedule_purpose === 'OFF_SCHEDULE') {
      extras.push(record)
      continue
    }
    const components = record.cognitive_index.observed_components
    columns.push({
      assessmentId: record.assessment_id,
      observedAt: record.observed_at,
      source: record.source,
      segmentKey: record.comparison_segment_key,
      usable: components !== null,
      memory: components?.memory ?? null,
      attention: components?.attention ?? null,
      responseSpeed: components?.response_speed ?? null,
      reactionTimeMs: record.scores.reaction_time_ms,
      quality: record.quality_status,
      reasons: record.cognitive_index.observed_unavailable_reasons,
    })
  }
  return { columns, extras }
}

export type ChangePair = {
  current: InsightAssessment
  previous: InsightAssessment
  delta: number
}

export function changePairs(records: readonly InsightAssessment[]): { pairs: ChangePair[]; skippedPairs: number } {
  const byId = new Map(records.map((record) => [record.assessment_id, record]))
  const pairs: ChangePair[] = []
  let skippedPairs = 0
  const scored = records.filter(
    (record) => record.is_representative && record.cognitive_index.observed_value !== null,
  )
  for (const record of scored) {
    const previousId = record.previous_comparable_assessment_id
    if (!previousId) {
      const earlier = scored.some(
        (other) =>
          other.assessment_id !== record.assessment_id &&
          other.comparison_segment_key === record.comparison_segment_key &&
          other.source === record.source &&
          other.cognitive_index.version === record.cognitive_index.version &&
          Date.parse(other.observed_at) < Date.parse(record.observed_at),
      )
      if (earlier) skippedPairs += 1
      continue
    }
    const previous = byId.get(previousId)
    const currentValue = record.cognitive_index.observed_value
    const previousValue = previous?.cognitive_index.observed_value
    if (previous && currentValue !== null && previousValue !== null && previousValue !== undefined) {
      pairs.push({ current: record, previous, delta: currentValue - previousValue })
    }
  }
  return { pairs, skippedPairs }
}

export type ScoreBin = { start: number; end: number; label: string; inclusiveEnd: boolean; count: number }

export function histogram(values: readonly number[]): ScoreBin[] {
  const bins: ScoreBin[] = Array.from({ length: 10 }, (_, i) => ({
    start: i * 10,
    end: i === 9 ? 100 : (i + 1) * 10,
    label: i === 9 ? '[90, 100]' : `[${i * 10}, ${i * 10 + 10})`,
    inclusiveEnd: i === 9,
    count: 0,
  }))
  for (const value of values) {
    if (!Number.isFinite(value)) continue
    const index = value >= 100 ? 9 : Math.max(0, Math.min(9, Math.floor(value / 10)))
    bins[index].count += 1
  }
  return bins
}

export function median(values: readonly number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

export function eligibleScores(records: readonly InsightAssessment[]): { record: InsightAssessment; value: number }[] {
  return records
    .filter((record) => record.is_representative && record.cognitive_index.observed_value !== null)
    .map((record) => ({ record, value: record.cognitive_index.observed_value as number }))
}

export function qualityCounts(records: readonly InsightAssessment[]): Record<Quality, number> {
  const counts: Record<Quality, number> = { VALID: 0, LOW: 0, INCOMPLETE: 0 }
  for (const record of records) counts[record.quality_status] += 1
  return counts
}

export const AVAILABILITY_ORDER: Availability[] = [
  'PENDING',
  'BUILDING_BASELINE',
  'INSUFFICIENT_DATA',
  'MODEL_UNAVAILABLE',
  'ANALYSIS_ERROR',
  'COMPLETE',
]

export function availabilityCounts(records: readonly InsightAssessment[]): Record<Availability, number> {
  const counts = Object.fromEntries(AVAILABILITY_ORDER.map((key) => [key, 0])) as Record<Availability, number>
  for (const record of records) counts[record.analysis.availability] += 1
  return counts
}

export type ContextAxis = 'sleep' | 'mood'

export type ContextPoint = {
  record: InsightAssessment
  x: number
  y: number
  medication: boolean | null
}

export function contextPairs(
  records: readonly InsightAssessment[],
  axis: ContextAxis,
): { included: ContextPoint[]; missing: number } {
  const included: ContextPoint[] = []
  let missing = 0
  for (const record of records) {
    if (!record.is_representative || record.cognitive_index.observed_value === null) continue
    const value = axis === 'sleep' ? record.context?.sleep_hours : record.context?.mood_score
    if (value === null || value === undefined) {
      missing += 1
      continue
    }
    included.push({
      record,
      x: value,
      y: record.cognitive_index.observed_value,
      medication: record.context?.medication_change ?? null,
    })
  }
  return { included, missing }
}

export function sourceBreakdown(records: readonly InsightAssessment[]): Record<Source, number> {
  const counts: Record<Source, number> = { LIVE_DEMO: 0, SYNTHETIC_HISTORY: 0, SCENARIO_REPLAY: 0 }
  for (const record of records) counts[record.source] += 1
  return counts
}

export function linkedAlerts(records: readonly InsightAssessment[]) {
  return records.flatMap((record) => (record.linked_alert ? [{ record, alert: record.linked_alert }] : []))
}

export function unresolvedLinkedCount(records: readonly InsightAssessment[]): number {
  return records.filter((record) => record.linked_alert && record.linked_alert.workflow_status !== 'RESOLVED').length
}

export function workflowCounts(records: readonly InsightAssessment[]): Record<WorkflowStatus, number> {
  const counts: Record<WorkflowStatus, number> = { OPEN: 0, ACKNOWLEDGED: 0, RESOLVED: 0 }
  for (const record of records) {
    if (record.linked_alert) counts[record.linked_alert.workflow_status] += 1
  }
  return counts
}

export function summaryStats(data: InsightsResponse) {
  const scored = eligibleScores(data.records)
  return {
    submitted: data.assessment_count,
    eligibleScored: scored.length,
    median: median(scored.map((row) => row.value)),
    unresolvedAlerts: unresolvedLinkedCount(data.records),
  }
}

export type CompareReason = 'INELIGIBLE' | 'UNAVAILABLE' | 'VERSION_MISMATCH' | 'SEGMENT_MISMATCH' | 'SOURCE_MISMATCH'

export function comparability(
  a: InsightAssessment,
  b: InsightAssessment,
): { ok: true } | { ok: false; reason: CompareReason } {
  if (!a.is_representative || !b.is_representative) return { ok: false, reason: 'INELIGIBLE' }
  if (a.cognitive_index.observed_value === null || b.cognitive_index.observed_value === null) {
    return { ok: false, reason: 'UNAVAILABLE' }
  }
  if (a.cognitive_index.version !== b.cognitive_index.version) return { ok: false, reason: 'VERSION_MISMATCH' }
  if (!a.comparison_segment_key || a.comparison_segment_key !== b.comparison_segment_key) {
    return { ok: false, reason: 'SEGMENT_MISMATCH' }
  }
  if (a.source !== b.source) return { ok: false, reason: 'SOURCE_MISMATCH' }
  return { ok: true }
}

export const COMPARE_REASON_TEXT: Record<CompareReason, string> = {
  INELIGIBLE: 'At least one check-in is not a weekly representative.',
  UNAVAILABLE: 'At least one check-in has no available Cognitive Score.',
  VERSION_MISMATCH: 'The two check-ins use different score versions.',
  SEGMENT_MISMATCH: 'The two check-ins are in different comparability segments.',
  SOURCE_MISMATCH: 'The two check-ins come from different sources.',
}

/** Sequential indigo cells for 0–100. Null stays uncolored (patterned in CSS). */
export function sequentialFill(value: number | null): string | undefined {
  if (value === null) return undefined
  const palette = [
    '#eef2ff',
    '#e0e7ff',
    '#c7d2fe',
    '#a5b4fc',
    '#818cf8',
    '#6366f1',
    '#4f46e5',
    '#4338ca',
    '#3730a3',
    '#312e81',
  ]
  return palette[Math.max(0, Math.min(9, Math.floor(value / 10)))]
}

export function elapsedLabel(earlierIso: string, laterIso: string): string {
  const ms = Math.abs(Date.parse(laterIso) - Date.parse(earlierIso))
  const days = Math.round(ms / (24 * 3600 * 1000))
  if (days === 0) return 'same calendar day'
  return `${days} day${days === 1 ? '' : 's'} apart`
}
