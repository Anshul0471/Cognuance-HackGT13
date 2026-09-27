import { useRef } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { InsightAssessment } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { eligibleScores, histogram, median } from '../utils/insightPresentation'
import { formatIndex } from '../utils/valueFormatting'
import { InsightPanel } from './InsightPanel'
import { useChartEntrance } from '../utils/chartEntrance'

export function ScoreDistributionChart({
  records,
  timeZone,
}: {
  records: InsightAssessment[]
  timeZone: string
}) {
  const scored = eligibleScores(records)
  const values = scored.map((row) => row.value)
  const bins = histogram(values)
  const mid = median(values)
  const limited = values.length > 0 && values.length < 5
  const chartRef = useRef<HTMLDivElement>(null)
  useChartEntrance(chartRef, values.length > 0)

  return (
    <InsightPanel
      title="Score distribution"
      unit="eligible available Cognitive Scores in this range"
      count={`${values.length} included · median ${mid === null ? '—' : formatIndex(mid)}`}
      explanation="Fixed bins [0,10) through [90,100]. Only this patient’s included observations; no other-patient comparison, percentile or bell curve."
      table={
        limited ? (
          <table className="min-w-full text-sm">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left">Observed</th>
                <th className="px-2 py-1 text-left">Score</th>
              </tr>
            </thead>
            <tbody>
              {scored.map((row) => (
                <tr key={row.record.assessment_id}>
                  <td className="px-2 py-1">{formatInZone(row.record.observed_at, timeZone)}</td>
                  <td className="px-2 py-1 tabular-nums">{formatIndex(row.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left">Bin</th>
                <th className="px-2 py-1 text-left">Count</th>
              </tr>
            </thead>
            <tbody>
              {bins.map((bin) => (
                <tr key={bin.label}>
                  <td className="px-2 py-1">{bin.label}</td>
                  <td className="px-2 py-1 tabular-nums">{bin.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      }
    >
      {values.length === 0 ? (
        <p className="text-sm text-slate-600">No eligible available Cognitive Scores in this range.</p>
      ) : limited ? (
        <div>
          <p className="text-sm font-medium text-slate-800">Limited observations</p>
          <p className="text-sm text-slate-600">
            Fewer than five included assessments, so individual points are listed instead of a distribution.
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {scored.map((row) => (
              <li key={row.record.assessment_id}>
                {formatInZone(row.record.observed_at, timeZone)} · {formatIndex(row.value)}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div ref={chartRef} aria-hidden="true" className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bins} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip isAnimationActive={false} />
              <Bar dataKey="count" fill="#4338ca" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </InsightPanel>
  )
}
