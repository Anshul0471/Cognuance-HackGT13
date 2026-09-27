import { describe, expect, it } from 'vitest'
import { ANCHOR, WEEK_MS, forecast, iso, timelineItem } from '../test/fixtures'
import { buildDomainSeries, chronological, reactionAxisMax, timeDomain, weeklyTicks } from './chartSeries'

const ids = (points: { item: { assessment_id: string } }[]) => points.map((p) => p.item.assessment_id)

describe('chart series integrity', () => {
  // Slots 0,1,2 weekly; slot 3 skipped; 4 weekly; LOW retake-less slot 5; 6 weekly; extra in 6;
  // 7 weekly; 8 INCOMPLETE with no memory score; 9 weekly (comparability change starts a segment).
  const items = [
    timelineItem(0),
    timelineItem(1, { forecast: forecast() }),
    timelineItem(2, { forecast: forecast() }),
    timelineItem(4, { forecast: forecast() }),
    timelineItem(5, { quality_status: 'LOW', longitudinal_eligible: false, forecast: forecast() }),
    timelineItem(6, { forecast: forecast('forecast-run-v2-gru', 'policy-v2') }),
    timelineItem(6, {
      assessment_id: 'a-6-extra',
      observed_at: iso(ANCHOR + 6 * WEEK_MS + 5 * 3600 * 1000),
      schedule_purpose: 'EXTRA_ATTEMPT',
      longitudinal_eligible: false,
    }),
    timelineItem(7, { forecast: forecast('forecast-run-v2-gru', 'policy-v2') }),
    timelineItem(8, {
      quality_status: 'INCOMPLETE',
      longitudinal_eligible: false,
      scores: { memory_score: null, attention_score: 80, reaction_time_ms: 600 },
    }),
    timelineItem(9, {
      analysis: { availability: 'INSUFFICIENT_DATA', deviation_level: null, aggregate_deviation: null, persistent_count: null, reason_codes: ['COMPARABILITY_CHANGE'] },
    }),
    timelineItem(10, {
      analysis: { availability: 'COMPLETE', deviation_level: 'REVIEW', aggregate_deviation: 2.6, persistent_count: 1, reason_codes: [] },
      forecast: forecast('forecast-run-v2-gru', 'policy-v2'),
    }),
  ]
  const shuffled = [...items].reverse()
  const memory = buildDomainSeries(shuffled, 'memory')

  it('never joins observed points across a skipped slot, an ineligible or unavailable check-in, or a new segment', () => {
    expect(memory.observedSegments.map(ids)).toEqual([
      ['a-0', 'a-1', 'a-2'], // slot 3 was skipped
      ['a-4'], // LOW check-in at slot 5 follows
      ['a-6'], // extra attempt follows
      ['a-7'], // INCOMPLETE with no memory score follows
      ['a-9', 'a-10'], // comparability change starts a new segment
    ])
  })

  it('keeps low-quality, extra and unavailable check-ins visible as their own categories', () => {
    expect(ids(memory.lowQuality)).toEqual(['a-5'])
    expect(ids(memory.notWeekly)).toEqual(['a-6-extra'])
    expect(memory.unavailableCount).toBe(1)
    const attention = buildDomainSeries(shuffled, 'attention')
    expect(ids(attention.lowQuality)).toEqual(['a-5', 'a-8'])
    expect(attention.unavailableCount).toBe(0)
  })

  it('plots only stored forecasts, at their target time, split on skipped slots and model/policy changes', () => {
    const segments = memory.forecastSegments.map((s) => s.map((p) => p.item.assessment_id))
    expect(segments).toEqual([['a-1', 'a-2'], ['a-4', 'a-5'], ['a-6', 'a-7'], ['a-10']])
    expect(memory.forecastSegments[0][0].x).toBe(ANCHOR + WEEK_MS)
    expect(memory.forecastSegments[0][0].y).toBe(70.2)
    expect(memory.versionChanges).toEqual([
      { x: ANCHOR + 6 * WEEK_MS, from: 'forecast-run-v1-gru · policy-v1', to: 'forecast-run-v2-gru · policy-v2' },
    ])
    expect(memory.forecastCount).toBe(7)
  })

  it('marks flagged check-ins without inventing points', () => {
    expect(ids(memory.flagged)).toEqual(['a-10'])
  })

  it('sorts a copy chronologically without mutating the cached array', () => {
    const before = shuffled.map((i) => i.assessment_id)
    expect(chronological(shuffled)[0].assessment_id).toBe('a-0')
    expect(shuffled.map((i) => i.assessment_id)).toEqual(before)
  })

  it('uses a zero-based reaction-time axis with headroom and a shared time domain covering targets', () => {
    expect(reactionAxisMax([timelineItem(0, { scores: { memory_score: 50, attention_score: 50, reaction_time_ms: 1247.5 } })])).toBe(1500)
    expect(reactionAxisMax([])).toBe(500)
    const [min, max] = timeDomain(items)!
    expect(min).toBeLessThan(ANCHOR)
    expect(max).toBeGreaterThan(ANCHOR + 10 * WEEK_MS)
    expect(timeDomain([])).toBeNull()
  })

  it('places axis ticks on real weekly targets, deduplicated and evenly thinned', () => {
    expect(weeklyTicks(items)).toEqual([0, 1, 2, 4, 5, 6, 7, 8, 9, 10].map((slot) => ANCHOR + slot * WEEK_MS))
    const many = Array.from({ length: 20 }, (_, slot) => timelineItem(slot))
    expect(weeklyTicks(many)).toHaveLength(10)
    expect(weeklyTicks(many)[0]).toBe(ANCHOR)
  })
})
