import { Gauge } from 'lucide-react'
import { useInsights } from '../queries'
import type { AssessmentDetail } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { reasonText } from '../utils/displayLabels'
import { elapsedLabel } from '../utils/insightPresentation'
import { formatIndex, formatPoints } from '../utils/valueFormatting'

const DAY = 24 * 3600 * 1000
// A weekly predecessor is 7 days earlier (±12 h windows); 10 days covers it without loading history.
const LOOKBACK_DAYS = 10

/**
 * Cognitive Score context for an alert (refinement 04 §9). Values come from the backend's
 * `cognitive_index_v1` projection; the previous comparable check-in is the backend's own
 * `previous_comparable_assessment_id` from a small Insights window. The point difference is
 * descriptive only — it never sets or changes the alert's category.
 */
export function AlertScoreContext({
  patientId,
  assessment,
  timeZone,
}: {
  patientId: string
  assessment: AssessmentDetail
  timeZone: string
}) {
  const index = assessment.cognitive_index
  const observedAt = Date.parse(assessment.observed_at)
  const range = {
    from: new Date(observedAt - LOOKBACK_DAYS * DAY).toISOString(),
    to: new Date(observedAt + 1).toISOString(),
    source: 'ALL' as const,
  }
  const insights = useInsights(patientId, range)
  const records = insights.data?.records ?? []
  const current = records.find((r) => r.assessment_id === assessment.assessment_id)
  const previousId = current?.previous_comparable_assessment_id ?? null
  const previous = previousId ? records.find((r) => r.assessment_id === previousId) : undefined

  const observed = index.observed_value
  const forecast = index.forecast_value
  const belowForecast = observed !== null && forecast !== null ? observed - forecast : null
  const prevValue = previous?.cognitive_index.observed_value ?? null
  const change = observed !== null && prevValue !== null ? observed - prevValue : null

  return (
    <section aria-labelledby="alert-score-heading" className="surface-card space-y-3 p-4">
      <h2 id="alert-score-heading" className="flex items-center gap-2 text-lg font-semibold">
        <Gauge aria-hidden="true" className="h-5 w-5 text-indigo-600" />
        Cognitive Score at this check-in
      </h2>
      <dl className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
        <div>
          <dt className="text-xs font-medium text-slate-600">Observed</dt>
          <dd className="text-xl font-bold whitespace-nowrap tabular-nums">{formatIndex(observed)}</dd>
          {observed === null && index.observed_unavailable_reasons[0] && (
            <dd className="text-xs text-slate-600">{reasonText(index.observed_unavailable_reasons[0])}</dd>
          )}
        </div>
        <div>
          <dt className="text-xs font-medium text-slate-600">Forecast composite (stored before the check-in)</dt>
          <dd className="text-xl font-bold whitespace-nowrap tabular-nums text-slate-700">{formatIndex(forecast)}</dd>
          {belowForecast !== null && (
            <dd className="text-sm text-slate-700">
              {belowForecast < 0
                ? `Below forecast by ${formatPoints(-belowForecast).replace('+', '')}`
                : belowForecast > 0
                  ? `Above forecast by ${formatPoints(belowForecast).replace('+', '')}`
                  : 'Equal to the forecast composite'}
            </dd>
          )}
        </div>
        <div>
          <dt className="text-xs font-medium text-slate-600">Previous comparable check-in</dt>
          {insights.isPending ? (
            <dd className="skeleton mt-1 h-6 w-28" aria-label="Loading previous comparable check-in" />
          ) : previous && prevValue !== null && change !== null ? (
            <>
              <dd className="text-xl font-bold whitespace-nowrap tabular-nums text-slate-700">{formatIndex(prevValue)}</dd>
              <dd className="text-sm text-slate-700">
                {formatPoints(change)} since {formatInZone(previous.observed_at, timeZone)} (
                {elapsedLabel(previous.observed_at, assessment.observed_at)})
              </dd>
            </>
          ) : (
            <dd className="text-sm text-slate-600">
              None directly comparable (a different source, segment or version, a missed week, or no usable earlier
              score). The forecast comparison is shown instead.
            </dd>
          )}
        </div>
      </dl>
      <p className="text-xs text-slate-500">
        The Cognitive Score ({index.version}) summarises the three task results for orientation. The alert itself was
        raised from the individual task comparisons below, not from this score.
      </p>
    </section>
  )
}
