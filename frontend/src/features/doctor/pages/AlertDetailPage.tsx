import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertEventTimeline } from '../components/AlertEventTimeline'
import { AlertReviewActions } from '../components/AlertReviewActions'
import { AlertScoreContext } from '../components/AlertScoreContext'
import { ClinicalReviewPrompt } from '../components/ClinicalReviewPrompt'
import { AssessmentEvidence } from '../components/AssessmentEvidence'
import { AlertWorkflowBadge, DeviationBadge } from '../components/Badges'
import { ErrorState, LastRefreshed, Loading, StaleNotice } from '../components/QueryState'
import { UNAVAILABLE_TEXT } from '../utils/errorText'
import {
  invalidateDoctorData,
  isAccessLost,
  mergePages,
  useAccessLossPurge,
  useAlert,
  useAlertEvents,
  useDoctorUserId,
  usePatient,
} from '../queries'
import { doctorKeys } from '../queryKeys'
import type { AlertDetail, AlertEventResponse } from '../schemas'
import { formatInZone, formatLocal } from '../utils/dateFormatting'
import { DOMAIN_LABEL } from '../utils/displayLabels'

export function AlertDetailPage() {
  const { alertId = '' } = useParams()
  const userId = useDoctorUserId()
  const queryClient = useQueryClient()
  const alert = useAlert(alertId)
  const patientId = alert.data?.patient_id ?? ''
  const patient = usePatient(patientId, alert.isSuccess)
  const events = useAlertEvents(alertId, alert.isSuccess)
  const [actionLostAccess, setActionLostAccess] = useState(false)

  const lost = actionLostAccess || [alert.error, events.error, patient.error].some(isAccessLost)
  useAccessLossPurge(lost, { patientId: patientId || undefined, alertId })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: doctorKeys.alert(userId, alertId) })
    void queryClient.invalidateQueries({ queryKey: doctorKeys.alertEvents(userId, alertId) })
    void invalidateDoctorData(queryClient, userId)
  }

  const confirmed = (response: AlertEventResponse) => {
    // Use the server's *current* alert summary; never roll back to a replayed event's historical status.
    queryClient.setQueryData<AlertDetail>(doctorKeys.alert(userId, alertId), (old) =>
      old && response.alert.lock_version >= old.lock_version
        ? { ...old, workflow_status: response.alert.workflow_status, lock_version: response.alert.lock_version }
        : old,
    )
    void invalidateDoctorData(queryClient, userId)
  }

  const back = (
    <Link to="/doctor/alerts" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-700">
      <ArrowLeft aria-hidden="true" className="h-4 w-4" />
      Alert inbox
    </Link>
  )

  if (lost) {
    return (
      <div className="space-y-4">
        {back}
        <h1 className="text-2xl font-bold">Alert review</h1>
        <p role="alert" className="rounded-lg border border-slate-300 bg-white p-4">
          {UNAVAILABLE_TEXT}
        </p>
      </div>
    )
  }

  const data = alert.data
  const timeZone = patient.data?.patient.timezone
  const eventItems = mergePages(events.data, (e) => e.event_id)

  return (
    <div className="space-y-6">
      {back}
      {alert.isPending && <Loading label="Loading alert…" />}
      {alert.isError && !data && <ErrorState error={alert.error} onRetry={() => void alert.refetch()} />}
      {alert.isError && data && (
        <StaleNotice error={alert.error} updatedAt={alert.dataUpdatedAt} onRefresh={() => void alert.refetch()} />
      )}
      {data && (
        <>
          <section aria-labelledby="alert-heading" className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h1 id="alert-heading" className="text-2xl font-bold break-words">
                Alert review: {data.patient_display_name}
              </h1>
              {patient.data && !patient.data.patient.account_active && (
                <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-medium text-slate-800">
                  Patient account inactive
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              <DeviationBadge level={data.deviation_level} />
              <AlertWorkflowBadge status={data.workflow_status} />
            </div>
            <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-slate-600">Check-in observed</dt>
                <dd>{timeZone ? `${formatInZone(data.observed_at, timeZone)} (${timeZone})` : formatLocal(data.observed_at)}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Alert created</dt>
                <dd>{formatLocal(data.created_at)} (your time)</dd>
              </div>
              <div>
                <dt className="text-slate-600">Affected domains</dt>
                <dd>{data.affected_domains.map((d) => DOMAIN_LABEL[d]).join(', ') || 'None listed'}</dd>
              </div>
              <div>
                <dt className="text-slate-600">Patient</dt>
                <dd>
                  <Link to={`/doctor/patients/${data.patient_id}?assessment=${data.assessment_id}`} className="underline">
                    Open assessment history
                  </Link>
                </dd>
              </div>
            </dl>
            <p className="text-sm text-slate-800">{data.summary}</p>
            <p className="text-xs text-slate-500">
              The deviation category is the original classification and does not change when the alert is reviewed.{' '}
              <LastRefreshed at={alert.dataUpdatedAt} />
            </p>
          </section>

          <ClinicalReviewPrompt status={data.workflow_status} />

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="min-w-0 space-y-3">
              {timeZone && (
                <AlertScoreContext patientId={data.patient_id} assessment={data.assessment} timeZone={timeZone} />
              )}
              <h2 className="text-lg font-semibold">Assessment evidence</h2>
              {timeZone ? (
                <AssessmentEvidence detail={data.assessment} patientId={data.patient_id} timeZone={timeZone} level={3} />
              ) : patient.isError ? (
                <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />
              ) : (
                <Loading label="Loading patient details…" />
              )}
            </div>
            <div className="space-y-6 lg:sticky lg:top-4 lg:self-start">
              <AlertReviewActions
                alert={{ alert_id: data.alert_id, workflow_status: data.workflow_status, lock_version: data.lock_version }}
                onConfirmed={confirmed}
                onRefresh={refresh}
                onAccessLost={() => setActionLostAccess(true)}
              />
              <section aria-labelledby="history-heading" className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
                <h2 id="history-heading" className="text-lg font-semibold">
                  Review history
                </h2>
                {events.isPending && <Loading label="Loading review history…" />}
                {events.isError && !events.data && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
                {events.isError && events.data && (
                  <StaleNotice error={events.error} updatedAt={events.dataUpdatedAt} onRefresh={() => void events.refetch()} />
                )}
                {events.data && (
                  <AlertEventTimeline
                    events={eventItems}
                    hasMore={events.hasNextPage}
                    loadingMore={events.isFetchingNextPage}
                    onLoadMore={() => void events.fetchNextPage()}
                  />
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
