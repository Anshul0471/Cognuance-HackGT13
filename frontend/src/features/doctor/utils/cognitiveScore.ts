import type { CognitiveIndexMetadata, TimelineItem } from '../schemas'
import { buildCompositeSeries, type ObservedPoint } from './chartSeries'

// Presentation helpers for the composite `cognitive_index_v1`. The backend owns the formula; this
// module only selects which stored values to show and how to phrase them.

export const SCORE_TITLE = 'Cognitive Score'
export const SCORE_SUBTITLE = 'Prototype task-performance index · 0–100'

export type ScoreHeadline = {
  /** The newest loaded assessment, whether or not it has a composite. */
  latest: TimelineItem | null
  /** The newest loaded assessment that has a composite (may be older than `latest`). */
  latestWithScore: ObservedPoint | null
  /** Its adjacent comparable predecessor, when the two sit in the same unbroken segment. */
  previousComparable: ObservedPoint | null
  changePoints: number | null
}

/**
 * Pick the headline values. "Previous comparable" reuses the chart's own segmentation, so a
 * change is only ever reported across two adjacent eligible weekly points in one segment; a gap,
 * an ineligible check-in or a comparability change in between leaves it null.
 */
export function scoreHeadline(items: readonly TimelineItem[]): ScoreHeadline {
  const byNewest = [...items].sort(
    (a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at) || b.assessment_id.localeCompare(a.assessment_id),
  )
  const segments = buildCompositeSeries(items).observedSegments
  let latestWithScore: ObservedPoint | null = null
  let previousComparable: ObservedPoint | null = null
  for (const segment of segments) {
    const last = segment[segment.length - 1]
    if (!latestWithScore || last.x > latestWithScore.x) {
      latestWithScore = last
      previousComparable = segment.length > 1 ? segment[segment.length - 2] : null
    }
  }
  // Extras and other ineligible check-ins can still carry a descriptive score, but never a change.
  const ineligibleLatest = [...items]
    .filter((item) => item.cognitive_index.observed_value !== null && !item.longitudinal_eligible)
    .sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at))[0]
  if (ineligibleLatest && (!latestWithScore || Date.parse(ineligibleLatest.observed_at) > latestWithScore.x)) {
    latestWithScore = {
      x: Date.parse(ineligibleLatest.observed_at),
      y: ineligibleLatest.cognitive_index.observed_value!,
      kind: ineligibleLatest.quality_status === 'VALID' ? 'notWeekly' : 'lowQuality',
      flagged: false,
      item: ineligibleLatest,
    }
    previousComparable = null
  }
  return {
    latest: byNewest[0] ?? null,
    latestWithScore,
    previousComparable,
    changePoints:
      latestWithScore && previousComparable ? latestWithScore.y - previousComparable.y : null,
  }
}

/** Plain-language formula description, built from the server's own metadata. */
export function formulaSummary(meta: CognitiveIndexMetadata): string {
  const floor = Math.round(meta.reaction_time_floor_ms)
  const ceiling = Math.round(meta.reaction_time_ceiling_ms)
  return (
    `Response speed = 100 × (${ceiling} − reaction time in ms) ÷ (${ceiling} − ${floor}), limited to 0–100. ` +
    `Cognitive Score = (memory + attention + response speed) ÷ 3.`
  )
}

export const SCORE_CAVEATS = [
  'A project-defined display summary of the three task results — not a clinically validated test, disease stage, probability or risk score.',
  'Each task carries exactly one third of the weight: a transparent prototype choice, not learned or medically established importance.',
  'The reaction-time anchors come from this prototype’s response window, so they are display-normalization limits, not clinical norms. Differences among fast responses compress; the milliseconds chart below keeps them visible.',
  'Sleep, mood and medication reports never add or subtract points; they remain separate context.',
  'Each value describes one check-in. Scores are never added up across visits, so more check-ins cannot raise the score.',
  'Alerts continue to use the per-domain rules. A steady composite can hide opposing changes and never cancels a flag.',
]
