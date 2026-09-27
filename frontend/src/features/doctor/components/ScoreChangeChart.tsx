import { useRef } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { InsightAssessment } from '../schemas'
import { formatDateInZone, formatInZone } from '../utils/dateFormatting'
import { changePairs } from '../utils/insightPresentation'
import { formatIndex, formatPoints } from '../utils/valueFormatting'
import { InsightPanel } from './InsightPanel'
import { useChartEntrance } from '../utils/chartEntrance'

export function ScoreChangeChart({
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
  const { pairs, skippedPairs } = changePairs(records)
  const chartRef = useRef<HTMLDivElement>(null)
  useChartEntrance(chartRef, pairs.length > 0, 'zero-line')
  const data = pairs.map((pair) => ({
    x: Date.parse(pair.current.observed_at),
    delta: pair.delta,
    pair,
  }))

  return (
    <InsightPanel
      title="Change between comparable assessments"
      unit="points · current composite − previous composite"
      count={`${pairs.length} consecutive comparable pair${pairs.length === 1 ? '' : 's'}; ${skippedPairs} skipped because of a gap, ineligible interruption, missing composite, or segment/source change`}
      explanation="A bar exists only when two adjacent weekly representatives in this range share a score version, comparability segment and source. The first point in the range has no bar. Bars are not labeled recovery or progression."
      table={
        <table className="min-w-full text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1 text-left">Previous</th>
              <th className="px-2 py-1 text-left">Current</th>
              <th className="px-2 py-1 text-left">Change</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((pair) => (
              <tr key={pair.current.assessment_id}>
                <td className="px-2 py-1">
                  {formatInZone(pair.previous.observed_at, timeZone)} · {formatIndex(pair.previous.cognitive_index.observed_value)}
                </td>
                <td className="px-2 py-1">
                  {formatInZone(pair.current.observed_at, timeZone)} · {formatIndex(pair.current.cognitive_index.observed_value)}
                </td>
                <td className="px-2 py-1 tabular-nums">{formatPoints(pair.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {pairs.length === 0 ? (
        <p className="text-sm text-slate-600">
          {records.filter((r) => r.is_representative && r.cognitive_index.observed_value !== null).length < 2
            ? 'One or fewer eligible scores in this range, so there is no change bar.'
            : 'No two adjacent comparable assessments produced a change value.'}
        </p>
      ) : (
        <div ref={chartRef} aria-hidden="true" className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis
                dataKey="x"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickFormatter={(ms: number) => formatDateInZone(ms, timeZone)}
                tick={{ fontSize: 11 }}
              />
              <YAxis tick={{ fontSize: 11 }} unit=" pts" />
              <ReferenceLine y={0} stroke="#64748b" />
              <Tooltip
                isAnimationActive={false}
                content={({ active, payload }) => {
                  const row = active ? (payload?.[0]?.payload as (typeof data)[number] | undefined) : undefined
                  if (!row) return null
                  return (
                    <div className="max-w-xs rounded-md border border-slate-300 bg-white p-2 text-xs shadow">
                      <p>
                        {formatInZone(row.pair.previous.observed_at, timeZone)} →{' '}
                        {formatInZone(row.pair.current.observed_at, timeZone)}
                      </p>
                      <p>
                        {formatIndex(row.pair.previous.cognitive_index.observed_value)} →{' '}
                        {formatIndex(row.pair.current.cognitive_index.observed_value)}
                      </p>
                      <p className="font-semibold">{formatPoints(row.delta)}</p>
                    </div>
                  )
                }}
              />
              <Bar
                dataKey="delta"
                isAnimationActive={false}
                onClick={(entry) => {
                  const id = (entry as { pair?: { current: InsightAssessment } }).pair?.current.assessment_id
                  if (id) onSelect(id)
                }}
              >
                {data.map((row) => (
                  <Cell
                    key={row.pair.current.assessment_id}
                    fill={row.delta >= 0 ? '#4338ca' : '#64748b'}
                    stroke={row.pair.current.assessment_id === selectedId ? '#0f172a' : undefined}
                    strokeWidth={row.pair.current.assessment_id === selectedId ? 2 : 0}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </InsightPanel>
  )
}
