import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import { cn } from '../lib/utils'

export type StatusState = 'loading' | 'ok' | 'error'

const styles: Record<StatusState, string> = {
  loading: 'bg-slate-100 text-slate-700',
  ok: 'bg-emerald-100 text-emerald-800',
  error: 'bg-rose-100 text-rose-800',
}

export function StatusBadge({ state, label }: { state: StatusState; label: string }) {
  const Icon = state === 'loading' ? LoaderCircle : state === 'ok' ? CircleCheck : CircleAlert
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium',
        styles[state],
      )}
    >
      <Icon aria-hidden="true" className={cn('h-4 w-4', state === 'loading' && 'animate-spin')} />
      {label}
    </span>
  )
}
