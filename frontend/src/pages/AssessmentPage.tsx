import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useReducer, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { ContextCheckinForm } from '../assessment/ContextCheckinForm'
import { buildSubmission, flowReducer, initialFlow } from '../assessment/flow'
import { Preparation, type PreparationChoices } from '../assessment/Preparation'
import { ReceiptView } from '../assessment/ReceiptView'
import { createRunRecorder, type RunRecorder } from '../assessment/recorder'
import { ReviewSubmit } from '../assessment/ReviewSubmit'
import { AttentionTask } from '../assessment/tasks/AttentionTask'
import { MemoryTask } from '../assessment/tasks/MemoryTask'
import { Practice } from '../assessment/tasks/Practice'
import { ReactionTask } from '../assessment/tasks/ReactionTask'
import type { SessionStart, StartSessionRequest } from '../assessment/types'
import { formatMs } from '../assessment/stimuli'
import { BigButton, Screen } from '../assessment/ui'
import { api, ApiError } from '../lib/api'
import { useDocumentTitle } from '../lib/useDocumentTitle'

const START_ERRORS: Record<string, string> = {
  ACTIVE_SESSION_EXISTS: 'You have a check-in that was started and not finished. Go back home to discard it first.',
  SLOT_COMPLETED: "This week's check-in is already done.",
  ATTEMPT_LIMIT_REACHED: "This week's check-in attempts have been used.",
  OUTSIDE_SCHEDULE_WINDOW: "Your weekly check-in window isn't open right now.",
}

const BREAK_LIMIT_MS = 2 * 60 * 1000

function BreakScreen({ next, onContinue, onStop }: { next: string; onContinue: () => void; onStop: () => void }) {
  const [started] = useState(() => performance.now())
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setElapsed(performance.now() - started), 1000)
    return () => clearInterval(timer)
  }, [started])
  const over = elapsed >= BREAK_LIMIT_MS
  return (
    <Screen title="Short break">
      <p>Next: {next}. Take a short break if you like (up to 2 minutes), then press Continue.</p>
      <p className="text-base text-slate-600" aria-live="polite">
        {over ? 'Please continue now.' : `Break time left: ${formatMs(BREAK_LIMIT_MS - elapsed)}`}
      </p>
      <div className="flex flex-wrap gap-3">
        <BigButton onClick={onContinue}>Continue</BigButton>
        <BigButton variant="danger" onClick={onStop}>
          Save what I've done and stop
        </BigButton>
      </div>
    </Screen>
  )
}

export function AssessmentPage() {
  useDocumentTitle('Check-in')
  const { setDraftActive } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const extra = params.get('extra') === '1'
  const status = useQuery({ queryKey: ['assessment-status'], queryFn: api.assessmentStatus })

  const [session, setSession] = useState<SessionStart | null>(null)
  const [choices, setChoices] = useState<PreparationChoices | null>(null)
  const [flow, dispatch] = useReducer(flowReducer, initialFlow)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [remaining, setRemaining] = useState<number | null>(null)
  const [recorder, setRecorder] = useState<RunRecorder | null>(null)
  const startAttempt = useRef<{ key: string; body: string } | null>(null)
  const inProgress = session !== null && flow.step !== 'receipt'

  // Protect the in-memory draft from token expiry; release it once saved or on leaving.
  useEffect(() => {
    setDraftActive(inProgress)
  }, [inProgress, setDraftActive])
  useEffect(() => () => setDraftActive(false), [setDraftActive])
  useEffect(() => () => recorder?.dispose(), [recorder])

  useEffect(() => {
    document.getElementById('screen-title')?.focus()
  }, [flow.step])

  useEffect(() => {
    if (flow.step === 'receipt') void queryClient.invalidateQueries({ queryKey: ['assessment-status'] })
  }, [flow.step, queryClient])

  // Browser warning only; unsaved answers are never sent on unload.
  useEffect(() => {
    if (!inProgress) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [inProgress])

  // Session time left, measured on the local monotonic clock (no client/server clock skew).
  useEffect(() => {
    if (!session || !recorder || !inProgress) return
    const budget = Date.parse(session.expires_at) - Date.parse(session.started_at)
    const tick = () => setRemaining(budget - recorder.offset())
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [session, recorder, inProgress])

  const start = async (choices: PreparationChoices) => {
    const request: Omit<StartSessionRequest, 'start_key'> = { ...choices, allow_unscheduled: extra }
    const body = JSON.stringify(request)
    // Retrying identical choices reuses the start key (idempotent); changed choices get a new one.
    if (!startAttempt.current || startAttempt.current.body !== body) {
      startAttempt.current = { key: crypto.randomUUID(), body }
    }
    setStarting(true)
    setStartError(null)
    try {
      const started = await api.startSession({ ...request, start_key: startAttempt.current.key })
      if (started.status !== 'STARTED' || started.protocol === null) {
        setStartError('That check-in has already ended. Please go back home and start again.')
        return
      }
      const live = started as SessionStart
      setRecorder(createRunRecorder(live.protocol.limits.max_telemetry_events, live.input_mode))
      setChoices(choices)
      setSession(live)
    } catch (error) {
      const code = error instanceof ApiError ? error.code : null
      setStartError(
        (code && START_ERRORS[code]) ??
          (error instanceof ApiError && error.isNetworkError
            ? 'Could not reach the server. Please try again.'
            : 'The check-in could not be started. Please try again.'),
      )
    } finally {
      setStarting(false)
    }
  }

  const stopWithoutSaving = useCallback(async () => {
    if (session) {
      try {
        await api.abandonSession(session.session_id)
      } catch {
        // The server expires it anyway; nothing was saved.
      }
    }
    setDraftActive(false)
    navigate('/patient', { replace: true })
  }, [session, navigate, setDraftActive])

  if (!session || !recorder) {
    if (status.isPending) return <p className="text-lg">Loading…</p>
    return (
      <Preparation
        firstCheckIn={status.data?.schedule.anchor_at == null}
        extra={extra}
        busy={starting}
        error={startError}
        onStart={start}
      />
    )
  }

  const rec = recorder
  const protocol = session.protocol
  let body: ReactNode
  switch (flow.step) {
    case 'practice':
      body = (
        <Practice
          protocol={protocol}
          mode={session.input_mode}
          recorder={rec}
          onDone={(record) => dispatch({ type: 'PRACTICE_DONE', record })}
          onCannotContinue={(record, choice) =>
            choice === 'save' ? dispatch({ type: 'SAVE_PARTIAL', practice: record }) : void stopWithoutSaving()
          }
        />
      )
      break
    case 'memory':
      body = <MemoryTask config={protocol.memory} recorder={rec} onFinish={(result) => dispatch({ type: 'MEMORY_DONE', result })} />
      break
    case 'break-attention':
    case 'break-reaction':
      body = (
        <BreakScreen
          next={flow.step === 'break-attention' ? 'the shapes activity' : 'the GO activity'}
          onContinue={() => dispatch({ type: 'CONTINUE' })}
          onStop={() => dispatch({ type: 'SAVE_PARTIAL' })}
        />
      )
      break
    case 'attention':
      body = (
        <AttentionTask
          trials={protocol.attention.trials}
          stimulusMs={protocol.attention.stimulus_ms}
          gapMs={protocol.attention.gap_ms}
          mode={session.input_mode}
          recorder={rec}
          maxEventsPerTrial={protocol.limits.max_events_per_trial}
          onFinish={(result) => dispatch({ type: 'ATTENTION_DONE', result })}
        />
      )
      break
    case 'reaction':
      body = (
        <ReactionTask
          trials={protocol.reaction.trials}
          responseWindowMs={protocol.reaction.response_window_ms}
          intertrialMs={protocol.reaction.intertrial_ms}
          mode={session.input_mode}
          recorder={rec}
          maxEventsPerTrial={protocol.limits.max_events_per_trial}
          onFinish={(result) => dispatch({ type: 'REACTION_DONE', result })}
        />
      )
      break
    case 'context':
      body = (
        <ContextCheckinForm
          firstCheckIn={status.data?.schedule.anchor_at == null}
          navigationDeclared={choices?.navigation_assistance ?? false}
          initial={flow.contextResult ?? undefined}
          onDone={(result) => dispatch({ type: 'CONTEXT_DONE', result })}
        />
      )
      break
    case 'review':
      body = (
        <ReviewSubmit
          state={flow}
          session={session}
          freeze={() => buildSubmission(flow, session, rec, crypto.randomUUID())}
          onSaved={(receipt) => dispatch({ type: 'SAVED', receipt })}
          onEditContext={() => dispatch({ type: 'EDIT_CONTEXT' })}
        />
      )
      break
    case 'receipt':
      body = <ReceiptView receipt={flow.receipt!} />
      break
  }

  return (
    <div className="space-y-6">
      {inProgress && remaining !== null && (
        <div
          className={
            remaining < 3 * 60 * 1000
              ? 'rounded-lg bg-amber-50 px-4 py-2 text-base font-medium text-amber-900'
              : 'text-base text-slate-600'
          }
        >
          {remaining > 0
            ? `Time left to finish and save this check-in: ${formatMs(remaining)}`
            : 'The time for this check-in has run out; it may not be possible to save it.'}
          {flow.step !== 'review' && (
            <button type="button" className="ml-3 min-h-11 underline" onClick={() => void stopWithoutSaving()}>
              Leave without saving
            </button>
          )}
        </div>
      )}
      {body}
    </div>
  )
}
