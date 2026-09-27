import { useEffect, useRef } from 'react'

/**
 * Ref that always holds the latest value. Lets task callbacks stay referentially stable even when
 * a parent re-renders with a new inline `onFinish` (e.g. every second for the session timer);
 * otherwise effects depending on those callbacks would restart their timers indefinitely.
 */
export function useLatest<T>(value: T) {
  const ref = useRef(value)
  useEffect(() => {
    ref.current = value
  })
  return ref
}
