import { RotateCcw, Search } from 'lucide-react'
import { useEffect, useId, useState, type FormEvent } from 'react'
import type { InsightsSource } from '../api'
import { mergePages, usePatients } from '../queries'
import type { InsightAssessment, PatientListItem } from '../schemas'
import { exclusiveToInclusiveDate, lastDaysUtcRange, todayInZone, toApiRange } from '../utils/dateFormatting'
import { SOURCE_LABEL } from '../utils/displayLabels'
import { sourceBreakdown } from '../utils/insightPresentation'

const PRESETS = [30, 90, 180, 365] as const
const SEARCH_MAX = 100

export type InsightFilterValue = {
  patientId: string | null
  from: string
  to: string
  source: InsightsSource
}

export function InsightFilters({
  value,
  timeZone,
  records,
  onChange,
  onReset,
}: {
  value: InsightFilterValue
  timeZone: string | null
  records: InsightAssessment[]
  onChange: (next: Partial<InsightFilterValue>) => void
  onReset: () => void
}) {
  const searchId = useId()
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const syncedCustom =
    timeZone && value.from && value.to
      ? {
          from: todayInZone(timeZone, Date.parse(value.from)),
          to: exclusiveToInclusiveDate(value.to, timeZone),
        }
      : { from: '', to: '' }

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])

  const patients = usePatients({ q: debounced || undefined })
  const items = mergePages(patients.data, (p) => p.patient_id)
  const breakdown = sourceBreakdown(records)
  const selectedPreset = matchingPreset(value, timeZone)

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <label htmlFor={searchId} className="block text-sm font-medium">
          Patient
        </label>
        <div className="relative mt-1 max-w-md">
          <Search aria-hidden="true" className="absolute top-3 left-3 h-4 w-4 text-slate-400" />
          <input
            id={searchId}
            type="search"
            value={search}
            maxLength={SEARCH_MAX}
            onChange={(event) => setSearch(event.target.value.slice(0, SEARCH_MAX))}
            className="min-h-11 w-full rounded-md border border-slate-300 bg-white py-2 pr-3 pl-9"
            placeholder="Search assigned patients"
          />
        </div>
        <ul className="mt-2 max-h-48 overflow-y-auto rounded-md border border-slate-200">
          {items.map((patient) => (
            <PatientChoice
              key={patient.patient_id}
              patient={patient}
              selected={patient.patient_id === value.patientId}
              onSelect={() => onChange({ patientId: patient.patient_id })}
            />
          ))}
          {patients.isSuccess && items.length === 0 && (
            <li className="px-3 py-2 text-sm text-slate-600">
              {debounced ? 'No assigned patients match that search.' : 'No patients are assigned to you.'}
            </li>
          )}
        </ul>
      </div>

      <fieldset className="space-y-2" disabled={!value.patientId || !timeZone}>
        <legend className="text-sm font-medium">Date range</legend>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => timeZone && onChange(lastDaysUtcRange(days, timeZone))}
              className={`min-h-11 rounded-md px-3 text-sm font-medium ${
                selectedPreset === days
                  ? 'bg-indigo-700 text-white'
                  : 'border border-slate-300 bg-white hover:bg-slate-50'
              }`}
            >
              Last {days} days
            </button>
          ))}
        </div>
        {timeZone ? (
          <CustomRangeForm
            key={`${syncedCustom.from}|${syncedCustom.to}`}
            from={syncedCustom.from}
            to={syncedCustom.to}
            timeZone={timeZone}
            onApply={(nextFrom, nextTo) => onChange({ from: nextFrom, to: nextTo })}
          />
        ) : (
          <p className="text-sm text-slate-600">Select a patient to choose dates in that person’s time zone.</p>
        )}
        {timeZone && (
          <p className="text-xs text-slate-500">
            Dates are calendar days in the patient’s time zone ({timeZone}). Filtering uses each assessment’s
            observed time; a forecast’s target time can fall slightly outside this range.
          </p>
        )}
      </fieldset>

      <div className="flex flex-wrap items-start gap-3">
        {/* Source filtering is optional; it sits in collapsed advanced filters (refinement 03 §9). */}
        <details className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5">
          <summary className="flex min-h-9 cursor-pointer items-center gap-2 text-sm font-medium">
            Advanced filters
            {value.source !== 'ALL' && (
              <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-800">
                Filters applied
              </span>
            )}
          </summary>
          <div className="mt-2 mb-1 space-y-2">
            <div>
              <label htmlFor={`${searchId}-source`} className="block text-sm font-medium">
                Data source
              </label>
              <select
                id={`${searchId}-source`}
                value={value.source}
                onChange={(event) => onChange({ source: event.target.value as InsightsSource })}
                className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-3"
              >
                <option value="ALL">All sources</option>
                <option value="LIVE_DEMO">{SOURCE_LABEL.LIVE_DEMO}</option>
                <option value="SYNTHETIC_HISTORY">{SOURCE_LABEL.SYNTHETIC_HISTORY}</option>
                <option value="SCENARIO_REPLAY">{SOURCE_LABEL.SCENARIO_REPLAY}</option>
              </select>
            </div>
            {records.length > 0 && (
              <p className="text-xs text-slate-600">
                In this range: {SOURCE_LABEL.LIVE_DEMO} {breakdown.LIVE_DEMO} · {SOURCE_LABEL.SYNTHETIC_HISTORY}{' '}
                {breakdown.SYNTHETIC_HISTORY} · {SOURCE_LABEL.SCENARIO_REPLAY} {breakdown.SCENARIO_REPLAY}. Sources are
                never joined into one line; each assessment’s source is listed in its record details.
              </p>
            )}
          </div>
        </details>
        <button
          type="button"
          onClick={onReset}
          disabled={!value.patientId}
          className="inline-flex min-h-11 items-center gap-1 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium hover:bg-slate-50 disabled:opacity-60"
        >
          <RotateCcw aria-hidden="true" className="h-4 w-4" />
          Reset filters
        </button>
      </div>
    </div>
  )
}

function CustomRangeForm({
  from,
  to,
  timeZone,
  onApply,
}: {
  from: string
  to: string
  timeZone: string
  onApply: (from: string, to: string) => void
}) {
  const fromId = useId()
  const toId = useId()
  const [draft, setDraft] = useState({ from, to })
  const [error, setError] = useState<string | null>(null)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const result = toApiRange(draft, timeZone)
    if (!result.ok || !result.range.from || !result.range.to) {
      setError(result.ok ? 'Enter both dates.' : result.error)
      return
    }
    setError(null)
    onApply(result.range.from, result.range.to)
  }
  return (
    <>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={fromId} className="block text-sm font-medium">
            From (inclusive)
          </label>
          <input
            id={fromId}
            type="date"
            value={draft.from}
            onChange={(event) => setDraft((d) => ({ ...d, from: event.target.value }))}
            className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-2"
          />
        </div>
        <div>
          <label htmlFor={toId} className="block text-sm font-medium">
            To (inclusive)
          </label>
          <input
            id={toId}
            type="date"
            value={draft.to}
            onChange={(event) => setDraft((d) => ({ ...d, to: event.target.value }))}
            className="mt-1 min-h-11 rounded-md border border-slate-300 bg-white px-2"
          />
        </div>
        <button type="submit" className="min-h-11 rounded-md bg-indigo-700 px-4 font-semibold text-white hover:bg-indigo-800">
          Apply dates
        </button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-rose-700">
          {error}
        </p>
      )}
    </>
  )
}

function PatientChoice({
  patient,
  selected,
  onSelect,
}: {
  patient: PatientListItem
  selected: boolean
  onSelect: () => void
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={`flex min-h-11 w-full items-center justify-between px-3 text-left text-sm ${
          selected ? 'bg-indigo-50 font-semibold text-indigo-900' : 'hover:bg-slate-50'
        }`}
      >
        <span>{patient.display_name}</span>
        {patient.unresolved_alert_count > 0 && (
          <span className="text-xs text-amber-800">{patient.unresolved_alert_count} unresolved</span>
        )}
      </button>
    </li>
  )
}

function matchingPreset(value: InsightFilterValue, timeZone: string | null): number | null {
  if (!timeZone || !value.from || !value.to) return null
  for (const days of PRESETS) {
    const preset = lastDaysUtcRange(days, timeZone)
    if (preset.from === value.from && preset.to === value.to) return days
  }
  return null
}
