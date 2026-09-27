import type { AlertFilters, InsightsRange, PatientFilters, TimelineRange } from './api'

// Private query keys: the signed-in user's ID and every effective parameter are part of each key.

export const doctorKeys = {
  all: (userId: string) => ['doctor', userId] as const,
  summary: (userId: string) => ['doctor', userId, 'summary'] as const,
  modelStatus: (userId: string) => ['doctor', userId, 'model-status'] as const,
  patients: (userId: string, filters: PatientFilters & { limit: number }) =>
    ['doctor', userId, 'patients', filters] as const,
  patientsAll: (userId: string) => ['doctor', userId, 'patients'] as const,
  patient: (userId: string, patientId: string) => ['doctor', userId, 'patient', patientId] as const,
  timeline: (userId: string, patientId: string, range: TimelineRange & { limit: number }) =>
    ['doctor', userId, 'timeline', patientId, range] as const,
  timelineAll: (userId: string, patientId: string) => ['doctor', userId, 'timeline', patientId] as const,
  assessment: (userId: string, patientId: string, assessmentId: string) =>
    ['doctor', userId, 'assessment', patientId, assessmentId] as const,
  assessmentsOf: (userId: string, patientId: string) => ['doctor', userId, 'assessment', patientId] as const,
  insights: (userId: string, patientId: string, range: InsightsRange) =>
    ['doctor', userId, 'insights', patientId, range] as const,
  insightsOf: (userId: string, patientId: string) => ['doctor', userId, 'insights', patientId] as const,
  alerts: (userId: string, filters: AlertFilters & { limit: number }) => ['doctor', userId, 'alerts', filters] as const,
  alertsAll: (userId: string) => ['doctor', userId, 'alerts'] as const,
  alert: (userId: string, alertId: string) => ['doctor', userId, 'alert', alertId] as const,
  alertEvents: (userId: string, alertId: string) => ['doctor', userId, 'alert-events', alertId] as const,
}
