import { useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { InsightsSource } from '../api'
import { AlertReviewTimeline } from '../components/AlertReviewTimeline'
import { AssessmentQualityCharts } from '../components/AssessmentQualityCharts'
import { ContextScatterChart } from '../components/ContextScatterChart'
import { DomainHeatmap } from '../components/DomainHeatmap'
import { ChartSkeleton } from '../components/InsightPanel'
import { InsightFilters } from '../components/InsightFilters'
import { CompareAssessments, SelectedAssessmentBreakdown } from '../components/InsightSelection'
import { ErrorState, LastRefreshed, StaleNotice } from '../components/QueryState'
import { ScoreChangeChart } from '../components/ScoreChangeChart'
import { ScoreDistributionChart } from '../components/ScoreDistributionChart'
import { isAccessLost, useAccessLossPurge, useInsights, usePatient } from '../queries'
import { lastDaysUtcRange } from '../utils/dateFormatting'
import { UNAVAILABLE_TEXT } from '../utils/errorText'
import { eligibleScores, summaryStats } from '../utils/insightPresentation'
import { formatIndex } from '../utils/valueFormatting'
import { ChartViewKey } from '../utils/chartEntrance'

const SOURCES: InsightsSource[] = ['ALL', 'LIVE_DEMO', 'SYNTHETIC_HISTORY', 'SCENARIO_REPLAY']

function asSource(value: string | null): InsightsSource {
  return SOURCES.includes(value as InsightsSource) ? (value as InsightsSource) : 'ALL'
}

export function VisualInsightsPage() {
  const [params, setParams] = useSearchParams()
  const patientId = params.get('patientId')
  const source = asSource(params.get('source'))
  const from = params.get('from')
  const to = params.get('to')
  const selectedId = params.get('assessment')
  const pinA = params.get('pinA')
  const pinB = params.get('pinB')

  const patient = usePatient(patientId ?? '', Boolean(patientId))
  const timeZone = patient.data?.patient.timezone ?? null
  const range = patientId && from && to && from < to ? { from, to, source } : null
  const insights = useInsights(patientId, range)
  const lost = isAccessLost(patient.error) || isAccessLost(insights.error)
  useAccessLossPurge(lost, { patientId: patientId ?? undefined })

  useEffect(() => {
    if (!patientId || !timeZone || (from && to)) return
    const preset = lastDaysUtcRange(90, timeZone)
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        next.set('from', preset.from)
        next.set('to', preset.to)
        if (!next.get('source')) next.set('source', 'ALL')
        return next
      },
      { replace: true },
    )
  }, [patientId, timeZone, from, to, setParams])

  const patch = (updates: Record<string, string | null | undefined>) => {
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
  }

  const resetFilters = () => {
    if (!timeZone) return
    const preset = lastDaysUtcRange(90, timeZone)
    patch({ from: preset.from, to: preset.to, source: 'ALL', assessment: null, pinA: null, pinB: null })
  }

  const records = insights.data?.records ?? []
  const presentIds = records.map((record) => record.assessment_id).join('|')
  useEffect(() => {
    if (!insights.isSuccess) return
    const present = new Set(presentIds ? presentIds.split('|') : [])
    const nextAssessment = selectedId && present.has(selectedId) ? selectedId : null
    const nextA = pinA && present.has(pinA) ? pinA : null
    const nextB = pinB && present.has(pinB) ? pinB : null
    if (nextAssessment === selectedId && nextA === pinA && nextB === pinB) return
    setParams(
      (current) => {
        const next = new URLSearchParams(current)
        for (const [key, value] of [
          ['assessment', nextAssessment],
          ['pinA', nextA],
          ['pinB', nextB],
        ] as const) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
        return next
      },
      { replace: true },
    )
  }, [insights.isSuccess, presentIds, selectedId, pinA, pinB, setParams])

  const selected = records.find((record) => record.assessment_id === selectedId) ?? null
  const left = records.find((record) => record.assessment_id === pinA) ?? null
  const right = records.find((record) => record.assessment_id === pinB) ?? null
  const stats = insights.data ? summaryStats(insights.data) : null
  const scored = eligibleScores(records)

  const select = (assessmentId: string) => patch({ assessment: assessmentId })
  const pinSelected = () => {
    if (!selectedId) return
    if (!pinA) patch({ pinA: selectedId })
    else if (!pinB && selectedId !== pinA) patch({ pinB: selectedId })
    else if (pinA === selectedId) patch({ pinA: null })
    else if (pinB === selectedId) patch({ pinB: null })
    else patch({ pinB: selectedId })
  }

  if (lost) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Visual Insights</h1>
        <p role="alert" className="rounded-lg border border-slate-300 bg-white p-4">
          {UNAVAILABLE_TEXT}
        </p>
      </div>
    )
  }

  return (
    <ChartViewKey.Provider value={`${patientId}|${from}|${to}|${source}`}>
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Visual Insights</h1>
        <p className="mt-1 text-slate-600">
          Additional views of one assigned patient’s stored check-ins. The Cognitive Score is a prototype
          task-performance index, not a clinical test. These charts do not create or dismiss alerts.
        </p>
        {patient.data && (
          <p className="mt-2 text-sm">
            <Link to={`/doctor/patients/${patient.data.patient.patient_id}`} className="font-semibold text-indigo-800 underline">
              Open {patient.data.patient.display_name}’s assessment history
            </Link>
          </p>
        )}
      </div>

      <InsightFilters
        value={{ patientId, from: from ?? '', to: to ?? '', source }}
        timeZone={timeZone}
        records={records}
        onChange={(next) => {
          const cleared = next.patientId !== undefined && next.patientId !== patientId
          patch({
            ...next,
            ...(cleared ? { from: null, to: null, assessment: null, pinA: null, pinB: null } : {}),
          })
        }}
        onReset={resetFilters}
      />

      {!patientId && (
        <p className="rounded-lg border border-slate-200 bg-white p-4 text-slate-700">
          Choose an assigned patient to load Visual Insights. The page never loads every patient’s history at once.
        </p>
      )}

      {patientId && patient.isError && !patient.data && (
        <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />
      )}

      {patientId && range && insights.isPending && (
        <div className="grid gap-4 md:grid-cols-2">
          <ChartSkeleton label="Loading domain heatmap…" />
          <ChartSkeleton label="Loading change chart…" />
          <ChartSkeleton label="Loading distribution…" />
          <ChartSkeleton label="Loading context explorer…" />
        </div>
      )}

      {insights.isError && !insights.data && (
        <ErrorState error={insights.error} onRetry={() => void insights.refetch()} />
      )}
      {insights.isError && insights.data && !isAccessLost(insights.error) && (
        <StaleNotice error={insights.error} updatedAt={insights.dataUpdatedAt} onRefresh={() => void insights.refetch()} />
      )}

      {insights.data && insights.data.complete && (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-slate-600">
              {insights.data.assessment_count} assessment{insights.data.assessment_count === 1 ? '' : 's'} in a complete
              snapshot.
            </p>
            <LastRefreshed at={insights.dataUpdatedAt} />
          </div>

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard
              label="Submitted assessments"
              value={String(stats?.submitted ?? 0)}
              help="Every assessment in this patient and filter range, including extras and invalid ones"
            />
            <SummaryCard
              label="Eligible Cognitive Scores"
              value={String(stats?.eligibleScored ?? 0)}
              help="Weekly representatives with an available composite"
            />
            <SummaryCard
              label="Median eligible score"
              value={stats?.median == null ? '—' : formatIndex(stats.median)}
              help="Median of those eligible scores only"
            />
            <SummaryCard
              label="Unresolved linked alerts"
              value={String(stats?.unresolvedAlerts ?? 0)}
              help="Open or acknowledged alerts attached to assessments in this range"
            />
          </section>

          {records.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white p-4">
              <p className="text-slate-700">No submitted assessments in this range.</p>
              <button type="button" onClick={resetFilters} className="mt-3 min-h-11 rounded-md border border-slate-300 px-3 font-medium">
                Reset dates and source
              </button>
            </div>
          ) : (
            <>
              {scored.length === 0 && (
                <p className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                  Assessments exist, but none have an eligible available Cognitive Score. Quality, context and alerts
                  below still describe the submitted check-ins.
                </p>
              )}
              <div className="grid gap-4 lg:grid-cols-2">
                <SelectedAssessmentBreakdown
                  record={selected}
                  patientId={patientId!}
                  timeZone={insights.data.timezone}
                  pinned={selectedId === pinA || selectedId === pinB}
                  onPin={pinSelected}
                  onClear={() => patch({ assessment: null })}
                />
                <CompareAssessments
                  left={left}
                  right={right}
                  timeZone={insights.data.timezone}
                  onClear={() => patch({ pinA: null, pinB: null })}
                />
              </div>
              <DomainHeatmap
                records={records}
                timeZone={insights.data.timezone}
                selectedId={selectedId}
                onSelect={select}
              />
              <div className="grid gap-4 lg:grid-cols-2">
                <ScoreChangeChart
                  records={records}
                  timeZone={insights.data.timezone}
                  selectedId={selectedId}
                  onSelect={select}
                />
                <ScoreDistributionChart records={records} timeZone={insights.data.timezone} />
                <ContextScatterChart
                  records={records}
                  timeZone={insights.data.timezone}
                  selectedId={selectedId}
                  onSelect={select}
                />
                <AssessmentQualityCharts records={records} />
              </div>
              <AlertReviewTimeline
                records={records}
                timeZone={insights.data.timezone}
                selectedId={selectedId}
                onSelect={select}
              />
            </>
          )}
        </>
      )}
    </div>
    </ChartViewKey.Provider>
  )
}

function SummaryCard({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-xs font-medium tracking-wide text-indigo-700 uppercase">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-slate-600">{help}</p>
    </div>
  )
}
