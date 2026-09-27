import { useMutation } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useBlocker } from 'react-router-dom'
import { ApiError, UNEXPECTED_RESPONSE } from '../../../lib/api'
import { doctorApi } from '../api'
import type { AlertEventRequest, AlertEventResponse, AlertRef, ReviewAction } from '../schemas'
import { ACTION_LABEL, WORKFLOW_LABEL } from '../utils/displayLabels'
import { AlertWorkflowBadge } from './Badges'
import { Dialog } from './Dialog'
import { NOTE_MAX, noteLength } from '../utils/notes'
import { RequestId } from './QueryState'

type Draft = Record<ReviewAction, string>
const EMPTY: Draft = { ACKNOWLEDGED: '', NOTE_ADDED: '', RESOLVED: '' }

type Outcome =
  | { kind: 'ambiguous'; message: string; requestId: string | null }
  | { kind: 'refreshed'; message: string; requestId: string | null }
  | { kind: 'invalid'; action: ReviewAction; message: string; requestId: string | null }

const DONE_TEXT: Record<ReviewAction, string> = {
  ACKNOWLEDGED: 'Acknowledgment recorded.',
  NOTE_ADDED: 'Note added.',
  RESOLVED: 'Alert resolved.',
}

function NoteField({
  id,
  label,
  required,
  value,
  disabled,
  error,
  onChange,
}: {
  id: string
  label: string
  required: boolean
  value: string
  disabled: boolean
  error: string | null
  onChange: (value: string) => void
}) {
  const length = noteLength(value)
  const over = length > NOTE_MAX
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label} {required ? '(required)' : '(optional)'}
      </label>
      <textarea
        id={id}
        value={value}
        rows={3}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error || over ? 'true' : 'false'}
        aria-describedby={`${id}-count${error ? ` ${id}-error` : ''}`}
        className="mt-1 block w-full rounded-md border border-slate-300 bg-white p-2 text-sm disabled:bg-slate-100"
      />
      <p id={`${id}-count`} className={over ? 'mt-1 text-xs font-semibold text-rose-700' : 'mt-1 text-xs text-slate-500'}>
        {length} / {NOTE_MAX} characters{over ? ' — too long' : ''}. Plain text; record your review action, not a
        diagnosis.
      </p>
      {error && (
        <p id={`${id}-error`} className="mt-1 text-sm text-rose-700">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Acknowledge / add note / resolve with optimistic-concurrency and idempotency rules (guide 06 §11):
 * one request key and frozen body per logical action; an unconfirmed result is retried only with
 * exactly that body; 409s refresh and require an explicit new submission.
 */
export function AlertReviewActions({
  alert,
  onConfirmed,
  onRefresh,
  onAccessLost,
}: {
  alert: AlertRef
  onConfirmed: (response: AlertEventResponse) => void
  onRefresh: () => void
  onAccessLost: () => void
}) {
  const ids = { ack: useId(), note: useId(), resolve: useId() }
  const [draft, setDraft] = useState<Draft>(EMPTY)
  const [fieldError, setFieldError] = useState<Partial<Record<ReviewAction, string>>>({})
  const [frozen, setFrozen] = useState<AlertEventRequest | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [resolveOpen, setResolveOpen] = useState(false)
  const [minVersion, setMinVersion] = useState(0)
  const resolveField = useRef<HTMLTextAreaElement>(null)

  const mutation = useMutation({
    mutationFn: (body: AlertEventRequest) => doctorApi.recordAlertEvent(alert.alert_id, body),
    onSuccess: (response, body) => {
      setFrozen(null)
      setOutcome(null)
      setFieldError({})
      setDraft((d) => ({ ...d, [body.action]: '' }))
      setResolveOpen(false)
      setAnnouncement(
        `${DONE_TEXT[body.action]}${response.replayed ? ' (this confirms the earlier request)' : ''} Current status: ${
          WORKFLOW_LABEL[response.alert.workflow_status]
        }.`,
      )
      onConfirmed(response)
    },
    onError: (error, body) => {
      const requestId = error instanceof ApiError ? error.requestId : null
      if (!(error instanceof ApiError) || error.isNetworkError || error.code === UNEXPECTED_RESPONSE) {
        setOutcome({
          kind: 'ambiguous',
          message:
            'The result could not be confirmed. The action may or may not have been recorded. “Retry” sends exactly the same request, so it cannot be recorded twice.',
          requestId,
        })
        return
      }
      if (error.status === 401) return
      if (error.status === 403 || error.status === 404) {
        setFrozen(null)
        onAccessLost()
        return
      }
      if (error.status === 429 || (error.status ?? 0) >= 500) {
        const wait = error.status === 429 && error.retryAfterSeconds ? ` Wait ${error.retryAfterSeconds} s, then retry.` : ''
        setOutcome({
          kind: 'ambiguous',
          message: `The server could not complete the action right now.${wait} “Retry” sends exactly the same request.`,
          requestId,
        })
        return
      }
      // Rejected without being recorded: the key is not reused; the draft stays for an explicit resubmission.
      setFrozen(null)
      if (error.status === 422) {
        setFieldError({
          [body.action]:
            error.code === 'NOTE_REQUIRED'
              ? 'A note is required for this action.'
              : 'The note was not accepted. Check its length and try again.',
        })
        setOutcome(null)
        return
      }
      if (error.code === 'STALE_ALERT_VERSION') {
        const current = error.details as { workflow_status?: string; lock_version?: number }
        setMinVersion(typeof current.lock_version === 'number' ? current.lock_version : alert.lock_version + 1)
        setOutcome({
          kind: 'refreshed',
          message: `Another update was made to this alert${
            current.workflow_status ? ` (now ${WORKFLOW_LABEL[current.workflow_status as AlertRef['workflow_status']] ?? current.workflow_status})` : ''
          }. The alert and its history have been refreshed. Your note is kept; review the latest history, then submit again.`,
          requestId,
        })
      } else if (error.code === 'INVALID_ALERT_TRANSITION') {
        setOutcome({
          kind: 'invalid',
          action: body.action,
          message: `“${ACTION_LABEL[body.action]}” is no longer available for this alert’s current status. The available actions have been updated.`,
          requestId,
        })
      } else if (error.code === 'IDEMPOTENCY_CONFLICT') {
        setOutcome({
          kind: 'refreshed',
          message:
            'This request could not be reused, so it was not recorded. The latest evidence has been refreshed; review it before starting a new action.',
          requestId,
        })
      } else {
        setOutcome({ kind: 'refreshed', message: error.detail ?? 'The action was not recorded.', requestId })
      }
      onRefresh()
    },
  })

  const busy = mutation.isPending
  const waitingForRefresh = alert.lock_version < minVersion
  const locked = busy || frozen !== null || waitingForRefresh
  const status = alert.workflow_status
  const dirty = frozen !== null || Object.values(draft).some((text) => text.trim() !== '')

  const submit = (action: ReviewAction) => (event?: FormEvent) => {
    event?.preventDefault()
    if (locked) return
    const text = draft[action].trim()
    if (action !== 'ACKNOWLEDGED' && !text) {
      setFieldError({ [action]: 'A note is required for this action.' })
      return
    }
    if (noteLength(text) > NOTE_MAX) {
      setFieldError({ [action]: `Shorten the note to ${NOTE_MAX} characters or fewer.` })
      return
    }
    const body: AlertEventRequest = {
      request_key: crypto.randomUUID(),
      expected_lock_version: alert.lock_version,
      action,
      note: text || null,
    }
    setFieldError({})
    setOutcome(null)
    setAnnouncement('')
    setFrozen(body)
    mutation.mutate(body)
  }

  const retry = () => {
    if (frozen && !busy) {
      setOutcome(null)
      mutation.mutate(frozen)
    }
  }

  const discardUnconfirmed = () => {
    setFrozen(null)
    setOutcome({
      kind: 'refreshed',
      message: 'The unconfirmed request was set aside. If it had been recorded, it now appears in the history below.',
      requestId: null,
    })
    onRefresh()
  }

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname && !nextLocation.pathname.startsWith('/login'),
  )

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const edit = (action: ReviewAction) => (value: string) => {
    setDraft((d) => ({ ...d, [action]: value }))
    if (fieldError[action]) setFieldError((e) => ({ ...e, [action]: undefined }))
  }

  const button =
    'inline-flex min-h-11 items-center justify-center rounded-md px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50'

  const outcomePanel = outcome && (
    <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      <p>{outcome.message}</p>
      <RequestId id={outcome.requestId} />
      {outcome.kind === 'ambiguous' && frozen && (
        <div className="mt-2 space-y-2">
          <p className="text-xs">
            Pending request: {ACTION_LABEL[frozen.action]}
            {frozen.note ? ` with note “${frozen.note.length > 80 ? `${frozen.note.slice(0, 80)}…` : frozen.note}”` : ''}{' '}
            (expected version {frozen.expected_lock_version}).
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={retry} disabled={busy} className={`${button} bg-indigo-700 text-white`}>
              {busy ? 'Retrying…' : 'Retry the same request'}
            </button>
            <button
              type="button"
              onClick={discardUnconfirmed}
              disabled={busy}
              className={`${button} border border-slate-300 bg-white`}
            >
              Set it aside and refresh
            </button>
          </div>
        </div>
      )}
    </div>
  )

  return (
    <section aria-labelledby="actions-heading" className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div className="space-y-1">
        <h2 id="actions-heading" className="text-lg font-semibold">
          Review actions
        </h2>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          Current status <AlertWorkflowBadge status={status} /> · version {alert.lock_version}
        </p>
        <p className="text-xs text-slate-500">
          Viewing this page does not change the alert. Actions change only its review status; the assessment, scores
          and deviation category stay as recorded.
        </p>
      </div>

      <p role="status" aria-live="polite" className="text-sm font-medium text-slate-800 empty:hidden">
        {announcement}
      </p>

      {!resolveOpen && outcomePanel}
      {waitingForRefresh && !busy && <p className="text-sm text-slate-600">Refreshing the alert before you can submit again…</p>}

      {status === 'OPEN' && (
        <form onSubmit={submit('ACKNOWLEDGED')} className="space-y-2 border-t border-slate-100 pt-4">
          <NoteField
            id={ids.ack}
            label="Acknowledgment note"
            required={false}
            value={draft.ACKNOWLEDGED}
            disabled={locked}
            error={fieldError.ACKNOWLEDGED ?? null}
            onChange={edit('ACKNOWLEDGED')}
          />
          <button type="submit" disabled={locked} className={`${button} bg-indigo-700 text-white hover:bg-indigo-800`}>
            {busy && frozen?.action === 'ACKNOWLEDGED' ? 'Saving…' : 'Acknowledge'}
          </button>
        </form>
      )}

      <form onSubmit={submit('NOTE_ADDED')} className="space-y-2 border-t border-slate-100 pt-4">
        <NoteField
          id={ids.note}
          label="Review note"
          required
          value={draft.NOTE_ADDED}
          disabled={locked}
          error={fieldError.NOTE_ADDED ?? null}
          onChange={edit('NOTE_ADDED')}
        />
        <button type="submit" disabled={locked} className={`${button} border border-slate-400 bg-white hover:bg-slate-50`}>
          {busy && frozen?.action === 'NOTE_ADDED' ? 'Saving…' : 'Add note'}
        </button>
      </form>

      {status !== 'RESOLVED' && (
        <div className="border-t border-slate-100 pt-4">
          <button
            type="button"
            disabled={locked}
            onClick={() => setResolveOpen(true)}
            className={`${button} border border-slate-500 bg-white hover:bg-slate-50`}
          >
            Resolve…
          </button>
          {status === 'ACKNOWLEDGED' && <p className="mt-1 text-xs text-slate-500">Resolving requires a note.</p>}
        </div>
      )}

      <Dialog open={resolveOpen} title="Resolve this alert" onClose={() => setResolveOpen(false)} initialFocusRef={resolveField}>
        <form onSubmit={submit('RESOLVED')} className="space-y-3">
          <p className="text-sm text-slate-700">
            Resolving records that you finished reviewing. It keeps the original deviation category and evidence;
            there is no reopen action.
          </p>
          <div>
            <label htmlFor={ids.resolve} className="block text-sm font-medium">
              Resolution note (required)
            </label>
            <textarea
              ref={resolveField}
              id={ids.resolve}
              rows={4}
              value={draft.RESOLVED}
              disabled={locked}
              onChange={(event) => edit('RESOLVED')(event.target.value)}
              aria-invalid={fieldError.RESOLVED || noteLength(draft.RESOLVED) > NOTE_MAX ? 'true' : 'false'}
              aria-describedby={`${ids.resolve}-count${fieldError.RESOLVED ? ` ${ids.resolve}-error` : ''}`}
              className="mt-1 block w-full rounded-md border border-slate-300 p-2 text-sm disabled:bg-slate-100"
            />
            <p id={`${ids.resolve}-count`} className="mt-1 text-xs text-slate-500">
              {noteLength(draft.RESOLVED)} / {NOTE_MAX} characters. Plain text.
            </p>
            {fieldError.RESOLVED && (
              <p id={`${ids.resolve}-error`} className="mt-1 text-sm text-rose-700">
                {fieldError.RESOLVED}
              </p>
            )}
          </div>
          {outcomePanel}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => setResolveOpen(false)} className={`${button} border border-slate-300 bg-white`}>
              {busy ? 'Close (the request continues)' : 'Cancel'}
            </button>
            <button type="submit" disabled={locked} className={`${button} bg-slate-800 text-white hover:bg-slate-900`}>
              {busy && frozen?.action === 'RESOLVED' ? 'Resolving…' : 'Resolve alert'}
            </button>
          </div>
        </form>
      </Dialog>

      <Dialog open={blocker.state === 'blocked'} title="Discard your unsent review note?" onClose={() => blocker.reset?.()}>
        <p className="text-sm text-slate-700">
          {frozen
            ? 'A review action has not been confirmed yet. If you leave, you will not be able to retry it from this page.'
            : 'You have typed a note that has not been submitted. Leaving will discard it.'}
        </p>
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button type="button" onClick={() => blocker.reset?.()} className={`${button} bg-indigo-700 text-white`}>
            Stay on this page
          </button>
          <button type="button" onClick={() => blocker.proceed?.()} className={`${button} border border-slate-300 bg-white`}>
            Discard and leave
          </button>
        </div>
      </Dialog>
    </section>
  )
}
