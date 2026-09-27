import { Search } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { InitialsAvatar } from '../../../components/InitialsAvatar'
import { AnalysisBadges } from '../components/Badges'
import { ErrorState, LastRefreshed, Loading, StaleNotice } from '../components/QueryState'
import { mergePages, usePatients } from '../queries'
import { formatLocal } from '../utils/dateFormatting'

const SEARCH_MAX = 100
const DEBOUNCE_MS = 300

type AlertFilter = 'any' | 'with' | 'without'

function parseAlertFilter(value: string | null): AlertFilter {
  return value === 'with' || value === 'without' ? value : 'any'
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

export function PatientListPage() {
  const searchId = useId()
  const filterId = useId()
  // Filters initialise from the URL (e.g. the overview's `?alerts=with` card) and stay in it.
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(() => (params.get('q') ?? '').slice(0, SEARCH_MAX))
  const alertFilter = parseAlertFilter(params.get('alerts'))
  const setAlertFilter = (value: AlertFilter) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === 'any') next.delete('alerts')
        else next.set('alerts', value)
        return next
      },
      { replace: true },
    )
  const q = useDebounced(search.trim(), DEBOUNCE_MS)
  const filters = {
    q: q || undefined,
    hasUnresolvedAlerts: alertFilter === 'any' ? undefined : alertFilter === 'with',
  }
  const patients = usePatients(filters)
  const items = mergePages(patients.data, (p) => p.patient_id)
  const filtered = filters.q !== undefined || filters.hasUnresolvedAlerts !== undefined

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Assigned patients</h1>
        <p className="mt-1 text-slate-600">
          Only patients currently assigned to you. Listed in the server's order (most recently added first);
          times are in your local time zone.
        </p>
      </div>

      <form role="search" className="flex flex-wrap items-start gap-3" onSubmit={(event) => event.preventDefault()}>
        <div className="min-w-0 flex-1">
          <label htmlFor={searchId} className="block text-sm font-medium">
            Search by name
          </label>
          <div className="relative mt-1">
            <Search aria-hidden="true" className="absolute top-3 left-3 h-4 w-4 text-slate-400" />
            <input
              id={searchId}
              type="search"
              value={search}
              maxLength={SEARCH_MAX}
              onChange={(event) => setSearch(event.target.value.slice(0, SEARCH_MAX))}
              className="min-h-11 w-full rounded-md border border-slate-300 bg-white py-2 pr-3 pl-9"
              aria-describedby={`${searchId}-help`}
            />
          </div>
          <p id={`${searchId}-help`} className="mt-1 text-xs text-slate-500">
            Searches all of your assigned patients on the server (up to {SEARCH_MAX} characters).
          </p>
        </div>
        <div>
          <label htmlFor={filterId} className="block text-sm font-medium">
            Unresolved alerts
          </label>
          <select
            id={filterId}
            value={alertFilter}
            onChange={(event) => setAlertFilter(event.target.value as AlertFilter)}
            className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-3"
          >
            <option value="any">Any</option>
            <option value="with">With unresolved alerts</option>
            <option value="without">Without unresolved alerts</option>
          </select>
        </div>
      </form>

      {patients.isPending && <Loading label="Loading patients…" />}
      {patients.isError && !patients.data && (
        <ErrorState error={patients.error} onRetry={() => void patients.refetch()} />
      )}
      {patients.isError && patients.data && (
        <StaleNotice error={patients.error} updatedAt={patients.dataUpdatedAt} onRefresh={() => void patients.refetch()} />
      )}
      {patients.isSuccess && items.length === 0 && (
        <p className="text-slate-700">
          {filtered ? 'No patients match these filters.' : 'No patients are assigned to you.'}
        </p>
      )}

      {items.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
            <span>
              {items.length} loaded{patients.hasNextPage ? '; more are available' : ''}.
            </span>
            <LastRefreshed at={patients.dataUpdatedAt} />
          </div>
          <div
            className="surface-card relative overflow-x-auto"
            role="region"
            aria-label="Assigned patients table"
            tabIndex={0}
          >
            <table className="min-w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs font-semibold tracking-wide text-slate-600 uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">Patient</th>
                  <th scope="col" className="px-4 py-2.5">Latest assessment</th>
                  <th scope="col" className="px-4 py-2.5">Latest analysis</th>
                  <th scope="col" className="px-4 py-2.5">Unresolved alerts</th>
                  <th scope="col" className="px-4 py-2.5"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((patient) => (
                  <tr key={patient.patient_id} className="align-middle transition-colors duration-150 hover:bg-slate-50 motion-reduce:transition-none">
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-3">
                        <InitialsAvatar name={patient.display_name} />
                        <span className="min-w-0">
                          <span className="block font-medium break-words">{patient.display_name}</span>
                          {!patient.account_active && (
                            <span className="mt-1 inline-flex rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800">
                              Patient account inactive
                            </span>
                          )}
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      {patient.latest_assessment_at ? formatLocal(patient.latest_assessment_at) : 'No assessments yet'}
                    </td>
                    <td className="px-4 py-3">
                      <AnalysisBadges
                        availability={patient.latest_analysis_availability}
                        level={patient.latest_deviation_level}
                      />
                    </td>
                    <td className="px-4 py-3 tabular-nums">{patient.unresolved_alert_count}</td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        to={`/doctor/patients/${patient.patient_id}`}
                        className="btn-secondary min-h-10 px-3 text-sm whitespace-nowrap"
                      >
                        View patient<span className="sr-only"> {patient.display_name}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {patients.hasNextPage && (
            <button
              type="button"
              onClick={() => void patients.fetchNextPage()}
              disabled={patients.isFetchingNextPage}
              className="min-h-11 rounded-md border border-slate-300 bg-white px-4 font-medium hover:bg-slate-50 disabled:opacity-60"
            >
              {patients.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          )}
        </>
      )}
    </div>
  )
}
