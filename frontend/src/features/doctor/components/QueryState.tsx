import { Copy, LoaderCircle, RefreshCw, ShieldOff, WifiOff } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { ApiError } from '../../../lib/api'
import { formatLocal } from '../utils/dateFormatting'
import { describeError } from '../utils/errorText'

export function Loading({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-slate-600">
      <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
      {label}
    </p>
  )
}

export function RequestId({ id }: { id: string | null }) {
  const [copied, setCopied] = useState(false)
  if (!id) return null
  const copy = () => {
    void navigator.clipboard?.writeText(id).then(() => setCopied(true), () => undefined)
  }
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-600">
      Request ID <code className="break-all rounded bg-slate-100 px-1 py-0.5">{id}</code>
      <button type="button" onClick={copy} className="inline-flex items-center gap-1 rounded px-1.5 py-1 underline">
        <Copy aria-hidden="true" className="h-3 w-3" />
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

export function ErrorState({ error, onRetry, children }: { error: unknown; onRetry?: () => void; children?: ReactNode }) {
  const access = error instanceof ApiError && (error.status === 403 || error.status === 404)
  const Icon = access ? ShieldOff : WifiOff
  return (
    <div role="alert" className="rounded-lg border border-slate-300 bg-white p-4 text-slate-800">
      <p className="flex items-start gap-2">
        <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
        <span>{describeError(error)}</span>
      </p>
      {children}
      {error instanceof ApiError && <RequestId id={error.requestId} />}
      {onRetry && !access && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
        >
          <RefreshCw aria-hidden="true" className="h-4 w-4" />
          Try again
        </button>
      )}
    </div>
  )
}

/** Shown when a background refresh failed but earlier same-user data is still displayed. */
export function StaleNotice({
  error,
  updatedAt,
  onRefresh,
}: {
  error: unknown
  updatedAt: number
  onRefresh: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950">
      <span>
        <strong>May be out of date.</strong> {describeError(error)} Showing data from{' '}
        {formatLocal(new Date(updatedAt).toISOString())}.
      </span>
      <button type="button" onClick={onRefresh} className="inline-flex items-center gap-1 font-semibold underline">
        <RefreshCw aria-hidden="true" className="h-3.5 w-3.5" />
        Refresh
      </button>
      {error instanceof ApiError && <RequestId id={error.requestId} />}
    </div>
  )
}

export function LastRefreshed({ at }: { at: number }) {
  if (!at) return null
  return <span className="text-xs text-slate-500">Last refreshed {formatLocal(new Date(at).toISOString())}</span>
}
