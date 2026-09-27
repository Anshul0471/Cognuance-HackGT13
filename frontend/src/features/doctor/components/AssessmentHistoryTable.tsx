import { Link } from 'react-router-dom'
import type { TimelineItem } from '../schemas'
import { FORECAST_FIELD, OBSERVED_FIELD, type ChartDomain } from '../utils/chartSeries'
import { formatInZone } from '../utils/dateFormatting'
import { PURPOSE_LABEL, WORKFLOW_LABEL } from '../utils/displayLabels'
import { formatDomainValue } from '../utils/valueFormatting'
import { AlertWorkflowBadge, AnalysisBadges, QualityBadge } from './Badges'

function DomainCell({ item, domain }: { item: TimelineItem; domain: ChartDomain }) {
  const forecast = item.forecast ? item.forecast[FORECAST_FIELD[domain]] : null
  return (
    <td className="px-3 py-2 whitespace-nowrap">
      <span className="block">{formatDomainValue(domain, item.scores[OBSERVED_FIELD[domain]])}</span>
      <span className="block text-xs text-slate-500">
        {forecast === null ? 'No forecast' : `Forecast ${formatDomainValue(domain, forecast)}`}
      </span>
    </td>
  )
}

/** Newest first; row identity is the assessment ID. The same evidence as the charts, without hover. */
export function AssessmentHistoryTable({
  items,
  patientId,
  patientName,
  timeZone,
  selectedId,
  onSelect,
}: {
  items: TimelineItem[]
  patientId: string
  patientName: string
  timeZone: string
  selectedId: string | null
  onSelect: (assessmentId: string) => void
}) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-slate-200 bg-white" role="region" aria-label="Assessment history table" tabIndex={0}>
      <table className="min-w-full text-sm">
        <caption className="px-3 py-2 text-left text-sm text-slate-600">
          Check-in history for {patientName}: {items.length} loaded, newest first. Times in {timeZone}.
        </caption>
        <thead className="bg-slate-50 text-left">
          <tr>
            <th scope="col" className="px-3 py-2">Observed</th>
            <th scope="col" className="px-3 py-2">Target (weekly slot)</th>
            <th scope="col" className="px-3 py-2">Source</th>
            <th scope="col" className="px-3 py-2">Memory</th>
            <th scope="col" className="px-3 py-2">Attention</th>
            <th scope="col" className="px-3 py-2">Reaction time</th>
            <th scope="col" className="px-3 py-2">Quality and eligibility</th>
            <th scope="col" className="px-3 py-2">Analysis</th>
            <th scope="col" className="px-3 py-2">Alert</th>
            <th scope="col" className="px-3 py-2"><span className="sr-only">Details</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {items.map((item) => {
            const selected = item.assessment_id === selectedId
            return (
              <tr key={item.assessment_id} className={selected ? 'bg-indigo-50' : undefined}>
                <td className="px-3 py-2 whitespace-nowrap">{formatInZone(item.observed_at, timeZone)}</td>
                <td className="px-3 py-2 whitespace-nowrap">{formatInZone(item.target_at, timeZone)}</td>
                <td className="px-3 py-2">
                  <span className="block">{PURPOSE_LABEL[item.schedule_purpose]}</span>
                </td>
                <DomainCell item={item} domain="memory" />
                <DomainCell item={item} domain="attention" />
                <DomainCell item={item} domain="reaction_time_ms" />
                <td className="px-3 py-2">
                  <QualityBadge quality={item.quality_status} />
                  <span className="mt-1 block text-xs text-slate-600">
                    {item.longitudinal_eligible ? 'Used for weekly comparison' : 'Not used for weekly comparison'}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <AnalysisBadges availability={item.analysis.availability} level={item.analysis.deviation_level} />
                </td>
                <td className="px-3 py-2">
                  {item.alert ? (
                    <Link
                      to={`/doctor/alerts/${item.alert.alert_id}`}
                      aria-label={`Open review (status ${WORKFLOW_LABEL[item.alert.workflow_status]})`}
                      className="inline-flex flex-col gap-1 underline"
                    >
                      <AlertWorkflowBadge status={item.alert.workflow_status} />
                      <span className="text-xs">Open review</span>
                    </Link>
                  ) : (
                    <span className="text-slate-500">None</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-col gap-1">
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(item.assessment_id)}
                      className="min-h-11 rounded-md border border-slate-300 px-3 font-semibold whitespace-nowrap hover:bg-slate-50 aria-pressed:border-indigo-500 aria-pressed:bg-indigo-100"
                    >
                      {selected ? 'Showing details' : 'Show details'}
                      <span className="sr-only"> for the check-in observed {formatInZone(item.observed_at, timeZone)}</span>
                    </button>
                    <Link
                      to={`/doctor/patients/${patientId}/assessments/${item.assessment_id}`}
                      className="text-xs underline"
                    >
                      Full page<span className="sr-only"> for the check-in observed {formatInZone(item.observed_at, timeZone)}</span>
                    </Link>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
