import { describe, expect, it } from 'vitest'
import { insightRecord } from '../test/fixtures'
import {
  changePairs,
  comparability,
  contextPairs,
  eligibleScores,
  heatmapColumns,
  histogram,
  median,
  qualityCounts,
  summaryStats,
} from './insightPresentation'
import { insightsResponse } from '../test/fixtures'

describe('insight presentation', () => {
  it('puts 0 in the first bin, 100 in the last, and never bins a null', () => {
    const bins = histogram([0, 9.9, 10, 100])
    expect(bins[0]).toMatchObject({ start: 0, count: 2 })
    expect(bins[1]).toMatchObject({ start: 10, count: 1 })
    expect(bins[9]).toMatchObject({ start: 90, end: 100, count: 1 })
    expect(histogram([]).every((bin) => bin.count === 0)).toBe(true)
    expect(histogram([Number.NaN]).every((bin) => bin.count === 0)).toBe(true)
  })

  it('reports a median only from included scores and an em-dash-ready null when empty', () => {
    expect(median([10, 20, 30])).toBe(20)
    expect(median([10, 20])).toBe(15)
    expect(median([])).toBeNull()
  })

  it('builds change bars only from backend predecessor IDs inside the filtered range', () => {
    const a0 = insightRecord(0)
    const a1 = insightRecord(1, { previous_comparable_assessment_id: a0.assessment_id })
    const a3 = insightRecord(3) // gap: no predecessor
    const extra = insightRecord(3, {
      assessment_id: 'a-extra',
      schedule_purpose: 'EXTRA_ATTEMPT',
      longitudinal_eligible: false,
      is_representative: false,
    })
    const { pairs, skippedPairs } = changePairs([a0, a1, extra, a3])
    expect(pairs).toHaveLength(1)
    expect(pairs[0].current.assessment_id).toBe(a1.assessment_id)
    expect(pairs[0].previous.assessment_id).toBe(a0.assessment_id)
    expect(skippedPairs).toBe(1)
    expect(eligibleScores([a0, a1, extra, a3])).toHaveLength(3)
  })

  it('keeps extras out of the heatmap columns and marks unusable cells as empty, not zero', () => {
    const weekly = insightRecord(0)
    const low = insightRecord(1, { quality_status: 'LOW', longitudinal_eligible: false, is_representative: false })
    const extra = insightRecord(1, {
      assessment_id: 'a-extra',
      schedule_purpose: 'EXTRA_ATTEMPT',
      longitudinal_eligible: false,
      is_representative: false,
    })
    const { columns, extras } = heatmapColumns([weekly, low, extra])
    expect(columns.map((c) => c.assessmentId)).toEqual([weekly.assessment_id, low.assessment_id])
    expect(columns[0]?.usable).toBe(true)
    expect(columns[1]?.usable).toBe(false)
    expect(columns[1]?.memory).toBeNull()
    expect(extras.map((r) => r.assessment_id)).toEqual(['a-extra'])
  })

  it('counts quality over every submitted assessment and excludes missing context from the scatter', () => {
    const withContext = insightRecord(0)
    const missingSleep = insightRecord(1, {
      context: {
        sleep_hours: null,
        mood_score: 6,
        medication_change: null,
        reported_by: 'PATIENT',
        missing_fields: { sleep_hours: 'SKIPPED' },
      },
    })
    const low = insightRecord(2, { quality_status: 'LOW', longitudinal_eligible: false, is_representative: false })
    const records = [withContext, missingSleep, low]
    expect(qualityCounts(records)).toEqual({ VALID: 2, LOW: 1, INCOMPLETE: 0 })
    const sleep = contextPairs(records, 'sleep')
    expect(sleep.included).toHaveLength(1)
    expect(sleep.missing).toBe(1)
    const mood = contextPairs(records, 'mood')
    expect(mood.included).toHaveLength(2)
    expect(summaryStats(insightsResponse(records))).toMatchObject({
      submitted: 3,
      eligibleScored: 2,
    })
  })

  it('allows pin-comparison differences only when both visits are comparable', () => {
    const live = insightRecord(0, { source: 'LIVE_DEMO' })
    const synthetic = insightRecord(1, { source: 'SYNTHETIC_HISTORY' })
    const extra = insightRecord(2, {
      schedule_purpose: 'EXTRA_ATTEMPT',
      longitudinal_eligible: false,
      is_representative: false,
    })
    expect(comparability(live, insightRecord(3, { source: 'LIVE_DEMO' }))).toEqual({ ok: true })
    expect(comparability(live, synthetic)).toEqual({ ok: false, reason: 'SOURCE_MISMATCH' })
    expect(comparability(live, extra)).toEqual({ ok: false, reason: 'INELIGIBLE' })
  })
})
