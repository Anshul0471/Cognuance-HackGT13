import { apiFetch, jsonInit, query } from '../../lib/api'
import * as s from './schemas'
import type { AlertEventRequest, WorkflowStatus } from './schemas'

// Doctor endpoints (guide 05 §11–§13). Every read validates its response shape and forwards the
// query's AbortSignal, so cancelled or superseded requests never populate a screen.

const enc = encodeURIComponent

export type PatientFilters = { q?: string; hasUnresolvedAlerts?: boolean }
export type TimelineRange = { from?: string; to?: string }
export type InsightsSource = 'ALL' | s.Source
/** `from` inclusive, `to` exclusive, both UTC ISO; the backend caps the window at 366 days. */
export type InsightsRange = { from: string; to: string; source: InsightsSource }
export type AlertStatusFilter = 'UNRESOLVED' | WorkflowStatus | 'ALL'
export type AlertFilters = { patientId?: string; status: AlertStatusFilter; deviationLevel?: s.DeviationLevel }

/** Unresolved omits both params; an explicit status never combines with include_resolved. */
export function alertStatusParams(status: AlertStatusFilter): { workflow_status?: WorkflowStatus; include_resolved?: true } {
  if (status === 'UNRESOLVED') return {}
  if (status === 'ALL') return { include_resolved: true }
  return { workflow_status: status }
}

export const doctorApi = {
  summary: (signal?: AbortSignal) => apiFetch('/doctor/summary', { signal, parse: s.doctorSummary.parse }),

  patients: (filters: PatientFilters, limit: number, cursor: string | null, signal?: AbortSignal) =>
    apiFetch(
      `/doctor/patients${query({
        limit,
        cursor: cursor ?? undefined,
        q: filters.q,
        has_unresolved_alerts: filters.hasUnresolvedAlerts,
      })}`,
      { signal, parse: s.patientPage.parse },
    ),

  patient: (patientId: string, signal?: AbortSignal) =>
    apiFetch(`/doctor/patients/${enc(patientId)}`, { signal, parse: s.doctorPatientDetail.parse }),

  timeline: (patientId: string, range: TimelineRange, limit: number, cursor: string | null, signal?: AbortSignal) =>
    apiFetch(
      `/doctor/patients/${enc(patientId)}/timeline${query({ limit, cursor: cursor ?? undefined, ...range })}`,
      { signal, parse: s.timelinePage.parse },
    ),

  assessment: (patientId: string, assessmentId: string, signal?: AbortSignal) =>
    apiFetch(`/doctor/patients/${enc(patientId)}/assessments/${enc(assessmentId)}`, {
      signal,
      parse: s.assessmentDetail.parse,
    }),

  /** One complete bounded snapshot for Visual Insights (refinement 01); never paginated. */
  insights: (patientId: string, range: InsightsRange, signal?: AbortSignal) =>
    apiFetch(
      `/doctor/patients/${enc(patientId)}/insights${query({
        from: range.from,
        to: range.to,
        source: range.source,
      })}`,
      { signal, parse: s.insightsResponse.parse },
    ),

  alerts: (filters: AlertFilters, limit: number, cursor: string | null, signal?: AbortSignal) =>
    apiFetch(
      `/doctor/alerts${query({
        limit,
        cursor: cursor ?? undefined,
        patient_id: filters.patientId,
        deviation_level: filters.deviationLevel,
        ...alertStatusParams(filters.status),
      })}`,
      { signal, parse: s.alertPage.parse },
    ),

  alert: (alertId: string, signal?: AbortSignal) =>
    apiFetch(`/doctor/alerts/${enc(alertId)}`, { signal, parse: s.alertDetail.parse }),

  alertEvents: (alertId: string, limit: number, cursor: string | null, signal?: AbortSignal) =>
    apiFetch(`/doctor/alerts/${enc(alertId)}/events${query({ limit, cursor: cursor ?? undefined })}`, {
      signal,
      parse: s.alertEventPage.parse,
    }),

  /** Never resend a changed action under an old request_key; refetch on 409 before a new attempt. */
  recordAlertEvent: (alertId: string, body: AlertEventRequest) =>
    apiFetch(`/doctor/alerts/${enc(alertId)}/events`, jsonInit('POST', body, { parse: s.alertEventResponse.parse })),

  modelStatus: (signal?: AbortSignal) => apiFetch('/model/status', { signal, parse: s.modelStatus.parse }),
}
