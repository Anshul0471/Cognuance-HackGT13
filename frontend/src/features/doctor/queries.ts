import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from '@tanstack/react-query'
import { useEffect } from 'react'
import { useAuth } from '../../auth/context'
import { ApiError } from '../../lib/api'
import {
  doctorApi,
  type AlertFilters,
  type InsightsRange,
  type PatientFilters,
  type TimelineRange,
} from './api'
import { doctorKeys } from './queryKeys'
import type { Page } from './schemas'

export const PATIENT_PAGE_SIZE = 20
export const TIMELINE_PAGE_SIZE = 50
export const ALERT_PAGE_SIZE = 20
export const EVENT_PAGE_SIZE = 20
const POLL_MS = 10_000

/** 403/404 on a protected record: the record is unavailable or access was lost. */
export function isAccessLost(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404)
}

// Poll while mounted and visible (TanStack pauses intervals in hidden tabs); stop once access is lost.
const live = {
  refetchInterval: (query: { state: { error: unknown } }) => (isAccessLost(query.state.error) ? false : POLL_MS),
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
  refetchOnReconnect: true,
  staleTime: 5_000,
} as const

export function useDoctorUserId(): string {
  const { user } = useAuth()
  if (!user) throw new Error('Doctor pages require a signed-in user')
  return user.id
}

/** Merge loaded pages without duplicate IDs (list membership can change between pages). */
export function mergePages<T>(data: InfiniteData<Page<T>> | undefined, idOf: (item: T) => string): T[] {
  const seen = new Set<string>()
  const out: T[] = []
  for (const page of data?.pages ?? []) {
    for (const item of page.items) {
      const id = idOf(item)
      if (!seen.has(id)) {
        seen.add(id)
        out.push(item)
      }
    }
  }
  return out
}

const pageOptions = {
  initialPageParam: null as string | null,
  getNextPageParam: <T>(last: Page<T>) => last.next_cursor,
}

export function useDoctorSummary() {
  const userId = useDoctorUserId()
  return useQuery({ queryKey: doctorKeys.summary(userId), queryFn: ({ signal }) => doctorApi.summary(signal), ...live })
}

export function useModelStatus() {
  const userId = useDoctorUserId()
  return useQuery({
    queryKey: doctorKeys.modelStatus(userId),
    queryFn: ({ signal }) => doctorApi.modelStatus(signal),
    ...live,
    refetchInterval: 60_000,
  })
}

export function usePatients(filters: PatientFilters, limit = PATIENT_PAGE_SIZE) {
  const userId = useDoctorUserId()
  return useInfiniteQuery({
    queryKey: doctorKeys.patients(userId, { ...filters, limit }),
    queryFn: ({ pageParam, signal }) => doctorApi.patients(filters, limit, pageParam, signal),
    ...pageOptions,
    ...live,
  })
}

export function usePatient(patientId: string, enabled = true) {
  const userId = useDoctorUserId()
  return useQuery({
    queryKey: doctorKeys.patient(userId, patientId),
    queryFn: ({ signal }) => doctorApi.patient(patientId, signal),
    enabled: enabled && patientId !== '',
    ...live,
  })
}

export function useTimeline(patientId: string, range: TimelineRange, enabled: boolean) {
  const userId = useDoctorUserId()
  return useInfiniteQuery({
    queryKey: doctorKeys.timeline(userId, patientId, { ...range, limit: TIMELINE_PAGE_SIZE }),
    queryFn: ({ pageParam, signal }) => doctorApi.timeline(patientId, range, TIMELINE_PAGE_SIZE, pageParam, signal),
    enabled,
    ...pageOptions,
    ...live,
  })
}

export function useAssessment(patientId: string, assessmentId: string | null) {
  const userId = useDoctorUserId()
  return useQuery({
    queryKey: doctorKeys.assessment(userId, patientId, assessmentId ?? ''),
    queryFn: ({ signal }) => doctorApi.assessment(patientId, assessmentId!, signal),
    enabled: assessmentId !== null,
    ...live,
  })
}

/** Enabled only once a patient is selected and the range is valid (never a speculative fetch). */
export function useInsights(patientId: string | null, range: InsightsRange | null) {
  const userId = useDoctorUserId()
  const effective = range ?? { from: '', to: '', source: 'ALL' as const }
  return useQuery({
    queryKey: doctorKeys.insights(userId, patientId ?? '', effective),
    queryFn: ({ signal }) => doctorApi.insights(patientId!, effective, signal),
    enabled: patientId !== null && range !== null,
    ...live,
  })
}

export function useAlerts(filters: AlertFilters, limit = ALERT_PAGE_SIZE) {
  const userId = useDoctorUserId()
  return useInfiniteQuery({
    queryKey: doctorKeys.alerts(userId, { ...filters, limit }),
    queryFn: ({ pageParam, signal }) => doctorApi.alerts(filters, limit, pageParam, signal),
    ...pageOptions,
    ...live,
  })
}

export function useAlert(alertId: string) {
  const userId = useDoctorUserId()
  return useQuery({
    queryKey: doctorKeys.alert(userId, alertId),
    queryFn: ({ signal }) => doctorApi.alert(alertId, signal),
    ...live,
  })
}

export function useAlertEvents(alertId: string, enabled: boolean) {
  const userId = useDoctorUserId()
  return useInfiniteQuery({
    queryKey: doctorKeys.alertEvents(userId, alertId),
    queryFn: ({ pageParam, signal }) => doctorApi.alertEvents(alertId, EVENT_PAGE_SIZE, pageParam, signal),
    enabled,
    ...pageOptions,
    ...live,
  })
}

/** After a confirmed review action every doctor view may have changed (lists, counts, headers). */
export function invalidateDoctorData(queryClient: QueryClient, userId: string) {
  return queryClient.invalidateQueries({ queryKey: doctorKeys.all(userId) })
}

type Scope = { patientId?: string; alertId?: string }

/**
 * Hide and drop cached content tied to a record that became unavailable, then refresh
 * assignment-scoped lists and counts. The failing query itself stays in its error state (its
 * screen renders the neutral unavailable message instead of any earlier data).
 */
export function purgeInaccessible(queryClient: QueryClient, userId: string, scope: Scope) {
  const keys = [
    scope.patientId && doctorKeys.timelineAll(userId, scope.patientId),
    scope.patientId && doctorKeys.assessmentsOf(userId, scope.patientId),
    scope.patientId && doctorKeys.insightsOf(userId, scope.patientId),
    scope.alertId && doctorKeys.alertEvents(userId, scope.alertId),
  ].filter(Boolean) as (readonly unknown[])[]
  for (const queryKey of keys) queryClient.removeQueries({ queryKey })
  if (scope.patientId) {
    queryClient.removeQueries({
      queryKey: doctorKeys.alertsAll(userId),
      predicate: (q) => (q.queryKey[3] as AlertFilters | undefined)?.patientId === scope.patientId,
    })
  }
  void queryClient.invalidateQueries({ queryKey: doctorKeys.summary(userId) })
  void queryClient.invalidateQueries({ queryKey: doctorKeys.patientsAll(userId) })
  void queryClient.invalidateQueries({
    queryKey: doctorKeys.alertsAll(userId),
    predicate: (q) => (q.queryKey[3] as AlertFilters | undefined)?.patientId !== scope.patientId,
  })
}

/** Run the purge once when a scoped record becomes unavailable. */
export function useAccessLossPurge(lost: boolean, scope: Scope) {
  const queryClient = useQueryClient()
  const userId = useDoctorUserId()
  const { patientId, alertId } = scope
  useEffect(() => {
    if (lost) purgeInaccessible(queryClient, userId, { patientId, alertId })
  }, [lost, queryClient, userId, patientId, alertId])
}
