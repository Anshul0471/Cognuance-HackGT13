import { useEffect } from 'react'
import { pageTitle } from '../config/brand'

/** Sets `COGNUANCE | <section>` without moving focus (safe to call on polled pages). */
export function useDocumentTitle(section: string) {
  useEffect(() => {
    document.title = pageTitle(section)
  }, [section])
}
