import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, ClipboardList, History } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { api } from '../lib/api'
import { useDocumentTitle } from '../lib/useDocumentTitle'

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })

// Schedule reason codes from GET /patient/assessment-status (backend_contract_v1).
const SCHEDULE_TEXT: Record<string, string> = {
  FIRST_CHECKIN: 'Your first check-in sets your weekly schedule.',
  IN_WINDOW: 'Your weekly check-in is available now.',
  SLOT_COMPLETED: "This week's check-in is done.",
  ATTEMPT_LIMIT_REACHED: "This week's check-in attempts have been used.",
  OUTSIDE_SCHEDULE_WINDOW: "Your next weekly check-in isn't open yet.",
}

const QUALITY_TEXT = {
  VALID: 'Saved',
  LOW: 'Saved — some parts could not be compared reliably',
  INCOMPLETE: 'Saved as unfinished',
} as const

export function PatientHomePage() {
  useDocumentTitle('Home')
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['assessment-status'], queryFn: api.assessmentStatus })
  const discard = useMutation({
    mutationFn: (sessionId: string) => api.abandonSession(sessionId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['assessment-status'] }),
  })

  const s = status.data
  const linkClass =
    'inline-flex min-h-12 items-center justify-center rounded-lg px-5 py-3 text-lg font-semibold focus:outline-none focus-visible:ring-4 focus-visible:ring-indigo-300'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Hello, {user?.display_name}</h1>
      </div>

      <section className="surface-card space-y-4 p-6" aria-labelledby="checkin-heading">
        <h2 id="checkin-heading" className="inline-flex items-center gap-2 text-xl font-semibold">
          <ClipboardList aria-hidden="true" className="h-6 w-6 text-indigo-700" />
          Weekly check-in
        </h2>

        {status.isPending && (
          <div role="status" className="space-y-3">
            <span className="sr-only">Loading your check-in status…</span>
            <div aria-hidden="true" className="skeleton h-6 w-3/4" />
            <div aria-hidden="true" className="skeleton h-12 w-44" />
          </div>
        )}
        {status.isError && (
          <p role="alert" className="text-lg text-rose-800">
            Your check-in status could not be loaded.
          </p>
        )}

        {s?.current_session && (
          <div className="space-y-3 rounded-lg bg-amber-50 p-4">
            <p className="text-lg">
              You started a check-in that wasn't finished. Unfinished answers were not saved and can't be continued.
            </p>
            <button
              type="button"
              disabled={discard.isPending}
              onClick={() => discard.mutate(s.current_session!.session_id)}
              className={`${linkClass} border-2 border-slate-400 bg-white text-slate-900 hover:bg-slate-100`}
            >
              {discard.isPending ? 'Discarding…' : 'Discard it so I can start again'}
            </button>
          </div>
        )}

        {s && !s.current_session && (
          <>
            {s.schedule.scheduled_start_allowed ? (
              <>
                <p className="text-lg">
                  {SCHEDULE_TEXT[s.schedule.reason_codes[0]] ?? 'Your weekly check-in is available now.'}
                </p>
                <p className="text-base text-slate-600">About 5 minutes. Please use a quiet place.</p>
                <Link to="/patient/check-in" className={`${linkClass} bg-indigo-700 text-white hover:bg-indigo-800`}>
                  Start check-in
                </Link>
              </>
            ) : (
              <>
                <p className="text-lg">
                  {s.schedule.reason_codes.map((code) => SCHEDULE_TEXT[code]).filter(Boolean).join(' ')}
                </p>
                {s.schedule.window_opens_at && (
                  <p className="inline-flex items-center gap-2 text-lg">
                    <CalendarClock aria-hidden="true" className="h-5 w-5" />
                    Next check-in opens {when(s.schedule.window_opens_at)}.
                  </p>
                )}
                {s.schedule.anchor_at !== null && (
                  <div className="space-y-2 border-t border-slate-200 pt-4">
                    <p className="text-base text-slate-600">
                      You can do an extra check-in now. It will be saved, but not used for weekly comparison.
                    </p>
                    <Link
                      to="/patient/check-in?extra=1"
                      className={`${linkClass} border-2 border-slate-400 bg-white text-slate-900 hover:bg-slate-100`}
                    >
                      Do an extra check-in
                    </Link>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </section>

      {s?.last_receipt && (
        <section className="surface-card p-6" aria-labelledby="last-heading">
          <h2 id="last-heading" className="inline-flex items-center gap-2 text-xl font-semibold">
            <History aria-hidden="true" className="h-6 w-6 text-slate-600" />
            Last check-in
          </h2>
          <p className="mt-2 text-lg">
            {when(s.last_receipt.received_at)}: {QUALITY_TEXT[s.last_receipt.quality.status]}.
          </p>
        </section>
      )}
    </div>
  )
}
