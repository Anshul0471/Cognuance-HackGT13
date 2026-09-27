import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { CurrentUser } from '../lib/api'
import type { PatientListItem } from '../features/doctor/schemas'
import { AuthProvider } from './AuthProvider'

const doctor: CurrentUser = {
  id: 'd1',
  email: 'dr.rivera@demo.test',
  role: 'doctor',
  display_name: 'Dr. Ana Rivera',
  patient_id: null,
  doctor_id: 'd-1',
}

const patient: CurrentUser = {
  id: 'u2',
  email: 'eleanor.park@demo.test',
  role: 'patient',
  display_name: 'Eleanor Park',
  patient_id: 'p2',
  doctor_id: null,
}

const eleanor: PatientListItem = {
  patient_id: 'p2',
  display_name: 'Eleanor Park',
  is_demo: true,
  account_active: true,
  latest_assessment_at: null,
  latest_analysis_availability: null,
  latest_deviation_level: null,
  unresolved_alert_count: 0,
}

const summary = {
  assigned_patient_count: 1,
  patients_with_open_alerts: 0,
  open_alert_count: 0,
  acknowledged_alert_count: 0,
  pending_analysis_count: 0,
  analysis_error_count: 0,
  generated_at: '2026-09-26T00:00:00.000Z',
}

type Handler = (init: RequestInit | undefined) => { status: number; body: unknown }

function mockBackend(user: CurrentUser, extra: Record<string, Handler> = {}) {
  const routes: Record<string, Handler> = {
    'POST /auth/login': (init) => {
      const body = JSON.parse(String(init?.body)) as { email: string; password: string }
      return body.password === 'right-password'
        ? { status: 200, body: { access_token: 'tok-123', token_type: 'bearer', expires_in: 1800, user } }
        : { status: 401, body: { error: { code: 'INVALID_CREDENTIALS', message: 'x', request_id: null, details: {} } } }
    },
    'POST /auth/logout': () => ({ status: 204, body: null }),
    'GET /doctor/patients': () => ({ status: 200, body: { items: [eleanor], next_cursor: null } }),
    'GET /doctor/summary': () => ({ status: 200, body: summary }),
    'GET /doctor/alerts': () => ({ status: 200, body: { items: [], next_cursor: null } }),
    ...extra,
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace('/api/v1', '').split('?')[0]
    const handler = routes[`${init?.method ?? 'GET'} ${path}`]
    const { status, body } = handler ? handler(init) : { status: 404, body: { detail: 'Not Found' } }
    if (status === 204) return new Response(null, { status })
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '*', element: <App /> }], { initialEntries: [path] })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

async function signIn(password = 'right-password') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'someone@demo.test')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('authentication flow', () => {
  it('redirects unauthenticated visitors to the login page', () => {
    mockBackend(doctor)
    renderApp('/doctor')
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
  })

  it('validates the form before calling the backend', async () => {
    const fetchMock = mockBackend(doctor)
    renderApp('/login')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows a generic error for wrong credentials', async () => {
    mockBackend(doctor)
    renderApp('/login')
    await signIn('wrong-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  })

  it('signs a doctor in, loads the overview with the bearer token, and keeps the token out of storage', async () => {
    const fetchMock = mockBackend(doctor)
    renderApp('/login')
    await signIn()

    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(await screen.findByText('No unresolved alerts.')).toBeInTheDocument()

    const summaryCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/doctor/summary'))
    expect(new Headers(summaryCall?.[1]?.headers).get('Authorization')).toBe('Bearer tok-123')
    expect(JSON.stringify({ ...localStorage })).not.toContain('tok-123')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('tok-123')
    expect(document.cookie).not.toContain('tok-123')
  })

  it('sends a patient to the patient area and keeps them out of doctor routes', async () => {
    mockBackend(patient)
    renderApp('/doctor')
    await signIn()
    // `from` was /doctor, but a patient is never returned to another role's area.
    expect(await screen.findByRole('heading', { name: 'Hello, Eleanor Park' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it('returns to the login page when the server rejects the session', async () => {
    mockBackend(doctor, {
      'GET /doctor/summary': () => ({
        status: 401,
        body: { error: { code: 'NOT_AUTHENTICATED', message: 'x', request_id: null, details: {} } },
      }),
    })
    renderApp('/login')
    await signIn()
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument())
  })

  it('signs out, revokes the server session and clears local state', async () => {
    const fetchMock = mockBackend(doctor)
    renderApp('/login')
    await signIn()
    await screen.findByRole('heading', { name: 'Overview' })
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('You have signed out.')
    expect(screen.queryByText('Dr. Ana Rivera')).not.toBeInTheDocument()
    const logoutCall = fetchMock.mock.calls.find(([url, init]) => String(url).endsWith('/auth/logout') && init?.method === 'POST')
    expect(new Headers(logoutCall?.[1]?.headers).get('Authorization')).toBe('Bearer tok-123')
  })
})
