import { useRef } from 'react'
import { useChartEntrance } from '../utils/chartEntrance'
import { formatInZone } from '../utils/dateFormatting'
import { QUALITY_LABEL, reasonText } from '../utils/displayLabels'
import { HEATMAP_ROWS, heatmapColumns, sequentialFill } from '../utils/insightPresentation'
import type { InsightAssessment } from '../schemas'
import { formatDomainValue, formatIndex } from '../utils/valueFormatting'
import { InsightPanel } from './InsightPanel'

export function DomainHeatmap({
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
  const { columns, extras } = heatmapColumns(records)
  const gridRef = useRef<HTMLDivElement>(null)
  useChartEntrance(gridRef, columns.length > 0, 'html')
  const cell = (value: number | null, row: string, date: string) =>
    value === null ? `No ${row} value on ${date}` : `${row} ${value.toFixed(1)} on ${date}`

  return (
    <InsightPanel
      title="Domain performance heatmap"
      unit="0–100 sequential palette · darker is a higher recorded value, not a diagnosis"
      count={`${columns.length} weekly-slot column${columns.length === 1 ? '' : 's'}; ${extras.length} extra/off-schedule check-in${extras.length === 1 ? '' : 's'} listed separately`}
      explanation="Eligible weekly check-ins as columns, grouped by comparability segment. Unusable columns are patterned, not colored as zero. Response speed is the normalized component; raw reaction time stays in the tooltip."
      table={
        <table className="min-w-full text-sm">
          <caption className="sr-only">Heatmap values for the selected range</caption>
          <thead>
            <tr>
              <th scope="col" className="px-2 py-1 text-left">
                Observed
              </th>
              {HEATMAP_ROWS.map((row) => (
                <th key={row.key} scope="col" className="px-2 py-1 text-left">
                  {row.label}
                </th>
              ))}
              <th scope="col" className="px-2 py-1 text-left">
                Reaction time
              </th>
            </tr>
          </thead>
          <tbody>
            {columns.map((column) => (
              <tr key={column.assessmentId} className={column.assessmentId === selectedId ? 'bg-indigo-50' : undefined}>
                <th scope="row" className="px-2 py-1 text-left font-medium">
                  {formatInZone(column.observedAt, timeZone)}
                </th>
                <td className="px-2 py-1 tabular-nums">{column.memory?.toFixed(1) ?? '—'}</td>
                <td className="px-2 py-1 tabular-nums">{column.attention?.toFixed(1) ?? '—'}</td>
                <td className="px-2 py-1 tabular-nums">{column.responseSpeed?.toFixed(1) ?? '—'}</td>
                <td className="px-2 py-1">{formatDomainValue('reaction_time_ms', column.reactionTimeMs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {columns.length === 0 ? (
        <p className="text-sm text-slate-600">No weekly-slot assessments in this range to plot as columns.</p>
      ) : (
        <div ref={gridRef} className="relative overflow-x-auto" tabIndex={0} role="region" aria-label="Domain heatmap">
          <div
            data-entrance="fade"
            className="grid min-w-max gap-px bg-slate-200"
            style={{ gridTemplateColumns: `8.5rem repeat(${columns.length}, 2.75rem)` }}
          >
            <div className="bg-white p-2 text-xs font-medium text-slate-500">Check-in</div>
            {columns.map((column, index) => {
              const prev = columns[index - 1]
              const newSegment = Boolean(prev && prev.segmentKey !== column.segmentKey)
              return (
                <button
                  key={`h-${column.assessmentId}`}
                  type="button"
                  aria-pressed={column.assessmentId === selectedId}
                  title={formatInZone(column.observedAt, timeZone)}
                  onClick={() => onSelect(column.assessmentId)}
                  className={`bg-white px-0.5 py-2 text-[10px] leading-tight ${
                    column.assessmentId === selectedId ? 'ring-2 ring-indigo-600 ring-inset' : ''
                  } ${newSegment ? 'border-l-2 border-indigo-300' : ''}`}
                >
                  {formatInZone(column.observedAt, timeZone).split(',')[0]}
                </button>
              )
            })}
            {HEATMAP_ROWS.map((row) => (
              <HeatmapRow
                key={row.key}
                label={row.label}
                columns={columns}
                rowKey={row.key === 'response_speed' ? 'responseSpeed' : row.key}
                selectedId={selectedId}
                timeZone={timeZone}
                cell={cell}
                onSelect={onSelect}
              />
            ))}
          </div>
          <ol className="mt-3 flex flex-wrap items-center gap-1 text-xs" aria-label="0 to 100 color legend">
            <li className="mr-1 text-slate-600">0</li>
            {Array.from({ length: 10 }, (_, i) => (
              <li key={i} className="h-3 w-5 border border-slate-200" style={{ background: sequentialFill(i * 10 + 5) }} />
            ))}
            <li className="ml-1 text-slate-600">100</li>
            <li className="ml-3 inline-flex items-center gap-1">
              <span className="inline-block h-3 w-5 border border-slate-300 bg-[repeating-linear-gradient(45deg,#f8fafc,#f8fafc_3px,#e2e8f0_3px,#e2e8f0_6px)]" />
              Unusable
            </li>
          </ol>
        </div>
      )}
      {extras.length > 0 && (
        <div className="mt-4 text-sm">
          <h3 className="font-medium">Extra and off-schedule check-ins</h3>
          <p className="text-slate-600">Shown here so they are not treated as extra weekly columns.</p>
          <ul className="mt-1 list-disc pl-5">
            {extras.map((record) => (
              <li key={record.assessment_id}>
                <button type="button" className="underline" onClick={() => onSelect(record.assessment_id)}>
                  {formatInZone(record.observed_at, timeZone)} ·{' '}
                  {formatIndex(record.cognitive_index.observed_value)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </InsightPanel>
  )
}

function HeatmapRow({
  label,
  columns,
  rowKey,
  selectedId,
  timeZone,
  cell,
  onSelect,
}: {
  label: string
  columns: ReturnType<typeof heatmapColumns>['columns']
  rowKey: 'memory' | 'attention' | 'responseSpeed'
  selectedId: string | null
  timeZone: string
  cell: (value: number | null, row: string, date: string) => string
  onSelect: (id: string) => void
}) {
  return (
    <>
      <div className="bg-white p-2 text-sm font-medium">{label}</div>
      {columns.map((column) => {
        const value = column[rowKey]
        const date = formatInZone(column.observedAt, timeZone)
        return (
          <button
            key={`${rowKey}-${column.assessmentId}`}
            type="button"
            aria-pressed={column.assessmentId === selectedId}
            aria-label={`${cell(value, label, date)}${column.usable ? '' : `; ${QUALITY_LABEL[column.quality]}`}${
              column.reasons[0] ? `; ${reasonText(column.reasons[0])}` : ''
            }${rowKey === 'responseSpeed' && column.reactionTimeMs != null ? `; raw ${Math.round(column.reactionTimeMs)} ms` : ''}`}
            onClick={() => onSelect(column.assessmentId)}
            className={`min-h-11 border border-transparent text-[11px] tabular-nums ${
              column.assessmentId === selectedId ? 'ring-2 ring-indigo-600 ring-inset' : ''
            } ${
              column.usable
                ? 'text-slate-900'
                : 'bg-[repeating-linear-gradient(45deg,#f8fafc,#f8fafc_3px,#e2e8f0_3px,#e2e8f0_6px)] text-slate-500'
            }`}
            style={column.usable ? { background: sequentialFill(value) } : undefined}
          >
            {value === null ? '—' : value.toFixed(0)}
          </button>
        )
      })}
    </>
  )
}
