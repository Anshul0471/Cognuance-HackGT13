import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { StatusBadge, type StatusState } from '../components/StatusBadge'
import { api, ApiError } from '../lib/api'
import { useDocumentTitle } from '../lib/useDocumentTitle'

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.isNetworkError ? 'Backend unreachable' : `HTTP ${error.status}`
  }
  return 'Unexpected error'
}

function StatusCard({
  title,
  state,
  label,
  children,
}: {
  title: string
  state: StatusState
  label: string
  children?: ReactNode
}) {
  return (
    <section
      aria-label={title}
      className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>
        <StatusBadge state={state} label={label} />
      </div>
      {children && <div className="mt-3 text-sm text-slate-600">{children}</div>}
    </section>
  )
}

const READY_TEXT: Record<string, string> = {
  DATABASE_UNAVAILABLE: 'Database unreachable',
  MIGRATIONS_NOT_CURRENT: 'Database schema is not at the expected migration (run alembic upgrade head)',
}

export function SetupStatusPage() {
  useDocumentTitle('System status')
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const ready = useQuery({ queryKey: ['ready'], queryFn: api.ready, retry: false })
  const model = useQuery({ queryKey: ['model-status'], queryFn: api.modelStatus, retry: false })
  const readyCode = ready.error instanceof ApiError ? ready.error.code : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Development setup status</h1>
        <p className="mt-1 text-slate-600">
          Live infrastructure checks from the backend. This does not mean the clinical workflow or
          model is ready.
        </p>
      </div>

      <StatusCard
        title="API health"
        state={health.isPending ? 'loading' : health.isSuccess ? 'ok' : 'error'}
        label={health.isPending ? 'Checking' : health.isSuccess ? 'Alive' : errorText(health.error)}
      />

      <StatusCard
        title="Readiness (database + migrations)"
        state={ready.isPending ? 'loading' : ready.isSuccess ? 'ok' : 'error'}
        label={ready.isPending ? 'Checking' : ready.isSuccess ? 'Ready' : 'Unavailable'}
      >
        {ready.isError && <p>{(readyCode && READY_TEXT[readyCode]) ?? errorText(ready.error)}</p>}
      </StatusCard>

      <StatusCard
        title="Forecasting model"
        state={model.isPending ? 'loading' : model.data?.forecast_ready ? 'ok' : 'error'}
        label={
          model.isPending
            ? 'Checking'
            : model.isError
              ? errorText(model.error)
              : model.data?.forecast_ready
                ? 'Ready'
                : 'Not ready'
        }
      >
        {model.data && (
          <ul className="space-y-1">
            <li>
              {model.data.model_kind
                ? `Active: ${model.data.model_kind} ${model.data.model_version} · policy ${model.data.policy_version ?? 'none'}`
                : 'No active model'}
            </li>
            <li>
              Model loaded: {model.data.model_loaded ? 'yes' : 'no'} · policy ready:{' '}
              {model.data.policy_ready ? 'yes' : 'no'}
            </li>
            {model.data.reason_code && <li>Unavailable reason: {model.data.reason_code}</li>}
          </ul>
        )}
      </StatusCard>
    </div>
  )
}
