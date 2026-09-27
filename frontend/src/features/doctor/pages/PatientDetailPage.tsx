import { ArrowLeft, Bell } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { AssessmentEvidence } from '../components/AssessmentEvidence'
import { AssessmentHistoryTable } from '../components/AssessmentHistoryTable'
import { AnalysisBadges } from '../components/Badges'
import { CognitiveScoreCard } from '../components/CognitiveScoreCard'
import { ChartLegend, PatientTimelineCharts } from '../components/PatientTimelineCharts'
import { ErrorState, LastRefreshed, Loading, StaleNotice } from '../components/QueryState'
import { UNAVAILABLE_TEXT } from '../utils/errorText'
import {
  isAccessLost,
  mergePages,
  useAccessLossPurge,
  useAssessment,
  usePatient,
  useTimeline,
} from '../queries'
import type { DoctorPatientDetail, TimelineItem } from '../schemas'
import { chronological } from '../utils/chartSeries'
import { formatInZone, toApiRange } from '../utils/dateFormatting'
import { ChartViewKey } from '../utils/chartEntrance'

function insightsHrefFor(patientId: string, from: string, to: string, timeZone: string): string {
  const params = new URLSearchParams({ patientId, source: 'ALL' })
  const result = toApiRange({ from, to }, timeZone)
  if (result.ok && result.range.from && result.range.to) {
    params.set('from', result.range.from)
    params.set('to', result.range.to)
  }
  return `/doctor/insights?${params}`
}

function PatientHeaderCard({ data }: { data: DoctorPatientDetail }) {
  const { patient } = data
  return (
    <section aria-labelledby="patient-name" className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 id="patient-name" className="text-2xl font-bold break-words">
          {patient.display_name}
        </h1>
        {!patient.account_active && (
          <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800">
            Patient account inactive
          </span>
        )}
      </div>
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-slate-600">Time zone (used for dates on this page)</dt>
          <dd className="font-medium">{patient.timezone}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Assigned to you since</dt>
          <dd>{formatInZone(data.assigned_at, patient.timezone)}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Latest assessment</dt>
          <dd>{data.latest_assessment_at ? formatInZone(data.latest_assessment_at, patient.timezone) : 'No assessments yet'}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Latest analysis</dt>
          <dd>
            <AnalysisBadges availability={data.latest_analysis_availability} level={data.latest_deviation_level} />
          </dd>
        </div>
      </dl>
      <Link
        to={`/doctor/alerts?patient=${patient.patient_id}`}
        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-slate-300 px-3 text-sm font-semibold hover:bg-slate-50"
      >
        <Bell aria-hidden="true" className="h-4 w-4" />
        This patient’s alerts: {data.open_alert_count} open, {data.acknowledged_alert_count} acknowledged
      </Link>
    </section>
  )
}

function RangeForm({
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
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    onApply(draft.from, draft.to)
  }
  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-3" aria-describedby={`${fromId}-help`}>
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
          aria-invalid={error ? 'true' : 'false'}
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
          aria-invalid={error ? 'true' : 'false'}
        />
      </div>
      <button type="submit" className="min-h-11 rounded-md bg-indigo-700 px-4 font-semibold text-white hover:bg-indigo-800">
        Apply dates
      </button>
      {(from || to) && (
        <button
          type="button"
          onClick={() => onApply('', '')}
          className="min-h-11 rounded-md border border-slate-300 bg-white px-4 font-medium hover:bg-slate-50"
        >
          Show all dates
        </button>
      )}
      <p id={`${fromId}-help`} className="w-full text-xs text-slate-500">
        Dates are calendar days in the patient’s time zone ({timeZone}).
      </p>
      {error && (
        <p role="alert" className="w-full text-sm text-rose-700">
          {error}
        </p>
      )}
    </form>
  )
}

function SelectedAssessment({
  patientId,
  item,
  timeZone,
}: {
  patientId: string
  item: TimelineItem
  timeZone: string
}) {
  const detail = useAssessment(patientId, item.assessment_id)
  return (
    <section aria-labelledby="selected-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="selected-heading" className="text-lg font-semibold">
          Check-in observed {formatInZone(item.observed_at, timeZone)}
        </h2>
        <Link to={`/doctor/patients/${patientId}/assessments/${item.assessment_id}`} className="text-sm underline">
          Open on its own page
        </Link>
      </div>
      {detail.isPending && <Loading label="Loading this check-in’s details…" />}
      {detail.isError && !detail.data && <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />}
      {detail.isError && detail.data && !isAccessLost(detail.error) && (
        <StaleNotice error={detail.error} updatedAt={detail.dataUpdatedAt} onRefresh={() => void detail.refetch()} />
      )}
      {detail.data && detail.data.assessment_id === item.assessment_id && !isAccessLost(detail.error) && (
        <AssessmentEvidence detail={detail.data} patientId={patientId} timeZone={timeZone} level={3} />
      )}
    </section>
  )
}

export function PatientDetailPage() {
  const { patientId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const selectedId = params.get('assessment')

  const patient = usePatient(patientId)
  const timeZone = patient.data?.patient.timezone ?? 'UTC'
  const range = toApiRange({ from, to }, timeZone)
  const timeline = useTimeline(patientId, range.ok ? range.range : {}, patient.isSuccess && range.ok)
  const lost = isAccessLost(patient.error) || isAccessLost(timeline.error)
  useAccessLossPurge(lost, { patientId })

  const setParam = (updates: Record<string, string | null>) =>
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        for (const [key, value] of Object.entries(updates)) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
        return next
      },
      { replace: true },
    )

  const back = (
    <Link to="/doctor/patients" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-700">
      <ArrowLeft aria-hidden="true" className="h-4 w-4" />
      Assigned patients
    </Link>
  )

  if (lost) {
    return (
      <div className="space-y-4">
        {back}
        <h1 className="text-2xl font-bold">Assessment history</h1>
        <p role="alert" className="rounded-lg border border-slate-300 bg-white p-4">
          {UNAVAILABLE_TEXT}
        </p>
      </div>
    )
  }

  const items = mergePages(timeline.data, (item) => item.assessment_id)
  const partial = timeline.hasNextPage
  const selected = items.find((item) => item.assessment_id === selectedId) ?? null
  const ranged = Boolean(from || to)

  return (
    <div className="space-y-6">
      {back}
      {patient.isPending && <Loading label="Loading patient…" />}
      {patient.isError && !patient.data && <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />}
      {patient.data && (
        <>
          {patient.isError && (
            <StaleNotice error={patient.error} updatedAt={patient.dataUpdatedAt} onRefresh={() => void patient.refetch()} />
          )}
          <PatientHeaderCard data={patient.data} />

          <section aria-labelledby="history-heading" className="space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="history-heading" className="text-lg font-semibold">
                Assessment history
              </h2>
              <LastRefreshed at={timeline.dataUpdatedAt} />
            </div>
            <RangeForm
              key={`${from}|${to}`}
              from={from}
              to={to}
              timeZone={timeZone}
              onApply={(f, t) => setParam({ from: f || null, to: t || null, assessment: null })}
            />
            <ChartLegend />

            {timeline.isPending && <Loading label="Loading assessment history…" />}
            {timeline.isError && !timeline.data && (
              <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />
            )}
            {timeline.isError && timeline.data && (
              <StaleNotice error={timeline.error} updatedAt={timeline.dataUpdatedAt} onRefresh={() => void timeline.refetch()} />
            )}
            {timeline.isSuccess && items.length === 0 && (
              <p className="rounded-lg border border-slate-200 bg-white p-4 text-slate-700">
                {ranged
                  ? 'No assessments in the selected dates.'
                  : 'No assessments yet. Task history appears here after the patient submits a check-in.'}
              </p>
            )}
            {items.length > 0 && (
              <>
                <p className="text-sm text-slate-700" role="status">
                  {items.length} assessment{items.length === 1 ? '' : 's'} loaded
                  {ranged ? ' for the selected dates' : ''}
                  {partial ? '. Older assessments exist but are not loaded yet, so this history is partial.' : '.'}
                </p>
                {!items.some((item) => item.forecast) && (
                  <p className="text-sm text-slate-600">
                    No stored forecasts among the loaded assessments; only observed results are plotted.
                  </p>
                )}
                {/* New patient or date range = a new chart entrance; polling and "load older" are not. */}
                <ChartViewKey.Provider value={`${patientId}|${from}|${to}`}>
                <CognitiveScoreCard
                  items={chronological(items)}
                  meta={patient.data.score_metadata}
                  timeZone={timeZone}
                  patientId={patientId}
                  partial={partial}
                  ranged={ranged}
                  insightsHref={insightsHrefFor(patientId, from, to, timeZone)}
                  onSelect={(id) => setParam({ assessment: id })}
                />
                <PatientTimelineCharts
                  items={chronological(items)}
                  timeZone={timeZone}
                  partial={partial}
                  onSelect={(id) => setParam({ assessment: id })}
                />
                </ChartViewKey.Provider>
                <AssessmentHistoryTable
                  items={items}
                  patientId={patientId}
                  patientName={patient.data.patient.display_name}
                  timeZone={timeZone}
                  selectedId={selectedId}
                  onSelect={(id) => setParam({ assessment: id })}
                />
                {partial && (
                  <button
                    type="button"
                    onClick={() => void timeline.fetchNextPage()}
                    disabled={timeline.isFetchingNextPage}
                    className="min-h-11 rounded-md border border-slate-300 bg-white px-4 font-medium hover:bg-slate-50 disabled:opacity-60"
                  >
                    {timeline.isFetchingNextPage ? 'Loading…' : 'Load older assessments'}
                  </button>
                )}
              </>
            )}
          </section>

          {selected ? (
            <SelectedAssessment key={selected.assessment_id} patientId={patientId} item={selected} timeZone={timeZone} />
          ) : selectedId && timeline.isSuccess ? (
            <p className="text-sm text-slate-700">
              The selected check-in is not among the loaded rows.{' '}
              <Link to={`/doctor/patients/${patientId}/assessments/${selectedId}`} className="underline">
                Open it on its own page
              </Link>
              .
            </p>
          ) : (
            items.length > 0 && (
              <p className="text-sm text-slate-600">Choose “Show details” on a row to see its evidence here.</p>
            )
          )}
        </>
      )}
    </div>
  )
}
