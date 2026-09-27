import {
  ArrowRight,
  Bell,
  CircleDot,
  CloudOff,
  Eye,
  Hourglass,
  TriangleAlert,
  UserRound,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { InitialsAvatar } from '../../../components/InitialsAvatar'
import { AlertWorkflowBadge, AnalysisBadges, DeviationBadge } from '../components/Badges'
import { ErrorState, StaleNotice } from '../components/QueryState'
import { mergePages, useAlerts, useDoctorSummary, useModelStatus, usePatients } from '../queries'
import type { DoctorSummary } from '../schemas'
import { formatLocal } from '../utils/dateFormatting'
import { DOMAIN_LABEL, MODEL_KIND_LABEL, reasonText } from '../utils/displayLabels'

type CountKey = keyof Omit<DoctorSummary, 'generated_at'>

// Server-owned counts only; links open the real list with the matching filter. Processing counts
// have no management screen, so they stay plain cards (explained under "About these counts").
const COUNTS: { key: CountKey; label: string; icon: LucideIcon; to?: string }[] = [
  { key: 'assigned_patient_count', label: 'Assigned patients', icon: Users, to: '/doctor/patients' },
  {
    key: 'patients_with_open_alerts',
    label: 'Patients with unresolved alerts',
    icon: UserRound,
    to: '/doctor/patients?alerts=with',
  },
  { key: 'open_alert_count', label: 'Open alerts', icon: CircleDot, to: '/doctor/alerts?status=OPEN' },
  { key: 'acknowledged_alert_count', label: 'Acknowledged alerts', icon: Eye, to: '/doctor/alerts?status=ACKNOWLEDGED' },
  { key: 'pending_analysis_count', label: 'Analysis pending', icon: Hourglass },
  { key: 'analysis_error_count', label: 'Analysis errors', icon: TriangleAlert },
]

const RECENT_ALERTS = 5
const PATIENT_ROWS = 6

function ModelNotice() {
  const status = useModelStatus()
  if (!status.data || status.data.forecast_ready) return null
  const reason = status.data.reason_code
  return (
    <div role="note" className="surface-card flex gap-2 p-4 text-sm text-slate-800">
      <CloudOff aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
      <p>
        <strong>New forecasts are currently unavailable</strong>
        {status.data.model_kind && ` (${MODEL_KIND_LABEL[status.data.model_kind] ?? status.data.model_kind})`}.
        {reason && ` ${reasonText(reason)}`} New check-ins are still saved; existing assessments and their stored
        forecasts remain readable.
      </p>
    </div>
  )
}

function CountCard({ label, value, icon: Icon, to }: { label: string; value: number; icon: LucideIcon; to?: string }) {
  const body = (
    <>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
        <Icon aria-hidden="true" className="h-4.5 w-4.5" />
      </span>
      <span className="min-w-0">
        <span className="block text-2xl font-bold tabular-nums leading-tight text-slate-900">{value}</span>
        <span className="block text-sm leading-snug text-slate-600">{label}</span>
      </span>
      {to && <ArrowRight aria-hidden="true" className="ml-auto h-4 w-4 shrink-0 self-center text-slate-400" />}
    </>
  )
  const base = 'surface-card flex h-full items-start gap-3 p-4'
  return to ? (
    <Link
      to={to}
      className={`${base} transition-colors duration-150 hover:border-indigo-200 hover:bg-indigo-50/40 motion-reduce:transition-none`}
    >
      {body}
    </Link>
  ) : (
    <div className={base}>{body}</div>
  )
}

function CountsSkeleton() {
  return (
    <div role="status" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <span className="sr-only">Loading counts…</span>
      {COUNTS.map(({ key }) => (
        <div key={key} aria-hidden="true" className="skeleton h-[76px] rounded-xl" />
      ))}
    </div>
  )
}

function RowsSkeleton({ label, rows }: { label: string; rows: number }) {
  return (
    <div role="status" className="space-y-2 p-4">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} aria-hidden="true" className="skeleton h-12" />
      ))}
    </div>
  )
}

function RecentAlerts() {
  const alerts = useAlerts({ status: 'UNRESOLVED' }, RECENT_ALERTS)
  const recent = mergePages(alerts.data, (a) => a.alert_id).slice(0, RECENT_ALERTS)
  return (
    <section aria-labelledby="recent-heading" className="surface-card flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <h2 id="recent-heading" className="text-base font-semibold">
          Recent unresolved alerts
        </h2>
        <Link to="/doctor/alerts" className="inline-flex items-center gap-1 text-sm font-semibold text-indigo-700">
          Open the alert inbox
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Link>
      </div>
      <p className="px-4 pt-3 text-xs text-slate-500">Newest first in the server's order; not a priority ranking.</p>
      {alerts.isPending && <RowsSkeleton label="Loading alerts…" rows={3} />}
      {alerts.isError && !alerts.data && (
        <div className="p-4">
          <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
        </div>
      )}
      {alerts.isError && alerts.data && (
        <div className="px-4 pt-3">
          <StaleNotice error={alerts.error} updatedAt={alerts.dataUpdatedAt} onRefresh={() => void alerts.refetch()} />
        </div>
      )}
      {alerts.isSuccess && recent.length === 0 && <p className="p-4 text-slate-700">No unresolved alerts.</p>}
      {recent.length > 0 && (
        <ul className="divide-y divide-slate-200">
          {recent.map((alert) => (
            <li key={alert.alert_id} className="flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3">
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-medium break-words">{alert.patient_display_name}</p>
                <p className="text-xs text-slate-600">
                  Check-in {formatLocal(alert.observed_at)} ·{' '}
                  {alert.affected_domains.map((d) => DOMAIN_LABEL[d]).join(', ') || 'No single domain listed'}
                </p>
                <p className="line-clamp-2 text-sm text-slate-700">{alert.summary}</p>
                <div className="flex flex-wrap gap-1.5">
                  <DeviationBadge level={alert.deviation_level} />
                  <AlertWorkflowBadge status={alert.workflow_status} />
                </div>
              </div>
              <Link
                to={`/doctor/alerts/${alert.alert_id}`}
                className="btn-secondary min-h-10 px-3 text-sm whitespace-nowrap"
              >
                Open review<span className="sr-only"> for {alert.patient_display_name}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function AssignedPatients() {
  // First server page only (patient creation order); never used to derive the counts above.
  const patients = usePatients({}, PATIENT_ROWS)
  const rows = patients.data?.pages[0]?.items.slice(0, PATIENT_ROWS) ?? []
  return (
    <section aria-labelledby="patients-heading" className="surface-card flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <h2 id="patients-heading" className="text-base font-semibold">
          Assigned patients
        </h2>
        <Link to="/doctor/patients" className="inline-flex items-center gap-1 text-sm font-semibold text-indigo-700">
          View all patients
          <ArrowRight aria-hidden="true" className="h-4 w-4" />
        </Link>
      </div>
      <p className="px-4 pt-3 text-xs text-slate-500">In the server's list order (most recently added first).</p>
      {patients.isPending && <RowsSkeleton label="Loading patients…" rows={4} />}
      {patients.isError && !patients.data && (
        <div className="p-4">
          <ErrorState error={patients.error} onRetry={() => void patients.refetch()} />
        </div>
      )}
      {patients.isSuccess && rows.length === 0 && <p className="p-4 text-slate-700">No patients are assigned to you.</p>}
      {rows.length > 0 && (
        <ul className="divide-y divide-slate-200">
          {rows.map((patient) => (
            <li key={patient.patient_id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
              <InitialsAvatar name={patient.display_name} />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="font-medium break-words">{patient.display_name}</p>
                <p className="text-xs text-slate-600">
                  {patient.latest_assessment_at
                    ? `Latest assessment ${formatLocal(patient.latest_assessment_at)}`
                    : 'No assessments yet'}
                  {' · '}
                  <span className="tabular-nums">{patient.unresolved_alert_count}</span> unresolved alert
                  {patient.unresolved_alert_count === 1 ? '' : 's'}
                </p>
                <AnalysisBadges availability={patient.latest_analysis_availability} level={patient.latest_deviation_level} />
              </div>
              <Link
                to={`/doctor/patients/${patient.patient_id}`}
                className="btn-secondary min-h-10 px-3 text-sm whitespace-nowrap"
              >
                View patient<span className="sr-only"> {patient.display_name}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function DoctorOverviewPage() {
  const summary = useDoctorSummary()

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">Overview</h1>
          <p className="mt-1 text-slate-600">Your patients, recent assessments, and review activity.</p>
        </div>
        {summary.data && <span className="text-xs text-slate-500">Updated {formatLocal(summary.data.generated_at)}</span>}
      </div>

      <ModelNotice />

      <section aria-labelledby="counts-heading" className="space-y-3">
        <h2 id="counts-heading" className="sr-only">
          Counts
        </h2>
        {summary.isPending && <CountsSkeleton />}
        {summary.isError && !summary.data && <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />}
        {summary.isError && summary.data && (
          <StaleNotice error={summary.error} updatedAt={summary.dataUpdatedAt} onRefresh={() => void summary.refetch()} />
        )}
        {summary.data && (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {COUNTS.map(({ key, label, icon, to }) => (
              <li key={key}>
                <CountCard label={label} value={summary.data[key]} icon={icon} to={to} />
              </li>
            ))}
          </ul>
        )}
        <details className="text-sm text-slate-600">
          <summary className="inline-flex min-h-9 cursor-pointer items-center gap-1 font-medium text-slate-700">
            <Bell aria-hidden="true" className="h-4 w-4" />
            About these counts
          </summary>
          <div className="mt-2 max-w-3xl space-y-1 pl-5">
            <p>
              Workflow and processing counts for patients currently assigned to you. They are not medical-risk
              estimates, and the categories overlap, so they are not added together.
            </p>
            <p>
              Open alerts await acknowledgment or resolution; acknowledged alerts are still unresolved. Analysis
              pending counts saved check-ins whose comparison has not finished; analysis errors count comparisons
              that failed and can be retried. Zero is a normal value for both.
            </p>
          </div>
        </details>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <RecentAlerts />
        <AssignedPatients />
      </div>
    </div>
  )
}
