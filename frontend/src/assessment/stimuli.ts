import type { ResponseEvent, Shape } from './types'

// Shapes differ by form (and label), never by colour alone.
export const SHAPE_SVG: Record<Shape, string> = {
  circle:
    '<svg viewBox="0 0 100 100" width="160" height="160" aria-hidden="true"><circle cx="50" cy="50" r="42" fill="#1e293b"/></svg>',
  square:
    '<svg viewBox="0 0 100 100" width="160" height="160" aria-hidden="true"><rect x="10" y="10" width="80" height="80" fill="#1e293b"/></svg>',
  triangle:
    '<svg viewBox="0 0 100 100" width="160" height="160" aria-hidden="true"><polygon points="50,6 95,92 5,92" fill="#1e293b"/></svg>',
}

export const SHAPE_LABEL: Record<Shape, string> = { circle: 'Circle', square: 'Square', triangle: 'Triangle' }

export function formatMs(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

/** Append a response offset, bounded per trial; beyond the limit only an overflow flag is set. */
export function addResponse(
  trial: { responses: ResponseEvent[]; event_overflow: boolean },
  offsetMs: number,
  maxEvents: number,
): boolean {
  if (trial.responses.length >= maxEvents) {
    trial.event_overflow = true
    return false
  }
  trial.responses.push({ offset_ms: offsetMs })
  return true
}
