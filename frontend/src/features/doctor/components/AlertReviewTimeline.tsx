import { useRef } from 'react'
import { Link } from 'react-router-dom'
import type { InsightAssessment } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { DEVIATION_LABEL, WORKFLOW_LABEL } from '../utils/displayLabels'
import { linkedAlerts, workflowCounts } from '../utils/insightPresentation'
import { InsightPanel } from './InsightPanel'
import { AlertWorkflowBadge, DeviationBadge } from './Badges'
import { useChartEntrance } from '../utils/chartEntrance'

export function AlertReviewTimeline({
  records,
  timeZone,
  selectedId,
  onSelect,
}: {
  records: InsightAssessment[]
  timeZone: string
  selectedId: string | null
  onSelect: (assessmentId: string) => void
}) {
  const items = linkedAlerts(records)
  const counts = workflowCounts(records)
  const listRef = useRef<HTMLOListElement>(null)
  useChartEntrance(listRef, items.length > 0, 'html')

  return (
    <InsightPanel
      title="Alert and review timeline"
      unit="current workflow status of alerts linked to assessments in this range"
      count={`${items.length} linked alert${items.length === 1 ? '' : 's'} · ${counts.OPEN} open / ${counts.ACKNOWLEDGED} acknowledged / ${counts.RESOLVED} resolved`}
      explanation="Markers sit at the linked assessment’s observed time. The tooltip also shows when the alert was created. This is the alert’s current status, not a reconstruction of its status on that date. Resolved alerts stay visible with their original category. No new alerts are inferred from the chart."
      table={
        <table className="min-w-full text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1 text-left">Observed</th>
              <th className="px-2 py-1 text-left">Created</th>
              <th className="px-2 py-1 text-left">Category</th>
              <th className="px-2 py-1 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map(({ record, alert }) => (
              <tr key={alert.alert_id}>
                <td className="px-2 py-1">{formatInZone(record.observed_at, timeZone)}</td>
                <td className="px-2 py-1">{formatInZone(alert.created_at, timeZone)}</td>
                <td className="px-2 py-1">{DEVIATION_LABEL[alert.deviation_level]}</td>
                <td className="px-2 py-1">{WORKFLOW_LABEL[alert.workflow_status]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {items.length === 0 ? (
        <p className="text-sm text-slate-600">No alerts linked to assessments in this range.</p>
      ) : (
        <ol ref={listRef} data-entrance="fade" className="relative space-y-3 border-l-2 border-indigo-100 pl-4">
          {items.map(({ record, alert }) => {
            const selected = record.assessment_id === selectedId
            return (
              <li key={alert.alert_id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onSelect(record.assessment_id)}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm ${
                    selected ? 'border-indigo-600 bg-indigo-50' : 'border-slate-200 bg-slate-50 hover:bg-white'
                  }`}
                >
                  <p className="font-medium">{formatInZone(record.observed_at, timeZone)}</p>
                  <p className="text-xs text-slate-600">Alert created {formatInZone(alert.created_at, timeZone)}</p>
                  <p className="mt-1 flex flex-wrap gap-2">
                    <DeviationBadge level={alert.deviation_level} />
                    <AlertWorkflowBadge status={alert.workflow_status} />
                  </p>
                </button>
                {selected && (
                  <p className="mt-2 text-sm">
                    <Link to={`/doctor/alerts/${alert.alert_id}`} className="font-semibold text-indigo-800 underline">
                      Open alert
                    </Link>
                  </p>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </InsightPanel>
  )
}
