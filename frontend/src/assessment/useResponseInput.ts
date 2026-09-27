import { useEffect, useRef } from 'react'
import type { RunRecorder } from './recorder'
import type { InputMode } from './types'

/**
 * One response channel per session: Space in keyboard mode, pointerdown on the response area in
 * pointer mode. Keyboard auto-repeat is ignored; `click` is never used, so a tap cannot count
 * twice. Using the other channel records an input-mode change (and no response).
 */
export function useResponseInput(
  mode: InputMode,
  enabled: boolean,
  onResponse: (timestamp: number) => void,
  recorder: RunRecorder | null,
) {
  const handler = useRef(onResponse)
  useEffect(() => {
    handler.current = onResponse
  }, [onResponse])

  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.code !== 'Space') return
      event.preventDefault()
      if (event.repeat) return
      recorder?.noteInput('keyboard', event.timeStamp)
      if (mode === 'keyboard') handler.current(event.timeStamp)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, mode, recorder])

  /** Spread onto the large response area. */
  const pointerProps = {
    onPointerDown: (event: React.PointerEvent) => {
      if (!enabled) return
      event.preventDefault()
      recorder?.noteInput('pointer', event.timeStamp)
      if (mode === 'pointer') handler.current(event.timeStamp)
    },
  }
  return pointerProps
}
