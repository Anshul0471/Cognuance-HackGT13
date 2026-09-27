import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { AssessmentEvidence } from '../components/AssessmentEvidence'
import { ErrorState, LastRefreshed, Loading, StaleNotice } from '../components/QueryState'
import { UNAVAILABLE_TEXT } from '../utils/errorText'
import { isAccessLost, useAccessLossPurge, useAssessment, usePatient } from '../queries'
import { formatInZone } from '../utils/dateFormatting'

export function AssessmentDetailPage() {
  const { patientId = '', assessmentId = '' } = useParams()
  const patient = usePatient(patientId)
  const detail = useAssessment(patientId, assessmentId)
  const lostError = isAccessLost(patient.error) || isAccessLost(detail.error)
  useAccessLossPurge(lostError, { patientId })

  const back = (
    <Link
      to={`/doctor/patients/${patientId}?assessment=${assessmentId}`}
      className="inline-flex items-center gap-1 text-sm font-medium text-indigo-700"
    >
      <ArrowLeft aria-hidden="true" className="h-4 w-4" />
      Assessment history
    </Link>
  )

  if (lostError) {
    return (
      <div className="space-y-4">
        {back}
        <h1 className="text-2xl font-bold">Assessment detail</h1>
        <p role="alert" className="rounded-lg border border-slate-300 bg-white p-4">
          {UNAVAILABLE_TEXT}
        </p>
      </div>
    )
  }

  const timeZone = patient.data?.patient.timezone
  return (
    <div className="space-y-6">
      {back}
      {(patient.isPending || detail.isPending) && <Loading label="Loading assessment…" />}
      {patient.isError && !patient.data && <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />}
      {detail.isError && !detail.data && <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />}
      {detail.isError && detail.data && (
        <StaleNotice error={detail.error} updatedAt={detail.dataUpdatedAt} onRefresh={() => void detail.refetch()} />
      )}
      {patient.data && detail.data && timeZone && (
        <>
          <div>
            <h1 className="text-2xl font-bold break-words">
              {patient.data.patient.display_name}: check-in observed {formatInZone(detail.data.observed_at, timeZone)}
            </h1>
            <p className="mt-1 flex flex-wrap gap-x-3 text-sm text-slate-600">
              <span>Times in {timeZone}.</span>
              <LastRefreshed at={detail.dataUpdatedAt} />
            </p>
          </div>
          <AssessmentEvidence detail={detail.data} patientId={patientId} timeZone={timeZone} level={2} />
        </>
      )}
    </div>
  )
}
