import {
  CircleCheck,
  CircleDashed,
  CircleDot,
  CircleSlash,
  Clock,
  CloudOff,
  Eye,
  Flag,
  GitCompareArrows,
  Hourglass,
  Minus,
  OctagonAlert,
  Repeat,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '../../../lib/utils'
import type { Availability, DeviationLevel, Quality, WorkflowStatus } from '../schemas'
import { AVAILABILITY_LABEL, DEVIATION_LABEL, QUALITY_LABEL, WORKFLOW_LABEL } from '../utils/displayLabels'

// Every badge pairs its colour with an icon and words; colour alone never carries meaning.
// No badge is a green "all clear": NORMAL and COMPLETE are deliberately neutral.

function Badge({ icon: Icon, label, className, prefix }: { icon: LucideIcon; label: string; className: string; prefix?: string }) {
  return (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold',
        className,
      )}
    >
      <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
      {prefix && <span className="sr-only">{prefix}: </span>}
      <span className="truncate">{label}</span>
    </span>
  )
}

const AVAILABILITY_STYLE: Record<Availability, [LucideIcon, string]> = {
  PENDING: [Clock, 'border-slate-300 bg-white text-slate-700'],
  BUILDING_BASELINE: [Hourglass, 'border-slate-300 bg-white text-slate-700'],
  INSUFFICIENT_DATA: [CircleSlash, 'border-slate-300 bg-white text-slate-700'],
  MODEL_UNAVAILABLE: [CloudOff, 'border-slate-300 bg-white text-slate-700'],
  ANALYSIS_ERROR: [TriangleAlert, 'border-rose-300 bg-rose-50 text-rose-800'],
  COMPLETE: [GitCompareArrows, 'border-indigo-200 bg-indigo-50 text-indigo-800'],
}

export function AnalysisStatusBadge({ availability }: { availability: Availability }) {
  const [icon, style] = AVAILABILITY_STYLE[availability]
  return <Badge icon={icon} label={AVAILABILITY_LABEL[availability]} className={style} prefix="Analysis" />
}

const DEVIATION_STYLE: Record<DeviationLevel, [LucideIcon, string]> = {
  NORMAL: [Minus, 'border-slate-300 bg-white text-slate-700'],
  REVIEW: [Flag, 'border-amber-300 bg-amber-50 text-amber-900'],
  PERSISTENT_DEVIATION: [Repeat, 'border-orange-300 bg-orange-50 text-orange-900'],
  HIGH_DEVIATION: [OctagonAlert, 'border-red-300 bg-red-50 text-red-800'],
}

export function DeviationBadge({ level }: { level: DeviationLevel }) {
  const [icon, style] = DEVIATION_STYLE[level]
  return <Badge icon={icon} label={DEVIATION_LABEL[level]} className={style} prefix="Deviation category" />
}

const WORKFLOW_STYLE: Record<WorkflowStatus, [LucideIcon, string]> = {
  OPEN: [CircleDot, 'border-amber-300 bg-white text-amber-900'],
  ACKNOWLEDGED: [Eye, 'border-indigo-200 bg-white text-indigo-800'],
  RESOLVED: [CircleCheck, 'border-slate-300 bg-slate-100 text-slate-700'],
}

export function AlertWorkflowBadge({ status }: { status: WorkflowStatus }) {
  const [icon, style] = WORKFLOW_STYLE[status]
  return <Badge icon={icon} label={WORKFLOW_LABEL[status]} className={style} prefix="Review status" />
}

const QUALITY_STYLE: Record<Quality, [LucideIcon, string]> = {
  VALID: [CircleCheck, 'border-slate-300 bg-white text-slate-700'],
  LOW: [TriangleAlert, 'border-amber-300 bg-amber-50 text-amber-900'],
  INCOMPLETE: [CircleDashed, 'border-slate-400 bg-slate-100 text-slate-800'],
}

export function QualityBadge({ quality }: { quality: Quality }) {
  const [icon, style] = QUALITY_STYLE[quality]
  return <Badge icon={icon} label={QUALITY_LABEL[quality]} className={style} prefix="Data quality" />
}

/** Analysis state as one or two badges: the deviation category only exists for COMPLETE analyses. */
export function AnalysisBadges({ availability, level }: { availability: Availability | null; level: DeviationLevel | null }) {
  if (availability === null) return <span className="text-sm text-slate-600">No assessments yet</span>
  return (
    <span className="flex flex-wrap gap-1.5">
      <AnalysisStatusBadge availability={availability} />
      {availability === 'COMPLETE' && level && <DeviationBadge level={level} />}
    </span>
  )
}
