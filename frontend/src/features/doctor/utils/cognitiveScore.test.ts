import { describe, expect, it } from 'vitest'
import { timelineItem } from '../test/fixtures'
import { scoreHeadline } from './cognitiveScore'

describe('cognitive score headline', () => {
  it('reports change only across adjacent eligible weekly points in one segment', () => {
    const items = [timelineItem(0), timelineItem(1), timelineItem(2)]
    const headline = scoreHeadline(items)
    expect(headline.latest?.assessment_id).toBe('a-2')
    expect(headline.latestWithScore?.item.assessment_id).toBe('a-2')
    expect(headline.previousComparable?.item.assessment_id).toBe('a-1')
    expect(headline.changePoints).not.toBeNull()
  })

  it('does not invent a change across a skipped week or an ineligible extra', () => {
    const gapped = scoreHeadline([timelineItem(0), timelineItem(2)])
    expect(gapped.previousComparable).toBeNull()
    expect(gapped.changePoints).toBeNull()

    const extraLatest = scoreHeadline([
      timelineItem(0),
      timelineItem(1, {
        assessment_id: 'a-extra',
        observed_at: '2026-08-16T18:00:00.000Z',
        schedule_purpose: 'EXTRA_ATTEMPT',
        longitudinal_eligible: false,
      }),
    ])
    expect(extraLatest.latest?.assessment_id).toBe('a-extra')
    expect(extraLatest.latestWithScore?.item.assessment_id).toBe('a-extra')
    expect(extraLatest.changePoints).toBeNull()
  })

  it('keeps an unavailable latest assessment visible and falls back to the last available score', () => {
    const incomplete = timelineItem(2, {
      quality_status: 'INCOMPLETE',
      longitudinal_eligible: false,
      scores: { memory_score: null, attention_score: 80, reaction_time_ms: null },
    })
    const headline = scoreHeadline([timelineItem(0), incomplete])
    expect(headline.latest?.assessment_id).toBe(incomplete.assessment_id)
    expect(headline.latest?.cognitive_index.observed_value).toBeNull()
    expect(headline.latestWithScore?.item.assessment_id).toBe('a-0')
  })
})
