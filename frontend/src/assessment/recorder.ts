// Timing and telemetry for one scored run, independent of presentation components.
//
// All offsets use performance.now() (monotonic) relative to a single origin captured when the
// session starts. Timer precision and background throttling are platform limits; the backend
// re-derives outcomes from these raw offsets and flags interruptions rather than trusting them.

import type { InputMode, Telemetry } from './types'

type RunTelemetry = Omit<Telemetry, 'viewport' | 'assistance'>

export type RunRecorder = {
  readonly runId: string
  /** Offset (ms) of `performance.now()` or of a DOMHighResTimeStamp such as event.timeStamp. */
  offset: (timestamp?: number) => number
  /** Open a pause interval (patient pressed Pause); returns its start offset. */
  pause: () => number
  /** Close the open pause interval, if any. */
  resume: () => void
  /** Every response-channel press; a channel other than the current one records a mode change. */
  noteInput: (mode: InputMode, timestamp?: number) => void
  telemetry: () => RunTelemetry
  /** Subscribe to the page becoming hidden. Returns an unsubscribe function. */
  onHidden: (listener: () => void) => () => void
  dispose: () => void
}

const round3 = (value: number) => Math.round(value * 1000) / 1000
// Interruptions inside task records share the server's 500-event budget; keep headroom for them.
const INTERRUPTION_HEADROOM = 100

export function createRunRecorder(maxEvents: number, sessionMode: InputMode): RunRecorder {
  const origin = performance.now()
  const budget = Math.max(0, maxEvents - INTERRUPTION_HEADROOM)
  const visibility: RunTelemetry['visibility_events'] = []
  const pauses: RunTelemetry['pause_events'] = []
  const modes: RunTelemetry['mode_changes'] = []
  const hiddenListeners = new Set<() => void>()
  let blurCount = 0
  let overflow = false
  let currentMode = sessionMode

  const offset = (timestamp?: number) => {
    // event.timeStamp shares performance.now()'s origin in current browsers. Some environments
    // report epoch milliseconds instead, so anything not near "now" falls back to performance.now().
    const now = performance.now()
    const plausible = timestamp !== undefined && timestamp > 0 && Math.abs(timestamp - now) < 60_000
    return round3(Math.max(0, (plausible ? timestamp : now) - origin))
  }

  /** Bounded: beyond the budget only the overflow flag is set (the backend then marks tasks LOW). */
  const room = () => {
    if (visibility.length + pauses.length + modes.length >= budget) {
      overflow = true
      return false
    }
    return true
  }

  const onVisibility = () => {
    const state = document.visibilityState === 'hidden' ? 'hidden' : 'visible'
    if (room()) visibility.push({ offset_ms: offset(), state })
    if (state === 'hidden') hiddenListeners.forEach((listener) => listener())
  }
  // blur alone is informational (a warning), not proof the page was hidden.
  const onBlur = () => {
    blurCount = Math.min(blurCount + 1, maxEvents)
  }

  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('blur', onBlur)

  return {
    runId: crypto.randomUUID(),
    offset,
    pause: () => {
      const start = offset()
      const open = pauses.find((p) => p.end_ms === null)
      if (!open && room()) pauses.push({ start_ms: start, end_ms: null })
      return start
    },
    resume: () => {
      const open = pauses.find((p) => p.end_ms === null)
      if (open) open.end_ms = Math.max(open.start_ms, offset())
    },
    noteInput: (mode, timestamp) => {
      if (mode === currentMode) return
      if (room()) modes.push({ offset_ms: offset(timestamp), from: currentMode, to: mode })
      currentMode = mode
    },
    telemetry: () => ({
      initial_input_mode: sessionMode,
      final_input_mode: currentMode,
      visibility_events: visibility.slice(),
      pause_events: pauses.map((p) => ({ ...p })),
      blur_count: blurCount,
      mode_changes: modes.slice(),
      event_overflow: overflow,
    }),
    onHidden: (listener) => {
      hiddenListeners.add(listener)
      return () => hiddenListeners.delete(listener)
    },
    dispose: () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('blur', onBlur)
      hiddenListeners.clear()
    },
  }
}
