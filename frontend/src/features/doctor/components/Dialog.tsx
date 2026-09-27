import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Modal dialog (WAI-ARIA APG pattern): accessible name, initial focus, contained Tab focus,
 * Escape closes, focus returns to the element that opened it.
 */
export function Dialog({
  open,
  title,
  onClose,
  initialFocusRef,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  initialFocusRef?: RefObject<HTMLElement | null>
  children: ReactNode
}) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    ;(initialFocusRef?.current ?? panel.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
      } else if (event.key === 'Tab' && panel.current) {
        const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
        if (!items.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus()
    }
  }, [open, initialFocusRef])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-4 sm:items-center">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-lg font-semibold">
            {title}
          </h2>
          <button type="button" onClick={onClose} aria-label="Close dialog" className="rounded p-1 hover:bg-slate-100">
            <X aria-hidden="true" className="h-5 w-5" />
          </button>
        </div>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  )
}
