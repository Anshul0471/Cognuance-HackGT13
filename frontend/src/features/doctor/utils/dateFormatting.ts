// Patient-history dates are shown in the patient's IANA time zone (never the browser's implicitly).
// Stored/sent instants stay UTC. Built on Intl only; no date library is installed.

const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/

export function safeZone(timeZone: string): string {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone })
    return timeZone
  } catch {
    return 'UTC'
  }
}

export function formatInZone(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: safeZone(timeZone),
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

export function formatDateInZone(ms: number, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, { timeZone: safeZone(timeZone), month: 'short', day: 'numeric' }).format(
    new Date(ms),
  )
}

/** Local time for doctor-workflow events (review history), labelled as the viewer's time. */
export function formatLocal(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Offset (ms) of `timeZone` from UTC at the given instant. */
function zoneOffset(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instant))
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
  return asUtc - Math.floor(instant / 1000) * 1000
}

export function isDateString(value: string): boolean {
  const m = DATE_RE.exec(value)
  if (!m) return false
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const date = new Date(Date.UTC(y, mo - 1, d))
  return date.getUTCFullYear() === y && date.getUTCMonth() === mo - 1 && date.getUTCDate() === d
}

/** UTC ISO instant of local midnight at the start of `date` (YYYY-MM-DD) in `timeZone`. */
export function zonedStartOfDayUtc(date: string, timeZone: string): string {
  if (!isDateString(date)) throw new RangeError(`Invalid date: ${date}`)
  const zone = safeZone(timeZone)
  const [y, m, d] = date.split('-').map(Number)
  const guess = Date.UTC(y, m - 1, d)
  let instant = guess - zoneOffset(guess, zone)
  const corrected = guess - zoneOffset(instant, zone)
  if (corrected !== instant) instant = corrected
  return new Date(instant).toISOString()
}

export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** Calendar date (YYYY-MM-DD) of `instant` in `timeZone`. */
export function todayInZone(timeZone: string, instant = Date.now()): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: safeZone(timeZone),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date(instant))
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00'
  return `${get('year')}-${get('month')}-${get('day')}`
}

/** Inclusive last-N local days → API `{from, to}` (from inclusive, to exclusive). */
export function lastDaysUtcRange(days: number, timeZone: string, instant = Date.now()): { from: string; to: string } {
  const today = todayInZone(timeZone, instant)
  return {
    from: zonedStartOfDayUtc(addDays(today, -(days - 1)), timeZone),
    to: zonedStartOfDayUtc(addDays(today, 1), timeZone),
  }
}

/** Inclusive local calendar date of an exclusive UTC `to` bound. */
export function exclusiveToInclusiveDate(iso: string, timeZone: string): string {
  return addDays(todayInZone(timeZone, Date.parse(iso)), -1)
}

export type RangeInput = { from: string; to: string }
export type RangeResult = { ok: true; range: { from?: string; to?: string } } | { ok: false; error: string }

/**
 * Patient-local inclusive dates → API range (`from` inclusive, `to` exclusive = the day after).
 * Invalid or reversed ranges are rejected before any request is made.
 */
export function toApiRange(input: RangeInput, timeZone: string): RangeResult {
  const from = input.from.trim()
  const to = input.to.trim()
  if ((from && !isDateString(from)) || (to && !isDateString(to))) return { ok: false, error: 'Enter dates as YYYY-MM-DD.' }
  if (from && to && from > to) return { ok: false, error: 'The start date must be on or before the end date.' }
  return {
    ok: true,
    range: {
      from: from ? zonedStartOfDayUtc(from, timeZone) : undefined,
      to: to ? zonedStartOfDayUtc(addDays(to, 1), timeZone) : undefined,
    },
  }
}
