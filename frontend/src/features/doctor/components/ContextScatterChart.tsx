import { useRef, useState } from 'react'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import type { InsightAssessment } from '../schemas'
import { formatInZone } from '../utils/dateFormatting'
import { contextPairs, type ContextAxis } from '../utils/insightPresentation'
import { formatIndex } from '../utils/valueFormatting'
import { InsightPanel } from './InsightPanel'
import { useChartEntrance } from '../utils/chartEntrance'

function MedicationMark({
  cx,
  cy,
  payload,
}: {
  cx?: number
  cy?: number
  payload?: { medication?: boolean | null }
}) {
  if (cx === undefined || cy === undefined) return null
  const change = payload?.medication
  const stroke = change === true ? '#b45309' : change === false ? '#4338ca' : '#64748b'
  const dash = change === null ? '2 2' : undefined
  return <circle cx={cx} cy={cy} r={5} fill="#fff" stroke={stroke} strokeWidth={2} strokeDasharray={dash} />
}

export function ContextScatterChart({
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
  const [axis, setAxis] = useState<ContextAxis>('sleep')
  const { included, missing } = contextPairs(records, axis)
  const selected = included.filter((p) => p.record.assessment_id === selectedId)
  const rest = included.filter((p) => p.record.assessment_id !== selectedId)
  const chartRef = useRef<HTMLDivElement>(null)
  useChartEntrance(chartRef, included.length > 0, 'scatter')

  return (
    <InsightPanel
      title="Context explorer"
      unit={axis === 'sleep' ? 'hours of sleep (x) · Cognitive Score (y)' : 'mood 1–10 (x) · Cognitive Score (y)'}
      count={`${included.length} included pair${included.length === 1 ? '' : 's'}; ${missing} eligible scores missing the selected context value`}
      explanation="Recorded together; this view does not establish cause. Changing the toggle never recomputes a Cognitive Score or a forecast."
      table={
        <table className="min-w-full text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1 text-left">Observed</th>
              <th className="px-2 py-1 text-left">{axis === 'sleep' ? 'Sleep (h)' : 'Mood'}</th>
              <th className="px-2 py-1 text-left">Score</th>
              <th className="px-2 py-1 text-left">Medication change</th>
            </tr>
          </thead>
          <tbody>
            {included.map((point) => (
              <tr key={point.record.assessment_id}>
                <td className="px-2 py-1">{formatInZone(point.record.observed_at, timeZone)}</td>
                <td className="px-2 py-1 tabular-nums">{point.x}</td>
                <td className="px-2 py-1">{formatIndex(point.y)}</td>
                <td className="px-2 py-1">{point.medication === null ? 'Unknown' : point.medication ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Context axis">
        {(['sleep', 'mood'] as const).map((choice) => (
          <button
            key={choice}
            type="button"
            aria-pressed={axis === choice}
            onClick={() => setAxis(choice)}
            className={`min-h-11 rounded-md px-3 text-sm font-medium ${
              axis === choice ? 'bg-indigo-700 text-white' : 'border border-slate-300 bg-white hover:bg-slate-50'
            }`}
          >
            {choice === 'sleep' ? 'Sleep hours' : 'Mood (1–10)'}
          </button>
        ))}
      </div>
      <p className="mb-2 text-sm font-medium text-slate-700">Recorded together; this view does not establish cause.</p>
      {included.length === 0 ? (
        <p className="text-sm text-slate-600">
          No eligible assessments have both an available Cognitive Score and a known {axis === 'sleep' ? 'sleep' : 'mood'}{' '}
          value.
        </p>
      ) : (
        <div ref={chartRef} aria-hidden="true" className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 4 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="x"
                name={axis}
                domain={axis === 'mood' ? [1, 10] : [0, 24]}
                tick={{ fontSize: 11 }}
              />
              <YAxis type="number" dataKey="y" domain={[0, 100]} tick={{ fontSize: 11 }} />
              <Tooltip
                isAnimationActive={false}
                content={({ active, payload }) => {
                  const point = active ? (payload?.[0]?.payload as (typeof included)[number] | undefined) : undefined
                  if (!point) return null
                  return (
                    <div className="max-w-xs rounded-md border border-slate-300 bg-white p-2 text-xs shadow">
                      <p>{formatInZone(point.record.observed_at, timeZone)}</p>
                      <p>{formatIndex(point.y)}</p>
                      <p>
                        {axis === 'sleep' ? `Sleep ${point.x} h` : `Mood ${point.x}`} · medication{' '}
                        {point.medication === null ? 'unknown' : point.medication ? 'yes' : 'no'}
                      </p>
                      <p>Reported by {point.record.context?.reported_by}</p>
                    </div>
                  )
                }}
              />
              <Scatter
                data={rest}
                shape={<MedicationMark />}
                isAnimationActive={false}
                onClick={(entry) => {
                  const id = (entry as { record?: InsightAssessment }).record?.assessment_id
                  if (id) onSelect(id)
                }}
              />
              <Scatter
                data={selected}
                shape={(props) => (
                  <g>
                    <MedicationMark {...props} />
                    {props.cx !== undefined && props.cy !== undefined && (
                      <circle cx={props.cx} cy={props.cy} r={9} fill="none" stroke="#0f172a" strokeWidth={2} />
                    )}
                  </g>
                )}
                isAnimationActive={false}
              />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-600">
        Marker outline: indigo = no medication change, amber = change reported, dashed slate = unknown.
      </p>
    </InsightPanel>
  )
}
