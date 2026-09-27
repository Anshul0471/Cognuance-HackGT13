import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { AuthProvider } from '../../auth/AuthProvider'
import { apiFetch, ApiError, setAccessToken } from '../../lib/api'
import type { AlertEventRequest } from './schemas'
import { alertDetail, insightRecord, insightsResponse, patientDetail, timelineItem } from './test/fixtures'

type Reply = { status: number; body?: unknown; headers?: Record<string, string> } | 'network-error'
type Handler = (url: URL, init: RequestInit | undefined) => Reply

const doctor = { id: 'd1', email: 'dr.rivera@demo.test', role: 'doctor', display_name: 'Dr. Ana Rivera', patient_id: null, doctor_id: 'd1' }
const patientUser = { id: 'u2', email: 'walter.hughes@demo.test', role: 'patient', display_name: 'Walter Hughes', patient_id: 'p-walter', doctor_id: null }
const summary = {
  assigned_patient_count: 4,
  patients_with_open_alerts: 1,
  open_alert_count: 1,
  acknowledged_alert_count: 0,
  pending_analysis_count: 0,
  analysis_error_count: 0,
  generated_at: '2026-09-26T20:00:00Z',
}
const empty = { items: [], next_cursor: null }
const err = (status: number, code: string, details: Record<string, unknown> = {}): Reply => ({
  status,
  body: { error: { code, message: code, request_id: 'req-123', details } },
})

function mockBackend(routes: Record<string, Handler>, user: object = doctor) {
  const all: Record<string, Handler> = {
    'POST /auth/login': () => ({ status: 200, body: { access_token: 'tok', token_type: 'bearer', expires_in: 1800, user } }),
    'POST /auth/logout': () => ({ status: 204 }),
    'GET /doctor/summary': () => ({ status: 200, body: summary }),
    'GET /doctor/alerts': () => ({ status: 200, body: empty }),
    'GET /doctor/patients': () => ({ status: 200, body: empty }),
    'GET /model/status': () => ({
      status: 200,
      body: { model_kind: 'GRU', model_version: 'm', policy_version: 'p', model_loaded: true, policy_ready: true, forecast_ready: true, reason_code: null },
    }),
    'GET /patient/assessment-status': () => ({
      status: 200,
      body: {
        patient_id: 'p-walter',
        server_time: '2026-09-26T20:00:00Z',
        current_session: null,
        last_receipt: null,
        schedule: { anchor_at: null, next_target_at: null, window_opens_at: null, window_closes_at: null, scheduled_start_allowed: true, reason_codes: ['FIRST_CHECKIN'] },
      },
    }),
    ...routes,
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const path = url.pathname.replace('/api/v1', '')
    const handler =
      all[`${init?.method ?? 'GET'} ${path}`] ??
      Object.entries(all).find(([key]) => {
        const [method, pattern] = key.split(' ')
        return method === (init?.method ?? 'GET') && new RegExp(`^${pattern.replace(/:[^/]+/g, '[^/]+')}$`).test(path)
      })?.[1]
    const reply = handler ? handler(url, init) : err(404, 'NOT_FOUND')
    if (reply === 'network-error') throw new TypeError('Failed to fetch')
    const headers = { 'Content-Type': 'application/json', 'X-Request-ID': 'hdr-req-1', ...reply.headers }
    if (reply.status === 204) return new Response(null, { status: 204, headers })
    return new Response(JSON.stringify(reply.body), { status: reply.status, headers })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function calls(fetchMock: ReturnType<typeof mockBackend>, method: string, pathPart: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => (init?.method ?? 'GET') === method && String(url).includes(pathPart),
  )
}

async function openAs(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '*', element: <App /> }], { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'someone@demo.test')
  await user.type(screen.getByLabelText('Password'), 'pw')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  return { user, router, client }
}

describe('doctor dashboard access', () => {
  it('keeps a patient out of doctor pages even after a direct link', async () => {
    const fetchMock = mockBackend({}, patientUser)
    await openAs('/doctor/alerts/al-1')
    expect(await screen.findByRole('heading', { name: /Hello, Walter Hughes/ })).toBeInTheDocument()
    expect(calls(fetchMock, 'GET', '/doctor/')).toHaveLength(0)
  })

  it('shows a neutral unavailable state for an unassigned alert and loads nothing else about it', async () => {
    const fetchMock = mockBackend({ 'GET /doctor/alerts/:id': () => err(404, 'NOT_FOUND') })
    await openAs('/doctor/alerts/someone-elses-alert')
    expect(await screen.findByText('This record is unavailable or you no longer have access.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Review actions/ })).not.toBeInTheDocument()
    expect(calls(fetchMock, 'GET', '/events')).toHaveLength(0)
  })

  it('shows the clinician review prompt for an open alert without acknowledging it', async () => {
    const fetchMock = mockBackend({
      'GET /doctor/alerts/:id': () => ({ status: 200, body: alertDetail() }),
      'GET /doctor/alerts/:id/events': () => ({ status: 200, body: empty }),
      'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
    })
    await openAs('/doctor/alerts/al-1')
    expect(
      await screen.findByRole('heading', { name: 'Unexpected performance change — clinical review requested' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Assess whether follow-up evaluation or additional testing is appropriate/)).toBeInTheDocument()
    expect(screen.getByText(/not a diagnosis, a test order or an emergency escalation/)).toBeInTheDocument()
    expect(calls(fetchMock, 'POST', '/events')).toHaveLength(0) // opening the prompt changes nothing
  })

  it('shows a resolved alert as completed, not as a new request', async () => {
    mockBackend({
      'GET /doctor/alerts/:id': () => ({ status: 200, body: alertDetail({ workflow_status: 'RESOLVED', lock_version: 3 }) }),
      'GET /doctor/alerts/:id/events': () => ({ status: 200, body: empty }),
      'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
    })
    await openAs('/doctor/alerts/al-1')
    expect(await screen.findByRole('heading', { name: 'Clinical review completed' })).toBeInTheDocument()
    expect(screen.queryByText(/clinical review requested/)).not.toBeInTheDocument()
  })

  it('hides the alert and drops its evidence when a review action reveals lost access', async () => {
    mockBackend({
      'GET /doctor/alerts/:id': () => ({ status: 200, body: alertDetail() }),
      'GET /doctor/alerts/:id/events': () => ({ status: 200, body: empty }),
      'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
      'POST /doctor/alerts/:id/events': () => err(404, 'NOT_FOUND'),
    })
    const { user } = await openAs('/doctor/alerts/al-1')
    await user.click(await screen.findByRole('button', { name: 'Acknowledge' }))
    expect(await screen.findByText('This record is unavailable or you no longer have access.')).toBeInTheDocument()
    expect(screen.queryByText(/647.5 ms slower/)).not.toBeInTheDocument()
  })

  it('never delivers a read that was answered for a different session', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => (release = resolve))))
    setAccessToken('doctor-a')
    const pending = apiFetch('/doctor/patients/p-a')
    setAccessToken('doctor-b')
    release(new Response(JSON.stringify({ secret: 'A' }), { status: 200 }))
    await expect(pending).rejects.toBeInstanceOf(ApiError)
    setAccessToken(null)
  })
})

describe('status fidelity', () => {
  it('never shows an unavailable, pending or failed analysis as a no-deviation result', async () => {
    const row = (id: string, availability: string) => ({
      patient_id: id,
      display_name: `Patient ${availability}`,
      is_demo: true,
      account_active: id !== 'p4',
      latest_assessment_at: '2026-09-26T16:00:00Z',
      latest_analysis_availability: availability,
      latest_deviation_level: null,
      unresolved_alert_count: 0,
    })
    mockBackend({
      'GET /doctor/patients': () => ({
        status: 200,
        body: {
          items: [row('p1', 'PENDING'), row('p2', 'BUILDING_BASELINE'), row('p3', 'MODEL_UNAVAILABLE'), row('p4', 'ANALYSIS_ERROR'), row('p5', 'INSUFFICIENT_DATA')],
          next_cursor: null,
        },
      }),
    })
    await openAs('/doctor/patients')
    const table = await screen.findByRole('table')
    for (const label of ['Analysis pending', 'Building a personal baseline', 'Forecast unavailable', 'Analysis could not be completed', 'Not enough usable history']) {
      expect(within(table).getByText(label)).toBeInTheDocument()
    }
    expect(within(table).queryByText('No configured deviation detected')).not.toBeInTheDocument()
    expect(within(table).getByText('Patient account inactive')).toBeInTheDocument()
  })

  it('keeps a resolved alert’s original deviation category', async () => {
    mockBackend({
      'GET /doctor/alerts': (url) =>
        url.searchParams.get('workflow_status') === 'RESOLVED'
          ? { status: 200, body: { items: [{ ...alertDetail({ workflow_status: 'RESOLVED', lock_version: 3 }), assessment: undefined, events_path: undefined }], next_cursor: null } }
          : { status: 200, body: empty },
    })
    await openAs('/doctor/alerts?status=RESOLVED')
    const row = (await screen.findByText('Walter Hughes')).closest('li')!
    expect(within(row).getByText('Large change flagged')).toBeInTheDocument()
    expect(within(row).getByText('Resolved')).toBeInTheDocument()
  })

  it('fails visibly with a request ID when a response has an unexpected shape', async () => {
    mockBackend({ 'GET /doctor/summary': () => ({ status: 200, body: { ...summary, open_alert_count: 'many' } }) })
    await openAs('/doctor')
    expect(await screen.findByText(/unexpected format/)).toBeInTheDocument()
    expect(screen.getByText('hdr-req-1')).toBeInTheDocument()
    expect(screen.queryByText('Open alerts')).not.toBeInTheDocument()
  })
})

describe('alert inbox filters and pagination', () => {
  it('maps status filters to exact params, resets the cursor on change and dedupes pages', async () => {
    const first = { ...alertDetail(), assessment: undefined, events_path: undefined }
    const second = { ...first, alert_id: 'al-2', patient_display_name: 'Rosa Delgado' }
    const fetchMock = mockBackend({
      'GET /doctor/alerts': (url) =>
        url.searchParams.get('cursor') === 'c1'
          ? { status: 200, body: { items: [first, second], next_cursor: null } }
          : { status: 200, body: { items: [first], next_cursor: 'c1' } },
    })
    const { user } = await openAs('/doctor/alerts')
    await user.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('Rosa Delgado')).toBeInTheDocument()
    expect(screen.getAllByText('Walter Hughes')).toHaveLength(1)

    await user.selectOptions(screen.getByLabelText('Review status'), 'ALL')
    await user.selectOptions(screen.getByLabelText('Review status'), 'RESOLVED')
    const urls = calls(fetchMock, 'GET', '/doctor/alerts?').map(([url]) => new URL(String(url), 'http://x').searchParams)
    const unresolved = urls.find((p) => !p.has('workflow_status') && !p.has('include_resolved') && !p.has('cursor'))
    const all = urls.find((p) => p.get('include_resolved') === 'true')
    const resolved = urls.find((p) => p.get('workflow_status') === 'RESOLVED')
    expect(unresolved).toBeDefined()
    expect(all?.has('workflow_status')).toBe(false)
    expect(all?.has('cursor')).toBe(false)
    expect(resolved?.has('include_resolved')).toBe(false)
    expect(urls.every((p) => !(p.has('workflow_status') && p.has('include_resolved')))).toBe(true)
  })
})

function reviewBackend(post: (body: AlertEventRequest, n: number) => Reply, current = { status: 'OPEN', version: 1 }) {
  const bodies: AlertEventRequest[] = []
  const state = { ...current }
  const fetchMock = mockBackend({
    'GET /doctor/alerts/:id': () => ({
      status: 200,
      body: alertDetail({ workflow_status: state.status as 'OPEN', lock_version: state.version }),
    }),
    'GET /doctor/alerts/:id/events': () => ({ status: 200, body: empty }),
    'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
    'POST /doctor/alerts/:id/events': (_url, init) => {
      const body = JSON.parse(String(init?.body)) as AlertEventRequest
      bodies.push(body)
      const reply = post(body, bodies.length)
      if (reply !== 'network-error' && reply.status === 200) {
        const { alert } = reply.body as { alert: { workflow_status: string; lock_version: number } }
        state.status = alert.workflow_status
        state.version = alert.lock_version
      }
      return reply
    },
  })
  return { fetchMock, bodies, state }
}

const accepted = (action: string, to: string, version: number, replayed = false): Reply => ({
  status: 200,
  body: {
    event: { event_id: `e-${version}`, action, from_status: 'OPEN', to_status: to, note: null, actor: { user_id: 'd1', display_name: 'Dr. Ana Rivera' }, created_at: '2026-09-26T20:05:00Z' },
    alert: { alert_id: 'al-1', workflow_status: to, lock_version: version },
    replayed,
  },
})

describe('review actions', () => {
  it('on a stale version keeps the draft, refreshes, and resubmits only explicitly with a new key and version', async () => {
    const { bodies, state, fetchMock } = reviewBackend((_body, n) => {
      if (n === 1) {
        state.status = 'ACKNOWLEDGED'
        state.version = 2
        return err(409, 'STALE_ALERT_VERSION', { workflow_status: 'ACKNOWLEDGED', lock_version: 2 })
      }
      return accepted('NOTE_ADDED', 'ACKNOWLEDGED', 3)
    })
    const { user } = await openAs('/doctor/alerts/al-1')
    const note = await screen.findByLabelText(/Review note/)
    await user.type(note, 'Discussed with caregiver.')
    await user.click(screen.getByRole('button', { name: 'Add note' }))

    expect(await screen.findByText(/Another update was made to this alert \(now Acknowledged\)/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Review note/)).toHaveValue('Discussed with caregiver.')
    await waitFor(() => expect(screen.getByText(/version 2/)).toBeInTheDocument())
    expect(calls(fetchMock, 'GET', '/doctor/alerts/al-1').length).toBeGreaterThan(1)
    expect(bodies).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Add note' }))
    expect(await screen.findByText(/Note added\. Current status: Acknowledged\./)).toBeInTheDocument()
    expect(bodies).toHaveLength(2)
    expect(bodies[1].expected_lock_version).toBe(2)
    expect(bodies[1].request_key).not.toBe(bodies[0].request_key)
    expect(bodies[1].note).toBe('Discussed with caregiver.')
    expect(screen.getByLabelText(/Review note/)).toHaveValue('')
  })

  it('retries a lost response with exactly the same request and trusts the returned current alert', async () => {
    const { bodies } = reviewBackend((_body, n) =>
      n === 1 ? 'network-error' : accepted('ACKNOWLEDGED', 'RESOLVED', 4, true),
    )
    const { user } = await openAs('/doctor/alerts/al-1')
    await user.type(await screen.findByLabelText(/Acknowledgment note/), '  Seen.  ')
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }))

    expect(await screen.findByText(/The result could not be confirmed/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add note' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Retry the same request' }))

    expect(await screen.findByText(/confirms the earlier request\) Current status: Resolved\./)).toBeInTheDocument()
    expect(bodies).toHaveLength(2)
    expect(bodies[1]).toEqual(bodies[0])
    expect(bodies[0]).toMatchObject({ action: 'ACKNOWLEDGED', expected_lock_version: 1, note: 'Seen.' })
  })

  it('uses the version returned by a confirmed note for the next action', async () => {
    const { bodies } = reviewBackend((body, n) =>
      n === 1 ? accepted('NOTE_ADDED', 'OPEN', 2) : accepted(body.action, 'ACKNOWLEDGED', 3),
    )
    const { user } = await openAs('/doctor/alerts/al-1')
    await user.type(await screen.findByLabelText(/Review note/), 'Called patient.')
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await screen.findByText(/Note added\./)
    await user.click(screen.getByRole('button', { name: 'Acknowledge' }))
    await screen.findByText(/Acknowledgment recorded\./)
    expect(bodies.map((b) => b.expected_lock_version)).toEqual([1, 2])
    expect(bodies[1].note).toBeNull()
  })

  it('resolves through an accessible dialog that requires a note and returns focus', async () => {
    const { bodies } = reviewBackend(() => accepted('RESOLVED', 'RESOLVED', 2))
    const { user } = await openAs('/doctor/alerts/al-1')
    const trigger = await screen.findByRole('button', { name: 'Resolve…' })
    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Resolve this alert' })
    const field = within(dialog).getByLabelText(/Resolution note/)
    expect(field).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Resolve alert' }))
    expect(within(screen.getByRole('dialog')).getByText('A note is required for this action.')).toBeInTheDocument()
    expect(bodies).toHaveLength(0)

    await user.type(within(screen.getByRole('dialog')).getByLabelText(/Resolution note/), 'Reviewed; no action needed.')
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Resolve alert' }))
    expect(await screen.findByText(/Alert resolved\./)).toBeInTheDocument()
    expect(bodies[0]).toMatchObject({ action: 'RESOLVED', note: 'Reviewed; no action needed.' })
  })

  it('asks before discarding an unsent note when navigating away', async () => {
    reviewBackend(() => accepted('NOTE_ADDED', 'OPEN', 2))
    const { user } = await openAs('/doctor/alerts/al-1')
    await user.type(await screen.findByLabelText(/Review note/), 'Draft in progress')
    await user.click(screen.getAllByRole('link', { name: /Overview/ })[0])
    expect(await screen.findByRole('dialog', { name: 'Discard your unsent review note?' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Stay on this page' }))
    expect(screen.getByLabelText(/Review note/)).toHaveValue('Draft in progress')
    await user.click(screen.getAllByRole('link', { name: /Overview/ })[0])
    await user.click(await screen.findByRole('button', { name: 'Discard and leave' }))
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })
})

describe('patient history', () => {
  it('renders every loaded check-in in the table, including unreliable and extra ones, with nulls as unavailable', async () => {
    const items = [
      timelineItem(2, { assessment_id: 'a-extra', schedule_purpose: 'EXTRA_ATTEMPT', longitudinal_eligible: false }),
      timelineItem(1, { quality_status: 'INCOMPLETE', longitudinal_eligible: false, scores: { memory_score: null, attention_score: 80, reaction_time_ms: null } }),
      timelineItem(0),
    ]
    const fetchMock = mockBackend({
      'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
      'GET /doctor/patients/:id/timeline': () => ({ status: 200, body: { items, next_cursor: 'older' } }),
    })
    const { user } = await openAs('/doctor/patients/p-walter')
    const table = await screen.findByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(within(table).getByText('Extra attempt')).toBeInTheDocument()
    expect(within(table).getAllByText('Unavailable')).toHaveLength(2)
    expect(screen.getByText(/Older assessments exist but are not loaded yet/)).toBeInTheDocument()
    expect(screen.getByText(/Memory task results and forecasts across 3 loaded assessments/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('From (inclusive)'), '2026-09-30')
    await user.type(screen.getByLabelText('To (inclusive)'), '2026-09-01')
    const before = calls(fetchMock, 'GET', '/timeline').length
    await user.click(screen.getByRole('button', { name: 'Apply dates' }))
    expect(screen.getByRole('alert')).toHaveTextContent('The start date must be on or before the end date.')
    expect(calls(fetchMock, 'GET', '/timeline')).toHaveLength(before)
    expect(screen.getByRole('heading', { name: 'Cognitive Score' })).toBeInTheDocument()
    expect(screen.getByText('Prototype task-performance index · 0–100')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Explore Visual Insights/ })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { name: 'Memory task' })[0]).toBeInTheDocument()

    // Refinements 02/03: branded title, no per-record demo/source badges, score stays above Memory task.
    expect(document.title).toBe('COGNUANCE | Assessment history')
    expect(screen.queryByText('Demo record')).not.toBeInTheDocument()
    expect(screen.queryByText(/fictional/i)).not.toBeInTheDocument()
    // Refinement 03: no per-row source tags; provenance lives in the assessment's record details.
    expect(within(table).queryByText(/Interactive assessment|Synthetic history|Simulated scenario/)).toBeNull()
    const score = screen.getByRole('heading', { name: 'Cognitive Score' })
    const memory = screen.getAllByRole('heading', { name: 'Memory task' })[0]
    expect(score.compareDocumentPosition(memory) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('visual insights', () => {
  const records = [
    insightRecord(0, { source: 'LIVE_DEMO' }),
    insightRecord(1, {
      source: 'LIVE_DEMO',
      previous_comparable_assessment_id: 'a-0',
      linked_alert: {
        alert_id: 'al-1',
        created_at: '2026-08-08T16:00:00Z',
        deviation_level: 'REVIEW',
        workflow_status: 'OPEN',
      },
      analysis: {
        availability: 'COMPLETE',
        deviation_level: 'REVIEW',
        aggregate_deviation: 2.1,
        persistent_count: 1,
        reason_codes: [],
      },
    }),
  ]

  const listItem = {
    patient_id: 'p-walter',
    display_name: 'Walter Hughes',
    is_demo: true,
    account_active: true,
    latest_assessment_at: null,
    latest_analysis_availability: null,
    latest_deviation_level: null,
    unresolved_alert_count: 1,
  }

  function insightsBackend() {
    return mockBackend({
      'GET /doctor/patients': () => ({
        status: 200,
        body: { items: [listItem], next_cursor: null },
      }),
      'GET /doctor/patients/:id': () => ({ status: 200, body: patientDetail }),
      'GET /doctor/patients/:id/insights': () => ({ status: 200, body: insightsResponse(records) }),
    })
  }

  it('shows a patient selector on a direct visit and does not fetch insights yet', async () => {
    const fetchMock = insightsBackend()
    await openAs('/doctor/insights')
    expect(await screen.findByText(/Choose an assigned patient/)).toBeInTheDocument()
    expect(calls(fetchMock, 'GET', '/insights')).toHaveLength(0)
  })

  it('asks for a patient on a direct visit and does not add a score panel to the overview', async () => {
    mockBackend({
      'GET /doctor/patients': () => ({
        status: 200,
        body: { items: [{ ...listItem, unresolved_alert_count: 0 }], next_cursor: null },
      }),
    })
    await openAs('/doctor')
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Cognitive Score' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Visual Insights' }).length).toBeGreaterThan(0)
  })

  it('loads a complete snapshot for a selected patient and links a heatmap selection to the breakdown', async () => {
    const fetchMock = insightsBackend()
    const { user } = await openAs('/doctor/insights?patientId=p-walter')
    expect(await screen.findByRole('heading', { name: 'Visual Insights' })).toBeInTheDocument()
    await waitFor(() => expect(calls(fetchMock, 'GET', '/insights').length).toBeGreaterThan(0))
    expect(screen.getByText('Eligible Cognitive Scores')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Domain performance heatmap' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Change between comparable assessments' })).toBeInTheDocument()
    expect(screen.queryByText('No alerts linked to assessments in this range.')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alert and review timeline' })).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: /Memory / })[0])
    expect(await screen.findByRole('heading', { name: 'Selected check-in' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Pin for comparison' }))
    expect(screen.getByText(/Pin two check-ins/)).toBeInTheDocument()
  })

  it('clears an unavailable selection when the snapshot no longer contains it', async () => {
    insightsBackend()
    await openAs('/doctor/insights?patientId=p-walter&assessment=missing-id&pinA=missing-id')
    expect(await screen.findByText(/Select a heatmap column/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Selected check-in' })).not.toBeInTheDocument()
  })
})
