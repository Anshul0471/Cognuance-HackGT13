import { useRef } from 'react'
import { Link } from 'react-router-dom'
import type { InsightAssessment } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { AVAILABILITY_LABEL, QUALITY_LABEL, reasonText } from '../utils/displayLabels'
import { COMPARE_REASON_TEXT, comparability, elapsedLabel } from '../utils/insightPresentation'
import { formatDomainValue, formatIndex, formatPoints } from '../utils/valueFormatting'
import { AnalysisBadges } from './Badges'
import { ChartViewKey, useChartEntrance } from '../utils/chartEntrance'

function ComponentBars({
  record,
}: {
  record: InsightAssessment
}) {
  const components = record.cognitive_index.observed_components
  const barsRef = useRef<HTMLDListElement>(null)
  useChartEntrance(barsRef, components !== null, 'html')
  if (!components) {
    return (
      <div className="text-sm text-slate-700">
        <p>
          No composite components:{' '}
          {record.cognitive_index.observed_unavailable_reasons.map(reasonText).join(' ') ||
            'the three task results are not all available.'}
        </p>
        <p className="mt-1 text-slate-600">
          Stored raw values: memory {formatDomainValue('memory', record.scores.memory_score)}, attention{' '}
          {formatDomainValue('attention', record.scores.attention_score)}, reaction time{' '}
          {formatDomainValue('reaction_time_ms', record.scores.reaction_time_ms)}.
        </p>
      </div>
    )
  }
  const rows = [
    { label: 'Memory', value: components.memory },
    { label: 'Attention', value: components.attention },
    { label: 'Response speed', value: components.response_speed },
  ]
  return (
    <dl ref={barsRef} className="space-y-2">
      {rows.map((row) => (
        <div key={row.label}>
          <div className="flex justify-between text-sm">
            <dt>{row.label}</dt>
            <dd className="tabular-nums">{row.value.toFixed(1)} / 100</dd>
          </div>
          <div className="mt-1 h-2.5 rounded-full bg-slate-100">
            <div data-entrance="bar-x" className="h-2.5 rounded-full bg-indigo-600" style={{ width: `${Math.min(100, Math.max(0, row.value))}%` }} />
          </div>
        </div>
      ))}
      <p className="text-xs text-slate-600">
        Raw reaction time {formatDomainValue('reaction_time_ms', record.scores.reaction_time_ms)}
      </p>
    </dl>
  )
}

export function SelectedAssessmentBreakdown({
  record,
  patientId,
  timeZone,
  pinned,
  onPin,
  onClear,
}: {
  record: InsightAssessment | null
  patientId: string
  timeZone: string
  pinned: boolean
  onPin: () => void
  onClear: () => void
}) {
  if (!record) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-600">
        Select a heatmap column, change bar, scatter point or alert marker to inspect that check-in’s components.
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4" aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Selected check-in</h2>
          <p className="text-sm text-slate-600">{formatInZone(record.observed_at, timeZone)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onPin}
            className="min-h-11 rounded-md border border-slate-300 px-3 text-sm font-medium hover:bg-slate-50"
          >
            {pinned ? 'Unpin' : 'Pin for comparison'}
          </button>
          <button type="button" onClick={onClear} className="min-h-11 rounded-md px-3 text-sm underline">
            Clear selection
          </button>
        </div>
      </div>
      <p className="mt-2 text-2xl font-bold tabular-nums">{formatIndex(record.cognitive_index.observed_value)}</p>
      <p className="text-sm text-slate-600">
        {QUALITY_LABEL[record.quality_status]} ·{' '}
        {AVAILABILITY_LABEL[record.analysis.availability]}
      </p>
      <div className="mt-2">
        <AnalysisBadges availability={record.analysis.availability} level={record.analysis.deviation_level} />
      </div>
      <div className="mt-4">
        <ChartViewKey.Provider value={record.assessment_id}>
        <ComponentBars record={record} />
      </ChartViewKey.Provider>
      </div>
      <p className="mt-3 text-sm">
        <Link
          to={`/doctor/patients/${patientId}/assessments/${record.assessment_id}`}
          className="font-semibold text-indigo-800 underline"
        >
          Open assessment detail
        </Link>
        {record.linked_alert && (
          <>
            {' · '}
            <Link to={`/doctor/alerts/${record.linked_alert.alert_id}`} className="font-semibold text-indigo-800 underline">
              Open alert
            </Link>
          </>
        )}
      </p>
    </section>
  )
}

export function CompareAssessments({
  left,
  right,
  timeZone,
  onClear,
}: {
  left: InsightAssessment | null
  right: InsightAssessment | null
  timeZone: string
  onClear: () => void
}) {
  if (!left || !right) {
    return (
      <section className="rounded-lg border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-600">
        Pin two check-ins to compare their component bars. Comparison is a selected-visit description, not the
        consecutive-slot change chart and not a new detector.
      </section>
    )
  }
  const verdict = comparability(left, right)
  const rows = [
    { label: 'Memory', a: left.cognitive_index.observed_components?.memory ?? null, b: right.cognitive_index.observed_components?.memory ?? null },
    { label: 'Attention', a: left.cognitive_index.observed_components?.attention ?? null, b: right.cognitive_index.observed_components?.attention ?? null },
    { label: 'Response speed', a: left.cognitive_index.observed_components?.response_speed ?? null, b: right.cognitive_index.observed_components?.response_speed ?? null },
    { label: 'Cognitive Score', a: left.cognitive_index.observed_value, b: right.cognitive_index.observed_value },
  ]
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-lg font-semibold">Compare two assessments</h2>
        <button type="button" onClick={onClear} className="min-h-11 rounded-md px-3 text-sm underline">
          Clear pins
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        {formatInZone(left.observed_at, timeZone)} · {formatInZone(right.observed_at, timeZone)} ·{' '}
        {elapsedLabel(left.observed_at, right.observed_at)}
      </p>
      {!verdict.ok && (
        <p className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-sm">
          Not comparable. {COMPARE_REASON_TEXT[verdict.reason]} Values are shown separately; no difference is calculated.
        </p>
      )}
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className="text-sm">
            <p className="font-medium">{row.label}</p>
            <p className="tabular-nums">
              {row.a === null ? '—' : row.label === 'Cognitive Score' ? formatIndex(row.a) : `${row.a.toFixed(1)} / 100`}
              {' · '}
              {row.b === null ? '—' : row.label === 'Cognitive Score' ? formatIndex(row.b) : `${row.b.toFixed(1)} / 100`}
            </p>
            {verdict.ok && row.a !== null && row.b !== null && (
              <p className="text-xs text-slate-600">{formatPoints(row.b - row.a)}</p>
            )}
            <div className="mt-1 space-y-1">
              <div className="h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-indigo-600" style={{ width: `${row.a ?? 0}%` }} />
              </div>
              <div className="h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-slate-500" style={{ width: `${row.b ?? 0}%` }} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
