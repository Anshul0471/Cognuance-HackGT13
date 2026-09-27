import { useId } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { AlertStatusFilter } from '../api'
import { AlertWorkflowBadge, DeviationBadge } from '../components/Badges'
import { ErrorState, LastRefreshed, Loading, StaleNotice } from '../components/QueryState'
import { UNAVAILABLE_TEXT } from '../utils/errorText'
import { isAccessLost, mergePages, useAlerts, usePatients } from '../queries'
import { flaggedLevel, workflowStatus, type DeviationLevel } from '../schemas'
import { formatLocal } from '../utils/dateFormatting'
import { DEVIATION_LABEL, DOMAIN_LABEL } from '../utils/displayLabels'

const STATUS_OPTIONS: { value: AlertStatusFilter; label: string }[] = [
  { value: 'UNRESOLVED', label: 'Unresolved (open or acknowledged)' },
  { value: 'OPEN', label: 'Open' },
  { value: 'ACKNOWLEDGED', label: 'Acknowledged' },
  { value: 'RESOLVED', label: 'Resolved' },
  { value: 'ALL', label: 'All statuses' },
]

function parseStatus(value: string | null): AlertStatusFilter {
  if (value === 'ALL') return 'ALL'
  const parsed = workflowStatus.safeParse(value)
  return parsed.success ? parsed.data : 'UNRESOLVED'
}

function parseLevel(value: string | null): DeviationLevel | undefined {
  const parsed = flaggedLevel.safeParse(value)
  return parsed.success ? parsed.data : undefined
}

export function AlertListPage() {
  const ids = { patient: useId(), status: useId(), level: useId() }
  const [params, setParams] = useSearchParams()
  const patientId = params.get('patient') || undefined
  const status = parseStatus(params.get('status'))
  const deviationLevel = parseLevel(params.get('level'))
  const alerts = useAlerts({ patientId, status, deviationLevel })
  const patients = usePatients({}, 100)
  const patientOptions = mergePages(patients.data, (p) => p.patient_id)
  const items = mergePages(alerts.data, (a) => a.alert_id)
  const filtered = patientId !== undefined || status !== 'UNRESOLVED' || deviationLevel !== undefined

  const update = (key: string, value: string) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Alerts</h1>
        <p className="mt-1 text-slate-600">
          Review items for your assigned patients, newest first in the server’s order (not a clinical priority
          ranking). Opening an alert does not acknowledge it. Times are in your local time zone.
        </p>
      </div>

      <form className="flex flex-wrap gap-3" onSubmit={(event) => event.preventDefault()} aria-label="Alert filters">
        <div>
          <label htmlFor={ids.patient} className="block text-sm font-medium">
            Patient
          </label>
          <select
            id={ids.patient}
            value={patientId ?? ''}
            onChange={(event) => update('patient', event.target.value)}
            className="mt-1 min-h-11 max-w-xs rounded-md border border-slate-300 bg-white px-3"
          >
            <option value="">All assigned patients</option>
            {patientOptions.map((p) => (
              <option key={p.patient_id} value={p.patient_id}>
                {p.display_name}
              </option>
            ))}
            {patientId && !patientOptions.some((p) => p.patient_id === patientId) && (
              <option value={patientId}>Selected patient</option>
            )}
          </select>
        </div>
        <div>
          <label htmlFor={ids.status} className="block text-sm font-medium">
            Review status
          </label>
          <select
            id={ids.status}
            value={status}
            onChange={(event) => update('status', event.target.value === 'UNRESOLVED' ? '' : event.target.value)}
            className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-3"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={ids.level} className="block text-sm font-medium">
            Deviation category
          </label>
          <select
            id={ids.level}
            value={deviationLevel ?? ''}
            onChange={(event) => update('level', event.target.value)}
            className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-3"
          >
            <option value="">Any category</option>
            {flaggedLevel.options.map((level) => (
              <option key={level} value={level}>
                {DEVIATION_LABEL[level]}
              </option>
            ))}
          </select>
        </div>
      </form>

      {alerts.isPending && <Loading label="Loading alerts…" />}
      {alerts.isError && isAccessLost(alerts.error) && (
        <p role="alert" className="rounded-lg border border-slate-300 bg-white p-4">
          {UNAVAILABLE_TEXT} Choose another patient filter.
        </p>
      )}
      {alerts.isError && !isAccessLost(alerts.error) && !alerts.data && (
        <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
      )}
      {alerts.isError && !isAccessLost(alerts.error) && alerts.data && (
        <StaleNotice error={alerts.error} updatedAt={alerts.dataUpdatedAt} onRefresh={() => void alerts.refetch()} />
      )}
      {alerts.isSuccess && items.length === 0 && (
        <p className="text-slate-700">{filtered ? 'No alerts match the selected filters.' : 'No unresolved alerts.'}</p>
      )}

      {items.length > 0 && !isAccessLost(alerts.error) && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>
              {items.length} loaded{alerts.hasNextPage ? '; more are available' : ''}. Refreshing reloads the list
              from the start, so items whose status changed may move or disappear.
            </span>
            <LastRefreshed at={alerts.dataUpdatedAt} />
          </div>
          <ul className="space-y-3">
            {items.map((alert) => (
              <li key={alert.alert_id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <p className="font-semibold break-words">{alert.patient_display_name}</p>
                    <div className="flex flex-wrap gap-1.5">
                      <DeviationBadge level={alert.deviation_level} />
                      <AlertWorkflowBadge status={alert.workflow_status} />
                    </div>
                  </div>
                  <Link
                    to={`/doctor/alerts/${alert.alert_id}`}
                    className="inline-flex min-h-11 items-center rounded-md bg-indigo-700 px-4 text-sm font-semibold text-white hover:bg-indigo-800"
                  >
                    Open review<span className="sr-only"> for {alert.patient_display_name}</span>
                  </Link>
                </div>
                <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-slate-600">Check-in observed</dt>
                    <dd>{formatLocal(alert.observed_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-600">Alert created</dt>
                    <dd>{formatLocal(alert.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-slate-600">Affected domains</dt>
                    <dd>{alert.affected_domains.map((d) => DOMAIN_LABEL[d]).join(', ') || 'None listed'}</dd>
                  </div>
                </dl>
                <p className="mt-2 text-sm text-slate-800">{alert.summary}</p>
              </li>
            ))}
          </ul>
          {alerts.hasNextPage && (
            <button
              type="button"
              onClick={() => void alerts.fetchNextPage()}
              disabled={alerts.isFetchingNextPage}
              className="min-h-11 rounded-md border border-slate-300 bg-white px-4 font-medium hover:bg-slate-50 disabled:opacity-60"
            >
              {alerts.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
