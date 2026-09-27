import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/context'
import { api, ApiError } from '../lib/api'
import type { FlowState } from './flow'
import type { AssessmentSubmission, Completion, ContextField, Receipt, SessionStart } from './types'
import { BigButton, Screen } from './ui'

type SubmitState =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'unsaved' } // transport failure: retry the identical body/key
  | { kind: 'reauth'; error: string | null }
  | { kind: 'expired' }
  | { kind: 'failed'; message: string }

const TASK_LABEL = { memory: 'Words', attention: 'Shapes', reaction: 'GO' } as const
const COMPLETION_LABEL: Record<Completion, string> = {
  COMPLETED: 'Finished',
  STOPPED: 'Stopped early',
  SKIPPED: 'Not done',
}
const FIELD_LABEL = { sleep_hours: 'Sleep', mood_score: 'Mood', medication_change: 'Medication change' } as const

export function ReviewSubmit({
  state,
  session,
  freeze,
  onSaved,
  onEditContext,
}: {
  state: FlowState
  session: SessionStart
  /** Builds the final payload with a new submission key (called only when no frozen body exists). */
  freeze: () => AssessmentSubmission
  onSaved: (receipt: Receipt) => void
  onEditContext: () => void
}) {
  const { reauthenticate } = useAuth()
  const [status, setStatus] = useState<SubmitState>({ kind: 'idle' })
  const [password, setPassword] = useState('')
  const frozen = useRef<AssessmentSubmission | null>(null)

  const send = async () => {
    // One frozen body per submission key; retries resend exactly the same bytes.
    frozen.current ??= freeze()
    setStatus({ kind: 'sending' })
    try {
      onSaved(await api.submitAssessment(session.session_id, frozen.current))
    } catch (error) {
      if (!(error instanceof ApiError) || error.isNetworkError) setStatus({ kind: 'unsaved' })
      else if (error.status === 401) setStatus({ kind: 'reauth', error: null })
      else if (error.code === 'SESSION_EXPIRED') setStatus({ kind: 'expired' })
      else if (error.status && error.status >= 500) setStatus({ kind: 'unsaved' })
      else
        setStatus({
          kind: 'failed',
          message: 'This check-in could not be saved because something in it was not accepted.',
        })
    }
  }

  const tasks = (['memory', 'attention', 'reaction'] as const).map((name) => ({
    name,
    completion: (state[name]?.completion ?? 'SKIPPED') as Completion,
  }))
  const missing = Object.keys(state.contextResult?.context.missing_fields ?? {}) as ContextField[]
  const locked = status.kind === 'sending' || status.kind === 'unsaved' || status.kind === 'reauth'

  if (status.kind === 'expired') {
    return (
      <Screen title="Not saved">
        <p>
          This check-in expired before it could be saved, so your answers were not saved. You can start a new
          check-in from the home page.
        </p>
        <Link to="/patient" className="text-lg font-semibold text-indigo-800 underline">
          Back to home
        </Link>
      </Screen>
    )
  }

  return (
    <Screen title="Review and save">
      <ul className="space-y-2">
        {tasks.map((t) => (
          <li key={t.name} className="flex justify-between rounded-lg border border-slate-200 bg-white px-4 py-3">
            <span className="font-medium">{TASK_LABEL[t.name]}</span>
            <span>{COMPLETION_LABEL[t.completion]}</span>
          </li>
        ))}
      </ul>
      {missing.length > 0 && (
        <p>Questions skipped or not known: {missing.map((field) => FIELD_LABEL[field]).join(', ')}.</p>
      )}

      {status.kind === 'unsaved' && (
        <p role="alert" className="rounded-lg bg-amber-50 p-4 font-medium text-amber-900">
          Not saved yet — the connection failed. Your answers are still here. Please try again.
        </p>
      )}
      {status.kind === 'failed' && (
        <p role="alert" className="rounded-lg bg-rose-50 p-4 text-rose-900">
          {status.message}
        </p>
      )}

      {status.kind === 'reauth' ? (
        <form
          className="space-y-3 rounded-lg border-2 border-slate-300 bg-white p-4"
          onSubmit={async (event) => {
            event.preventDefault()
            try {
              await reauthenticate(password)
              setPassword('')
              await send()
            } catch {
              setStatus({ kind: 'reauth', error: 'That password did not work. Please try again.' })
            }
          }}
        >
          <p className="font-medium">
            Not saved yet — please sign in again to save. Your answers are still here; you won't need to redo the
            activities.
          </p>
          <label className="block">
            <span className="text-base font-medium">Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 w-full rounded-md border-2 border-slate-300 px-3 py-2.5 text-lg"
            />
          </label>
          {status.error && (
            <p role="alert" className="text-rose-800">
              {status.error}
            </p>
          )}
          <BigButton type="submit">Sign in and save</BigButton>
        </form>
      ) : (
        <div className="flex flex-wrap gap-3">
          <BigButton onClick={send} disabled={status.kind === 'sending'}>
            {status.kind === 'sending' ? 'Saving…' : status.kind === 'unsaved' ? 'Try again' : 'Save check-in'}
          </BigButton>
          {!locked && (
            <BigButton
              variant="secondary"
              onClick={() => {
                frozen.current = null // edited answers get a new submission key
                onEditContext()
              }}
            >
              Change my answers to the questions
            </BigButton>
          )}
        </div>
      )}
    </Screen>
  )
}
