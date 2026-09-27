import type { ReactNode } from 'react'
import { cn } from '../../../lib/utils'

/** Shared Visual Insights card: title, unit, sample count, explanation, chart, and a data table. */
export function InsightPanel({
  title,
  unit,
  count,
  explanation,
  children,
  table,
  className,
}: {
  title: string
  unit: string
  count: string
  explanation: string
  children: ReactNode
  table: ReactNode
  className?: string
}) {
  return (
    <section className={cn('rounded-lg border border-slate-200 bg-white p-4', className)}>
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-xs font-medium tracking-wide text-indigo-700 uppercase">{unit}</p>
        <p className="text-sm text-slate-600">{count}</p>
        <p className="text-sm text-slate-600">{explanation}</p>
      </header>
      <div className="mt-4">{children}</div>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer font-medium text-indigo-800">View data</summary>
        <div className="relative mt-2 overflow-x-auto">{table}</div>
      </details>
    </section>
  )
}

export function ChartSkeleton({ label }: { label: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4" aria-busy="true">
      <p className="font-medium text-slate-700">{label}</p>
      <div className="mt-3 h-40 animate-pulse rounded-md bg-slate-100 motion-reduce:animate-none" />
    </div>
  )
}
