import { useId, useRef } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TimelineItem } from '../schemas'
import {
  buildCompositeSeries,
  timeDomain,
  weeklyTicks,
  type ForecastPoint,
  type ObservedPoint,
} from '../utils/chartSeries'
import { formatDateInZone, formatInZone } from '../utils/dateFormatting'
import {
  AVAILABILITY_LABEL,
  DEVIATION_LABEL,
  PURPOSE_LABEL,
  QUALITY_LABEL,
  reasonText,
} from '../utils/displayLabels'
import { formatDomainValue, formatIndex } from '../utils/valueFormatting'
import { useChartEntrance } from '../utils/chartEntrance'

// Same visual language as the task charts on this page: solid observed, dashed forecast composite,
// separate markers for unreliable / not-weekly / flagged check-ins, and no smoothing.
const COLOR = {
  observed: '#4338ca',
  forecast: '#475569',
  lowQuality: '#b45309',
  notWeekly: '#0f766e',
  flagged: '#b91c1c',
  grid: '#e2e8f0',
}

type Datum = (ObservedPoint | ForecastPoint) & { series: 'observed' | 'forecast' }

function HollowCircle(props: { cx?: number; cy?: number }) {
  if (props.cx === undefined || props.cy === undefined) return null
  return <circle cx={props.cx} cy={props.cy} r={4} fill="#fff" stroke={COLOR.forecast} strokeWidth={2} />
}

function FlagRing(props: { cx?: number; cy?: number }) {
  if (props.cx === undefined || props.cy === undefined) return null
  return <circle cx={props.cx} cy={props.cy} r={8} fill="none" stroke={COLOR.flagged} strokeWidth={2} />
}

function ScoreTooltip({
  active,
  payload,
  timeZone,
}: {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: unknown }>
  timeZone: string
}) {
  const datum = active ? (payload?.[0]?.payload as Datum | undefined) : undefined
  if (!datum) return null
  const { item } = datum
  const index = item.cognitive_index
  const level = item.analysis.deviation_level
  return (
    <div className="max-w-xs rounded-md border border-slate-300 bg-white p-2 text-xs text-slate-800 shadow">
      <p className="font-semibold">
        {datum.series === 'forecast' ? 'Composite of task forecasts' : 'Observed Cognitive Score'}
      </p>
      <p>Observed: {formatInZone(item.observed_at, timeZone)}</p>
      <p>Target: {formatInZone(item.target_at, timeZone)}</p>
      <p>Score: {formatIndex(index.observed_value)}</p>
      <p>Forecast composite: {formatIndex(index.forecast_value)}</p>
      {index.observed_components && (
        <p>
          From memory {formatDomainValue('memory', index.observed_components.memory)}, attention{' '}
          {formatDomainValue('attention', index.observed_components.attention)}, response speed{' '}
          {index.observed_components.response_speed.toFixed(1)} (reaction time{' '}
          {formatDomainValue('reaction_time_ms', item.scores.reaction_time_ms)})
        </p>
      )}
      {index.observed_value === null && index.observed_unavailable_reasons.length > 0 && (
        <p>{reasonText(index.observed_unavailable_reasons[0])}</p>
      )}
      <p>{PURPOSE_LABEL[item.schedule_purpose]}</p>
      <p>
        Quality: {QUALITY_LABEL[item.quality_status]} ·{' '}
        {item.longitudinal_eligible ? 'Used for weekly comparison' : 'Not used for weekly comparison'}
      </p>
      <p>
        Analysis: {AVAILABILITY_LABEL[item.analysis.availability]}
        {level && ` · ${DEVIATION_LABEL[level]}`}
      </p>
      <p className="text-slate-500">Score version {index.version}</p>
    </div>
  )
}

export function CognitiveScoreChart({
  items,
  timeZone,
  partial,
  onSelect,
}: {
  items: TimelineItem[]
  timeZone: string
  partial: boolean
  onSelect: (assessmentId: string) => void
}) {
  const descId = useId()
  const chartRef = useRef<HTMLDivElement>(null)
  const xDomain = timeDomain(items)
  const series = buildCompositeSeries(items)
  const weekly = series.observedSegments.flat()
  useChartEntrance(chartRef, xDomain !== null && items.length > 0)
  if (!xDomain) return null

  const observed: Datum[] = weekly.map((p) => ({ ...p, series: 'observed' }))
  const forecasts: Datum[] = series.forecastSegments.flat().map((p) => ({ ...p, series: 'forecast' }))
  const low: Datum[] = series.lowQuality.map((p) => ({ ...p, series: 'observed' }))
  const notWeekly: Datum[] = series.notWeekly.map((p) => ({ ...p, series: 'observed' }))
  const flagged: Datum[] = series.flagged.map((p) => ({ ...p, series: 'observed' }))
  const select = (datum: unknown) => {
    const id = (datum as { payload?: Datum } | undefined)?.payload?.item.assessment_id
    if (id) onSelect(id)
  }

  return (
    <figure aria-describedby={descId}>
      <figcaption id={descId} className="text-sm text-slate-600">
        Cognitive Score across {items.length} loaded assessment{items.length === 1 ? '' : 's'}
        {partial ? ' (older check-ins not loaded)' : ''}. 0–100; higher combines better task
        performance. {weekly.length} weekly score{weekly.length === 1 ? '' : 's'},{' '}
        {series.lowQuality.length + series.notWeekly.length} shown separately as not used for weekly
        comparison, {series.unavailableCount} without a composite, {series.forecastCount} forecast
        composite{series.forecastCount === 1 ? '' : 's'}
        {series.versionChanges.length ? `, ${series.versionChanges.length} model/policy change(s)` : ''}. The
        assessment table below lists the same check-ins.
      </figcaption>
      <div ref={chartRef} aria-hidden="true" className="mt-3 h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={COLOR.grid} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              domain={xDomain}
              ticks={weeklyTicks(items)}
              interval={0}
              allowDataOverflow
              tickFormatter={(ms: number) => formatDateInZone(ms, timeZone)}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[0, 100]}
              allowDataOverflow
              width={52}
              tick={{ fontSize: 11 }}
              label={{ value: 'index', angle: -90, position: 'insideLeft', fontSize: 11 }}
            />
            {series.versionChanges.map((change) => (
              <ReferenceLine
                key={`v-${change.x}`}
                x={change.x}
                stroke="#94a3b8"
                strokeDasharray="2 2"
                label={{ value: 'Model/policy change', position: 'insideTopLeft', fontSize: 10, fill: '#475569' }}
              />
            ))}
            {series.forecastSegments.map((segment, i) => (
              <Line
                key={`f-${i}`}
                data={segment}
                dataKey="y"
                type="linear"
                stroke={COLOR.forecast}
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                activeDot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
            {series.observedSegments.map((segment, i) => (
              <Line
                key={`o-${i}`}
                data={segment}
                dataKey="y"
                type="linear"
                stroke={COLOR.observed}
                strokeWidth={2.5}
                dot={false}
                activeDot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
            <Scatter data={forecasts} dataKey="y" shape={<HollowCircle />} isAnimationActive={false} onClick={select} />
            <Scatter data={observed} dataKey="y" fill={COLOR.observed} isAnimationActive={false} onClick={select} />
            <Scatter data={low} dataKey="y" shape="triangle" fill={COLOR.lowQuality} isAnimationActive={false} onClick={select} />
            <Scatter data={notWeekly} dataKey="y" shape="diamond" fill={COLOR.notWeekly} isAnimationActive={false} onClick={select} />
            <Scatter data={flagged} dataKey="y" shape={<FlagRing />} isAnimationActive={false} onClick={select} />
            <Tooltip
              shared={false}
              isAnimationActive={false}
              content={(props) => <ScoreTooltip active={props.active} payload={props.payload} timeZone={timeZone} />}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}
