import { describe, expect, it } from 'vitest'
import { addDays, exclusiveToInclusiveDate, lastDaysUtcRange, todayInZone, toApiRange, zonedStartOfDayUtc } from './dateFormatting'

describe('patient-local date ranges', () => {
  it('converts a local calendar day to the UTC instant of its midnight', () => {
    expect(zonedStartOfDayUtc('2026-07-15', 'America/New_York')).toBe('2026-07-15T04:00:00.000Z') // EDT
    expect(zonedStartOfDayUtc('2026-12-15', 'America/New_York')).toBe('2026-12-15T05:00:00.000Z') // EST
    expect(zonedStartOfDayUtc('2026-09-26', 'Asia/Kolkata')).toBe('2026-09-25T18:30:00.000Z')
    expect(zonedStartOfDayUtc('2026-03-08', 'America/New_York')).toBe('2026-03-08T05:00:00.000Z') // DST day
    expect(zonedStartOfDayUtc('2026-09-26', 'UTC')).toBe('2026-09-26T00:00:00.000Z')
  })

  it('sends an inclusive start and an exclusive end (the next local midnight)', () => {
    const result = toApiRange({ from: '2026-09-01', to: '2026-09-30' }, 'America/New_York')
    expect(result).toEqual({
      ok: true,
      range: { from: '2026-09-01T04:00:00.000Z', to: '2026-10-01T04:00:00.000Z' },
    })
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
  })

  it('rejects reversed or malformed ranges before any request', () => {
    expect(toApiRange({ from: '2026-09-30', to: '2026-09-01' }, 'UTC').ok).toBe(false)
    expect(toApiRange({ from: '2026-02-30', to: '' }, 'UTC').ok).toBe(false)
    expect(toApiRange({ from: '', to: '' }, 'UTC')).toEqual({ ok: true, range: { from: undefined, to: undefined } })
  })

  it('builds last-N-day presets from the patient-local calendar, inclusive of today', () => {
    const now = Date.parse('2026-09-26T20:00:00Z')
    expect(todayInZone('America/New_York', now)).toBe('2026-09-26')
    expect(lastDaysUtcRange(90, 'America/New_York', now)).toEqual({
      from: zonedStartOfDayUtc('2026-06-29', 'America/New_York'),
      to: zonedStartOfDayUtc('2026-09-27', 'America/New_York'),
    })
    expect(exclusiveToInclusiveDate('2026-09-27T04:00:00.000Z', 'America/New_York')).toBe('2026-09-26')
  })
})
