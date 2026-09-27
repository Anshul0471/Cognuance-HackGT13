import type { TimelineItem } from '../schemas'

// Pure chart transformations. Nothing here classifies deviations or infers eligibility: those come
// from the backend. These functions only decide which stored points may be joined by a line.

export type ChartDomain = 'memory' | 'attention' | 'reaction_time_ms'

export const OBSERVED_FIELD = {
  memory: 'memory_score',
  attention: 'attention_score',
  reaction_time_ms: 'reaction_time_ms',
} as const

export const FORECAST_FIELD = {
  memory: 'predicted_memory_score',
  attention: 'predicted_attention_score',
  reaction_time_ms: 'predicted_reaction_time_ms',
} as const

const WEEK_MS = 7 * 24 * 3600 * 1000
const SLOT_TOLERANCE_MS = 3600 * 1000
const SEGMENT_START_REASONS = new Set(['COMPARABILITY_CHANGE', 'PROTOCOL_MISMATCH'])

/** weekly = eligible weekly representative; lowQuality = LOW/INCOMPLETE; notWeekly = valid but ineligible. */
export type PointKind = 'weekly' | 'lowQuality' | 'notWeekly'

export type ObservedPoint = {
  x: number
  y: number
  kind: PointKind
  flagged: boolean
  item: TimelineItem
}

export type ForecastPoint = { x: number; y: number; item: TimelineItem; version: string }

export type VersionChange = { x: number; from: string; to: string }

export type DomainSeries = {
  observedSegments: ObservedPoint[][]
  lowQuality: ObservedPoint[]
  notWeekly: ObservedPoint[]
  flagged: ObservedPoint[]
  forecastSegments: ForecastPoint[][]
  versionChanges: VersionChange[]
  /** Loaded assessments with no observed value for this domain (unavailable, never zero). */
  unavailableCount: number
  forecastCount: number
}

const t = (iso: string) => Date.parse(iso)

/** Oldest first by observation time, then ID; returns a copy (the query cache is never mutated). */
export function chronological(items: readonly TimelineItem[]): TimelineItem[] {
  return [...items].sort(
    (a, b) => t(a.observed_at) - t(b.observed_at) || a.assessment_id.localeCompare(b.assessment_id),
  )
}

function consecutiveSlots(earlier: TimelineItem, later: TimelineItem): boolean {
  return Math.abs(t(later.target_at) - t(earlier.target_at) - WEEK_MS) <= SLOT_TOLERANCE_MS
}

function isFlagged(item: TimelineItem): boolean {
  const level = item.analysis.deviation_level
  return level !== null && level !== 'NORMAL'
}

export function versionOf(item: TimelineItem): string | null {
  return item.forecast ? `${item.forecast.model_version} · ${item.forecast.policy_version}` : null
}

/** How a series reads its values, so the composite and the task charts share one rule set. */
type Accessors = {
  observed: (item: TimelineItem) => number | null
  forecast: (item: TimelineItem) => number | null
  /** Forecast-line identity: a change starts a new segment and a version marker. */
  forecastVersion: (item: TimelineItem) => string | null
}

const domainAccessors = (domain: ChartDomain): Accessors => ({
  observed: (item) => item.scores[OBSERVED_FIELD[domain]],
  forecast: (item) => item.forecast?.[FORECAST_FIELD[domain]] ?? null,
  forecastVersion: versionOf,
})

/**
 * Composite `cognitive_index_v1` series. The projection can be unavailable even when a forecast
 * row exists, and the score version joins the forecast-line identity so a future
 * `cognitive_index_v2` cannot be drawn as one uninterrupted line.
 */
const compositeAccessors: Accessors = {
  observed: (item) => item.cognitive_index.observed_value,
  forecast: (item) => item.cognitive_index.forecast_value,
  forecastVersion: (item) =>
    item.cognitive_index.forecast_value === null
      ? null
      : `${versionOf(item) ?? 'unknown model'} · ${item.cognitive_index.version}`,
}

export function buildDomainSeries(items: readonly TimelineItem[], domain: ChartDomain): DomainSeries {
  return buildSeries(items, domainAccessors(domain))
}

export function buildCompositeSeries(items: readonly TimelineItem[]): DomainSeries {
  return buildSeries(items, compositeAccessors)
}

function buildSeries(items: readonly TimelineItem[], accessors: Accessors): DomainSeries {
  const sorted = chronological(items)
  const out: DomainSeries = {
    observedSegments: [],
    lowQuality: [],
    notWeekly: [],
    flagged: [],
    forecastSegments: [],
    versionChanges: [],
    unavailableCount: 0,
    forecastCount: 0,
  }

  // Observed: join only consecutive weekly representatives with nothing ineligible/unavailable between.
  let segment: ObservedPoint[] = []
  let previous: TimelineItem | null = null
  let interrupted = false
  const close = () => {
    if (segment.length) out.observedSegments.push(segment)
    segment = []
  }
  for (const item of sorted) {
    const value = accessors.observed(item)
    if (value === null) {
      out.unavailableCount += 1
      interrupted = true
      continue
    }
    const kind: PointKind = item.longitudinal_eligible
      ? 'weekly'
      : item.quality_status === 'VALID'
        ? 'notWeekly'
        : 'lowQuality'
    const point: ObservedPoint = { x: t(item.observed_at), y: value, kind, flagged: isFlagged(item), item }
    if (point.flagged) out.flagged.push(point)
    if (kind !== 'weekly') {
      out[kind].push(point)
      interrupted = true
      continue
    }
    const startsSegment = item.analysis.reason_codes.some((code) => SEGMENT_START_REASONS.has(code))
    if (interrupted || startsSegment || previous === null || !consecutiveSlots(previous, item)) close()
    segment.push(point)
    previous = item
    interrupted = false
  }
  close()

  // Forecasts: plotted at their target time; joined only for consecutive slots under one model/policy.
  const forecasts = sorted
    .filter((item) => accessors.forecast(item) !== null)
    .sort((a, b) => t(a.target_at) - t(b.target_at) || t(a.observed_at) - t(b.observed_at))
  let fSegment: ForecastPoint[] = []
  let fPrevious: ForecastPoint | null = null
  for (const item of forecasts) {
    const point: ForecastPoint = {
      x: t(item.target_at),
      y: accessors.forecast(item)!,
      item,
      version: accessors.forecastVersion(item) ?? 'unknown',
    }
    out.forecastCount += 1
    const versionChanged = fPrevious !== null && fPrevious.version !== point.version
    if (versionChanged) out.versionChanges.push({ x: point.x, from: fPrevious!.version, to: point.version })
    if (fPrevious === null || versionChanged || !consecutiveSlots(fPrevious.item, item)) {
      if (fSegment.length) out.forecastSegments.push(fSegment)
      fSegment = []
    }
    fSegment.push(point)
    fPrevious = point
  }
  if (fSegment.length) out.forecastSegments.push(fSegment)
  return out
}

/** Shared x-axis domain (ms) over every loaded observation and forecast target, padded. */
export function timeDomain(items: readonly TimelineItem[]): [number, number] | null {
  const xs = items.flatMap((item) => [t(item.observed_at), ...(item.forecast ? [t(item.target_at)] : [])])
  if (!xs.length) return null
  const min = Math.min(...xs)
  const max = Math.max(...xs)
  const pad = Math.max((max - min) * 0.04, 2 * 24 * 3600 * 1000)
  return [min - pad, max + pad]
}

/** X-axis ticks at the loaded weekly target times, thinned evenly to at most `max`. */
// Recharts' own time ticks ignore the patient's time zone; these are real slot targets.
export function weeklyTicks(items: readonly TimelineItem[], max = 10): number[] {
  const targets = [...new Set(items.map((item) => t(item.target_at)))].sort((a, b) => a - b)
  if (targets.length <= max) return targets
  const step = Math.ceil(targets.length / max)
  return targets.filter((_, i) => i % step === 0)
}

/** Zero-based reaction-time axis with headroom above the largest loaded finite value. */
export function reactionAxisMax(items: readonly TimelineItem[]): number {
  const values = items.flatMap((item) => [
    item.scores.reaction_time_ms,
    item.forecast?.predicted_reaction_time_ms ?? null,
  ])
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v))
  const max = finite.length ? Math.max(...finite) : 0
  return Math.max(500, Math.ceil((max * 1.2) / 100) * 100)
}
