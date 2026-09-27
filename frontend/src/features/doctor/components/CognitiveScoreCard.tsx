import { ArrowRight, Gauge } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { CognitiveIndexMetadata, TimelineItem } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { reasonText } from '../utils/displayLabels'
import { SCORE_SUBTITLE, SCORE_TITLE, scoreHeadline } from '../utils/cognitiveScore'
import { formatIndex, formatPoints } from '../utils/valueFormatting'
import { AnalysisBadges, DeviationBadge } from './Badges'
import { CognitiveScoreChart } from './CognitiveScoreChart'
import { CognitiveScoreExplanation } from './CognitiveScoreExplanation'

/**
 * The composite score card inserted above the task charts (refinement 01 §5). It reuses the
 * page's already-loaded timeline, filters and pagination: no second filter bar or patient
 * selector, and no data of its own.
 */
export function CognitiveScoreCard({
  items,
  meta,
  timeZone,
  patientId,
  partial,
  ranged,
  insightsHref,
  onSelect,
}: {
  items: TimelineItem[]
  meta: CognitiveIndexMetadata
  timeZone: string
  patientId: string
  partial: boolean
  ranged: boolean
  insightsHref: string
  onSelect: (assessmentId: string) => void
}) {
  const { latest, latestWithScore, previousComparable, changePoints } = scoreHeadline(items)
  const headlineItem = latestWithScore?.item ?? null
  const latestHasScore = headlineItem !== null && latest !== null && headlineItem.assessment_id === latest.assessment_id
  // With a filter applied the newest loaded row is only the newest *in range*; say so.
  const headlineLabel = ranged ? 'Latest assessment in selected range' : 'Latest assessment'

  return (
    <section
      aria-labelledby="cognitive-score-heading"
      className="rounded-lg border border-slate-200 bg-white p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="cognitive-score-heading" className="inline-flex items-center gap-2 font-semibold">
            <Gauge aria-hidden="true" className="h-4 w-4 text-indigo-600" />
            {SCORE_TITLE}
          </h3>
          <p className="text-sm text-slate-600">{SCORE_SUBTITLE}</p>
        </div>
        <Link
          to={insightsHref}
          className="inline-flex min-h-11 items-center gap-1 rounded-md border border-slate-300 px-3 text-sm font-semibold hover:bg-slate-50"
        >
          Explore Visual Insights
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Link>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <p className="text-xs text-slate-600">{latestHasScore ? headlineLabel : 'Last available score'}</p>
          <p className="text-3xl font-bold tabular-nums">{formatIndex(latestWithScore?.y ?? null)}</p>
          {headlineItem && (
            <p className="text-xs text-slate-600">{formatInZone(headlineItem.observed_at, timeZone)}</p>
          )}
        </div>
        {changePoints !== null && previousComparable && latestWithScore && (
          <div>
            <p className="text-xs text-slate-600">Change from the previous comparable check-in</p>
            <p className="text-lg font-semibold tabular-nums">{formatPoints(changePoints)}</p>
            <p className="text-xs text-slate-600">
              {formatInZone(previousComparable.item.observed_at, timeZone)} →{' '}
              {formatInZone(latestWithScore.item.observed_at, timeZone)}
            </p>
          </div>
        )}
        {headlineItem && (
          <div>
            <p className="text-xs text-slate-600">Analysis of that check-in</p>
            <AnalysisBadges
              availability={headlineItem.analysis.availability}
              level={headlineItem.analysis.deviation_level}
            />
          </div>
        )}
      </div>

      {latest && !latestHasScore && (
        <p className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2 text-sm">
          The {ranged ? 'newest check-in in this range' : 'newest check-in'} (
          {formatInZone(latest.observed_at, timeZone)}) has no Cognitive Score:{' '}
          {latest.cognitive_index.observed_unavailable_reasons.map(reasonText).join(' ') ||
            'its three task results are not all available.'}{' '}
          Its saved results stay visible below.
        </p>
      )}
      {headlineItem?.longitudinal_eligible === false && (
        <p className="mt-2 text-sm text-slate-600">
          This check-in is not used for weekly comparison, so it has no change value.
        </p>
      )}
      {latest?.analysis.deviation_level && latest.analysis.deviation_level !== 'NORMAL' && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <DeviationBadge level={latest.analysis.deviation_level} />
          <span className="text-slate-700">
            Flagged by the per-domain rules. A steady composite does not cancel this.
          </span>
          {latest.alert && (
            <Link to={`/doctor/alerts/${latest.alert.alert_id}`} className="font-semibold underline">
              Open review
            </Link>
          )}
        </p>
      )}

      {items.length > 0 ? (
        <CognitiveScoreChart items={items} timeZone={timeZone} partial={partial} onSelect={onSelect} />
      ) : (
        <p className="mt-3 text-sm text-slate-600">No assessments loaded for this range.</p>
      )}

      <div className="mt-3">
        <CognitiveScoreExplanation
          meta={meta}
          index={headlineItem?.cognitive_index ?? null}
          reactionTimeMs={headlineItem?.scores.reaction_time_ms ?? null}
        />
      </div>
      <p className="sr-only">Patient {patientId}</p>
    </section>
  )
}
