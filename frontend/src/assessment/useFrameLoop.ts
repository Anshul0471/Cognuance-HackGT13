import { useEffect, useRef } from 'react'

/**
 * Runs `onFrame(timestamp)` on every animation frame while `active`. All task state lives in refs,
 * so React Strict Mode's mount→unmount→mount only cancels and resumes the loop; it never restarts
 * a trial or records a timestamp twice. The frame timestamp shares performance.now()'s timebase.
 */
export function useFrameLoop(active: boolean, onFrame: (timestamp: number) => void) {
  const callback = useRef(onFrame)
  useEffect(() => {
    callback.current = onFrame
  }, [onFrame])

  useEffect(() => {
    if (!active) return
    let id = 0
    const tick = (timestamp: number) => {
      callback.current(timestamp)
      id = requestAnimationFrame(tick)
    }
    id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [active])
}
