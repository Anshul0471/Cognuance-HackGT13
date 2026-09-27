import type { ChartDomain } from './chartSeries'

// Display-only rounding: one decimal for score points, whole milliseconds for reaction time.
// Raw precision is kept everywhere else. `null` is shown as unavailable, never as zero.

const oneDecimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 0 })
const indexDecimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const twoDecimals = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

export function formatDomainValue(domain: ChartDomain, value: number | null | undefined): string {
  if (value === null || value === undefined) return 'Unavailable'
  return domain === 'reaction_time_ms' ? `${Math.round(value)} ms` : `${oneDecimal.format(value)} pts`
}

/** Signed actual-minus-predicted difference with its unit (points, not percent). */
export function formatDifference(domain: ChartDomain, value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±'
  const magnitude = Math.abs(value)
  return domain === 'reaction_time_ms'
    ? `${sign}${Math.round(magnitude)} ms`
    : `${sign}${oneDecimal.format(magnitude)} points`
}

export function formatRatio(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : twoDecimals.format(value)
}

/** Composite score: one decimal and an explicit `/100` (never a percent sign). */
export function formatIndex(value: number | null | undefined): string {
  return value === null || value === undefined ? 'Unavailable' : `${indexDecimal.format(value)} / 100`
}

export function formatPoints(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±'
  return `${sign}${oneDecimal.format(Math.abs(value))} points`
}

export const DOMAIN_UNIT: Record<ChartDomain, string> = {
  memory: 'points (0–100)',
  attention: 'points (0–100)',
  reaction_time_ms: 'milliseconds',
}
