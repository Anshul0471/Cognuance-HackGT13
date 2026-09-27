import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../auth/AuthProvider'
import { safeReturnPath } from '../auth/context'
import type { CurrentUser } from '../lib/api'
import { PROTOTYPE_DISCLOSURE } from './AboutPage'

const patient: CurrentUser = {
  id: 'u2',
  email: 'eleanor.park@demo.test',
  role: 'patient',
  display_name: 'Eleanor Park',
  patient_id: 'p2',
  doctor_id: null,
}

const assessmentStatus = {
  current_session: null,
  last_receipt: null,
  schedule: {
    scheduled_start_allowed: true,
    reason_codes: ['FIRST_CHECKIN'],
    window_opens_at: null,
    anchor_at: null,
  },
}

type Reply = { status: number; body: unknown; headers?: Record<string, string> }

function mockBackend(routes: Record<string, (init?: RequestInit) => Reply> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace('/api/v1', '').split('?')[0]
    const handler = routes[`${init?.method ?? 'GET'} ${path}`]
    const reply = handler ? handler(init) : { status: 404, body: { error: { code: 'NOT_FOUND', message: 'x', request_id: null, details: {} } } }
    if (reply.status === 204) return new Response(null, { status: 204 })
    return new Response(JSON.stringify(reply.body), {
      status: reply.status,
      headers: { 'Content-Type': 'application/json', ...reply.headers },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const loginOk = (user: CurrentUser) => () => ({
  status: 200,
  body: { access_token: 'tok-public', token_type: 'bearer', expires_in: 1800, user },
})

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter([{ path: '*', element: <App /> }], { initialEntries: [path] })
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>,
  )
  return router
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('public landing page', () => {
  it('shows the COGNUANCE welcome page without credentials or any API request', () => {
    const fetchMock = mockBackend()
    renderAt('/')
    expect(screen.getByText('Welcome to COGNUANCE')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'A clearer view of cognitive changes over time.' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'How it works' })).toBeInTheDocument()
    for (const card of ['Focused assessments', 'Clear visual insights', 'Connected review']) {
      expect(screen.getByRole('heading', { name: card })).toBeInTheDocument()
    }
    expect(document.title).toBe('COGNUANCE | Welcome')
    // No demo banners on the public page; the disclosure lives on About.
    expect(screen.queryByText(/fictional|demo record/i)).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'About COGNUANCE' }).length).toBeGreaterThan(0)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('opens the real sign-in form from the primary action and returns home from it', async () => {
    mockBackend()
    const router = renderAt('/')
    const user = userEvent.setup()
    await user.click(screen.getAllByRole('link', { name: 'Sign in' })[0])
    expect(router.state.location.pathname).toBe('/login')
    expect(screen.getByRole('heading', { name: 'Welcome back' })).toBeInTheDocument()
    expect(screen.getByText('Sign in to continue to COGNUANCE.')).toBeInTheDocument()
    expect(document.title).toBe('COGNUANCE | Sign in')
    await user.click(screen.getByRole('link', { name: 'Back to home' }))
    expect(router.state.location.pathname).toBe('/')
  })

  it('offers Open dashboard for the signed-in role instead of Sign in', async () => {
    mockBackend({ 'POST /auth/login': loginOk(patient), 'GET /patient/assessment-status': () => ({ status: 200, body: assessmentStatus }) })
    const router = renderAt('/login')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), 'someone@demo.test')
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Hello, Eleanor Park' })).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'COGNUANCE' }))
    expect(router.state.location.pathname).toBe('/patient')
    await router.navigate('/')
    const open = await screen.findAllByRole('link', { name: 'Open dashboard' })
    expect(open[0]).toHaveAttribute('href', '/patient')
    expect(screen.queryByRole('link', { name: 'Sign in' })).not.toBeInTheDocument()
  })

  it('mobile menu exposes How it works and About, closes after navigation and on Escape', async () => {
    mockBackend()
    const router = renderAt('/')
    const user = userEvent.setup()
    const toggle = screen.getByRole('button', { name: 'Open menu' })
    await user.click(toggle)
    const menu = document.getElementById('public-mobile-nav')!
    expect(within(menu).getByRole('link', { name: 'How it works' })).toHaveAttribute('href', '/#how-it-works')
    await user.keyboard('{Escape}')
    expect(document.getElementById('public-mobile-nav')).toBeNull()
    expect(toggle).toHaveFocus()

    await user.click(toggle)
    await user.click(within(document.getElementById('public-mobile-nav')!).getByRole('link', { name: 'About' }))
    expect(router.state.location.pathname).toBe('/about')
    expect(document.getElementById('public-mobile-nav')).toBeNull()
  })
})

describe('about page', () => {
  it('holds the consolidated prototype disclosure and readable source labels, with no API calls', () => {
    const fetchMock = mockBackend()
    renderAt('/about')
    expect(screen.getByRole('heading', { level: 1, name: 'About COGNUANCE' })).toBeInTheDocument()
    expect(screen.getByText(PROTOTYPE_DISCLOSURE)).toBeInTheDocument()
    for (const label of ['Interactive assessment', 'Synthetic history', 'Simulated scenario']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(document.title).toBe('COGNUANCE | About')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('sign-in refinements', () => {
  it('toggles password visibility without submitting', async () => {
    const fetchMock = mockBackend()
    renderAt('/login')
    const user = userEvent.setup()
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    expect(password).toHaveAttribute('autocomplete', 'current-password')
    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide password' })).toHaveAttribute('aria-pressed', 'true')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByText('Enter a valid email address')).not.toBeInTheDocument()
  })

  it('shows the rate-limit wait, keeps the email, and never prefills credentials', async () => {
    mockBackend({
      'POST /auth/login': () => ({
        status: 429,
        headers: { 'Retry-After': '240' },
        body: { error: { code: 'TOO_MANY_LOGIN_ATTEMPTS', message: 'x', request_id: 'r', details: {} } },
      }),
    })
    renderAt('/login')
    const user = userEvent.setup()
    expect(screen.getByLabelText('Email')).toHaveValue('')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    await user.type(screen.getByLabelText('Email'), 'someone@demo.test')
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many sign-in attempts. Try again in 4 minutes.')
    expect(screen.getByLabelText('Email')).toHaveValue('someone@demo.test')
  })

  it('sends a protected deep link straight to sign-in, then back to it', async () => {
    mockBackend({ 'POST /auth/login': loginOk(patient), 'GET /patient/assessment-status': () => ({ status: 200, body: assessmentStatus }) })
    const router = renderAt('/patient/check-in')
    expect(router.state.location.pathname).toBe('/login')
    expect(screen.queryByText('Welcome to COGNUANCE')).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Email'), 'someone@demo.test')
    await user.type(screen.getByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await vi.waitFor(() => expect(router.state.location.pathname).toBe('/patient/check-in'))
  })

  it('rejects external or malformed return destinations', () => {
    for (const bad of ['https://evil.example/patient', '//evil.example', '/patient\\evil', '/patientx', '/doctor', 42, null]) {
      expect(safeReturnPath(bad, 'patient')).toBe('/patient')
    }
    expect(safeReturnPath('/patient/check-in?extra=1', 'patient')).toBe('/patient/check-in?extra=1')
  })
})
