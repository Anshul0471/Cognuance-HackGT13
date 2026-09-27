import { useRef } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { InsightAssessment } from '../schemas'
import { AVAILABILITY_LABEL, QUALITY_LABEL } from '../utils/displayLabels'
import { AVAILABILITY_ORDER, availabilityCounts, qualityCounts } from '../utils/insightPresentation'
import { InsightPanel } from './InsightPanel'
import { useChartEntrance } from '../utils/chartEntrance'

const QUALITY_COLOR = { VALID: '#4338ca', LOW: '#b45309', INCOMPLETE: '#64748b' }

export function AssessmentQualityCharts({ records }: { records: InsightAssessment[] }) {
  const total = records.length
  const pieRef = useRef<HTMLDivElement>(null)
  const barsRef = useRef<HTMLUListElement>(null)
  useChartEntrance(pieRef, total > 0, 'pie')
  useChartEntrance(barsRef, total > 0, 'html')
  const quality = qualityCounts(records)
  const availability = availabilityCounts(records)
  const slices = (['VALID', 'LOW', 'INCOMPLETE'] as const).map((key) => ({
    key,
    name: QUALITY_LABEL[key],
    value: quality[key],
  }))
  const qualitySum = slices.reduce((sum, slice) => sum + slice.value, 0)
  const availabilitySum = AVAILABILITY_ORDER.reduce((sum, key) => sum + availability[key], 0)

  return (
    <InsightPanel
      title="Assessment quality and analysis availability"
      unit="counts of submitted assessments · not a health measure"
      count={`${total} submitted assessment${total === 1 ? '' : 's'} (quality ${qualitySum}, availability ${availabilitySum})`}
      explanation="Quality and availability are different dimensions; each chart’s counts sum to the same total. An empty range is “No submitted assessments,” not 100% completion."
      table={
        <table className="min-w-full text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1 text-left">Category</th>
              <th className="px-2 py-1 text-left">Count</th>
            </tr>
          </thead>
          <tbody>
            {slices.map((slice) => (
              <tr key={slice.key}>
                <td className="px-2 py-1">{slice.name}</td>
                <td className="px-2 py-1 tabular-nums">
                  {slice.value} / {total}
                </td>
              </tr>
            ))}
            {AVAILABILITY_ORDER.map((key) => (
              <tr key={key}>
                <td className="px-2 py-1">{AVAILABILITY_LABEL[key]}</td>
                <td className="px-2 py-1 tabular-nums">
                  {availability[key]} / {total}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {total === 0 ? (
        <p className="text-sm text-slate-600">No submitted assessments.</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium">Task quality</h3>
            <div ref={pieRef} className="relative mx-auto h-44 w-44" aria-hidden="true">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={slices.filter((s) => s.value > 0)}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={48}
                    outerRadius={70}
                    isAnimationActive={false}
                  >
                    {slices
                      .filter((s) => s.value > 0)
                      .map((slice) => (
                        <Cell key={slice.key} fill={QUALITY_COLOR[slice.key]} />
                      ))}
                  </Pie>
                  <Tooltip isAnimationActive={false} />
                </PieChart>
              </ResponsiveContainer>
              <p className="absolute inset-0 flex items-center justify-center text-sm font-semibold">{total}</p>
            </div>
            <ul className="text-sm">
              {slices.map((slice) => (
                <li key={slice.key}>
                  {slice.name}: {slice.value} / {total}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-medium">Analysis availability</h3>
            <ul ref={barsRef} className="mt-2 space-y-2">
              {AVAILABILITY_ORDER.map((key) => (
                <li key={key}>
                  <div className="flex justify-between text-sm">
                    <span>{AVAILABILITY_LABEL[key]}</span>
                    <span className="tabular-nums">
                      {availability[key]} / {total}
                    </span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-slate-100">
                    <div
                      data-entrance="bar-x"
                      className="h-2 rounded-full bg-indigo-600"
                      style={{ width: `${total ? (availability[key] / total) * 100 : 0}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </InsightPanel>
  )
}
