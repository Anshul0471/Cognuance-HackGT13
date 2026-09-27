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
  buildDomainSeries,
  FORECAST_FIELD,
  OBSERVED_FIELD,
  reactionAxisMax,
  timeDomain,
  weeklyTicks,
  type ChartDomain,
  type ForecastPoint,
  type ObservedPoint,
} from '../utils/chartSeries'
import { formatDateInZone, formatInZone } from '../utils/dateFormatting'
import {
  AVAILABILITY_LABEL,
  DEVIATION_LABEL,
  PURPOSE_LABEL,
  QUALITY_LABEL,
} from '../utils/displayLabels'
import { formatDomainValue } from '../utils/valueFormatting'
import { useChartEntrance } from '../utils/chartEntrance'

const COLOR = {
  observed: '#4338ca',
  forecast: '#475569',
  lowQuality: '#b45309',
  notWeekly: '#0f766e',
  flagged: '#b91c1c',
  grid: '#e2e8f0',
}

const CHARTS: { domain: ChartDomain; title: string; direction: string }[] = [
  { domain: 'memory', title: 'Memory task', direction: 'Score 0–100; higher is better task performance.' },
  { domain: 'attention', title: 'Attention task', direction: 'Score 0–100; higher is better task performance.' },
  {
    domain: 'reaction_time_ms',
    title: 'Reaction time',
    direction: 'Milliseconds from zero; higher means slower responses. Not comparable with the 0–100 scores.',
  },
]

type Datum = (ObservedPoint | ForecastPoint) & { series: 'observed' | 'forecast' }

function HollowCircle(props: { cx?: number; cy?: number }) {
  if (props.cx === undefined || props.cy === undefined) return null
  return <circle cx={props.cx} cy={props.cy} r={4} fill="#fff" stroke={COLOR.forecast} strokeWidth={2} />
}

function FlagRing(props: { cx?: number; cy?: number }) {
  if (props.cx === undefined || props.cy === undefined) return null
  return <circle cx={props.cx} cy={props.cy} r={8} fill="none" stroke={COLOR.flagged} strokeWidth={2} />
}

function PointTooltip({
  active,
  payload,
  domain,
  timeZone,
}: {
  active?: boolean
  payload?: ReadonlyArray<{ payload?: unknown }>
  domain: ChartDomain
  timeZone: string
}) {
  const datum = active ? (payload?.[0]?.payload as Datum | undefined) : undefined
  if (!datum) return null
  const { item } = datum
  const observed = item.scores[OBSERVED_FIELD[domain]]
  const forecast = item.forecast ? item.forecast[FORECAST_FIELD[domain]] : null
  const level = item.analysis.deviation_level
  return (
    <div className="max-w-xs rounded-md border border-slate-300 bg-white p-2 text-xs text-slate-800 shadow">
      <p className="font-semibold">{datum.series === 'forecast' ? 'Stored forecast' : 'Observed result'}</p>
      <p>Observed: {formatInZone(item.observed_at, timeZone)}</p>
      <p>Target: {formatInZone(item.target_at, timeZone)}</p>
      <p>{PURPOSE_LABEL[item.schedule_purpose]}</p>
      <p>Result: {formatDomainValue(domain, observed)}</p>
      <p>Forecast: {forecast === null ? 'No stored forecast' : formatDomainValue(domain, forecast)}</p>
      {item.forecast && (
        <p>
          Model/policy: {item.forecast.model_version} · {item.forecast.policy_version}
        </p>
      )}
      <p>
        Quality: {QUALITY_LABEL[item.quality_status]} ·{' '}
        {item.longitudinal_eligible ? 'Used for weekly comparison' : 'Not used for weekly comparison'}
      </p>
      <p>
        Analysis: {AVAILABILITY_LABEL[item.analysis.availability]}
        {level && ` · ${DEVIATION_LABEL[level]}`}
      </p>
    </div>
  )
}

export function ChartLegend() {
  const row = 'flex items-center gap-2'
  return (
    <ul aria-label="Chart legend" className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-700">
      <li className={row}>
        <svg aria-hidden="true" width="28" height="12">
          <line x1="0" y1="6" x2="28" y2="6" stroke={COLOR.observed} strokeWidth="2" />
          <circle cx="14" cy="6" r="4" fill={COLOR.observed} />
        </svg>
        Observed weekly check-in (solid; joined only across consecutive weeks)
      </li>
      <li className={row}>
        <svg aria-hidden="true" width="28" height="12">
          <line x1="0" y1="6" x2="28" y2="6" stroke={COLOR.forecast} strokeWidth="2" strokeDasharray="5 3" />
          <circle cx="14" cy="6" r="4" fill="#fff" stroke={COLOR.forecast} strokeWidth="2" />
        </svg>
        Stored forecast at its target time (dashed)
      </li>
      <li className={row}>
        <svg aria-hidden="true" width="14" height="12">
          <polygon points="7,1 13,11 1,11" fill={COLOR.lowQuality} />
        </svg>
        Low quality or incomplete (not compared)
      </li>
      <li className={row}>
        <svg aria-hidden="true" width="14" height="12">
          <polygon points="7,0 13,6 7,12 1,6" fill={COLOR.notWeekly} />
        </svg>
        Saved but not used for weekly comparison (extra, off-schedule, or later same-week attempt)
      </li>
      <li className={row}>
        <svg aria-hidden="true" width="16" height="16">
          <circle cx="8" cy="8" r="6" fill="none" stroke={COLOR.flagged} strokeWidth="2" />
        </svg>
        Check-in flagged for review
      </li>
      <li className={row}>
        <svg aria-hidden="true" width="12" height="16">
          <line x1="6" y1="0" x2="6" y2="16" stroke="#94a3b8" strokeWidth="2" strokeDasharray="2 2" />
        </svg>
        Forecast model or policy version changed
      </li>
    </ul>
  )
}

function DomainChart({
  domain,
  title,
  direction,
  items,
  xDomain,
  ticks,
  rtMax,
  timeZone,
  partial,
  onSelect,
}: {
  domain: ChartDomain
  title: string
  direction: string
  items: TimelineItem[]
  xDomain: [number, number]
  ticks: number[]
  rtMax: number
  timeZone: string
  partial: boolean
  onSelect: (assessmentId: string) => void
}) {
  const headingId = useId()
  const descId = useId()
  const chartRef = useRef<HTMLDivElement>(null)
  const series = buildDomainSeries(items, domain)
  useChartEntrance(chartRef, items.length > 0)
  const weekly = series.observedSegments.flat()
  const observed: Datum[] = weekly.map((p) => ({ ...p, series: 'observed' }))
  const forecasts: Datum[] = series.forecastSegments.flat().map((p) => ({ ...p, series: 'forecast' }))
  const low: Datum[] = series.lowQuality.map((p) => ({ ...p, series: 'observed' }))
  const notWeekly: Datum[] = series.notWeekly.map((p) => ({ ...p, series: 'observed' }))
  const flagged: Datum[] = series.flagged.map((p) => ({ ...p, series: 'observed' }))
  const select = (datum: unknown) => {
    const id = (datum as { payload?: Datum } | undefined)?.payload?.item.assessment_id
    if (id) onSelect(id)
  }
  const yDomain: [number, number] = domain === 'reaction_time_ms' ? [0, rtMax] : [0, 100]

  return (
    <figure aria-labelledby={headingId} aria-describedby={descId} className="rounded-lg border border-slate-200 bg-white p-4">
      <figcaption>
        <h3 id={headingId} className="font-semibold">
          {title}
        </h3>
        <p id={descId} className="text-sm text-slate-600">
          {title} results and forecasts across {items.length} loaded assessment{items.length === 1 ? '' : 's'}
          {partial ? ' (older check-ins not loaded)' : ''}. {direction} {weekly.length} weekly result
          {weekly.length === 1 ? '' : 's'}, {series.lowQuality.length} low quality or incomplete,{' '}
          {series.notWeekly.length} not used for weekly comparison, {series.unavailableCount} without a result for this
          task, {series.forecastCount} stored forecast{series.forecastCount === 1 ? '' : 's'}
          {series.versionChanges.length ? `, ${series.versionChanges.length} model/policy change(s)` : ''}. The table
          below lists the same evidence.
        </p>
      </figcaption>
      <div ref={chartRef} aria-hidden="true" className="mt-3 h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={COLOR.grid} strokeDasharray="3 3" />
            <XAxis
              type="number"
              dataKey="x"
              domain={xDomain}
              ticks={ticks}
              interval={0}
              allowDataOverflow
              tickFormatter={(ms: number) => formatDateInZone(ms, timeZone)}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={yDomain}
              allowDataOverflow
              width={52}
              tick={{ fontSize: 11 }}
              label={{
                value: domain === 'reaction_time_ms' ? 'ms' : 'points',
                angle: -90,
                position: 'insideLeft',
                fontSize: 11,
              }}
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
                strokeWidth={2}
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
              content={(props) => (
                <PointTooltip active={props.active} payload={props.payload} domain={domain} timeZone={timeZone} />
              )}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

export function PatientTimelineCharts({
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
  const xDomain = timeDomain(items)
  if (!xDomain) return null
  const rtMax = reactionAxisMax(items)
  const ticks = weeklyTicks(items)
  return (
    <div className="grid gap-4">
      {CHARTS.map((chart) => (
        <DomainChart
          key={chart.domain}
          {...chart}
          items={items}
          xDomain={xDomain}
          ticks={ticks}
          rtMax={rtMax}
          timeZone={timeZone}
          partial={partial}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}
