import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SetupStatusPage } from './SetupStatusPage'

type MockResponse = { status: number; body: unknown }

function mockFetch(routes: Record<string, MockResponse | 'network-error' | 'pending'>) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    const key = Object.keys(routes).find((path) => url.endsWith(path))
    const route = key ? routes[key] : { status: 404, body: { detail: 'Not Found' } }
    if (route === 'pending') return new Promise<Response>(() => {})
    if (route === 'network-error') return Promise.reject(new TypeError('Failed to fetch'))
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SetupStatusPage />
    </QueryClientProvider>,
  )
}

const card = (name: string) => screen.getByRole('region', { name })

const readyBody = { status: 'ready' }

const modelBody = {
  model_kind: null,
  model_version: null,
  policy_version: null,
  model_loaded: false,
  policy_ready: false,
  forecast_ready: false,
  reason_code: 'MODEL_NOT_CONFIGURED',
}

const errorBody = (code: string) => ({ error: { code, message: 'x', request_id: 'r-1', details: {} } })

describe('SetupStatusPage', () => {
  it('shows loading state while requests are pending', () => {
    mockFetch({ '/health': 'pending', '/ready': 'pending', '/model/status': 'pending' })
    renderPage()
    expect(screen.getAllByText('Checking')).toHaveLength(3)
  })

  it('shows ready state from successful responses', async () => {
    mockFetch({
      '/health': { status: 200, body: { status: 'ok' } },
      '/ready': { status: 200, body: readyBody },
      '/model/status': { status: 200, body: modelBody },
    })
    renderPage()
    expect(await within(card('API health')).findByText('Alive')).toBeInTheDocument()
    expect(await within(card('Readiness (database + migrations)')).findByText('Ready')).toBeInTheDocument()
    // Model must honestly report not-ready.
    expect(await within(card('Forecasting model')).findByText('Not ready')).toBeInTheDocument()
    expect(within(card('Forecasting model')).getByText('Unavailable reason: MODEL_NOT_CONFIGURED')).toBeInTheDocument()
  })

  it('names the active model when forecasting is ready', async () => {
    mockFetch({
      '/health': { status: 200, body: { status: 'ok' } },
      '/ready': { status: 200, body: readyBody },
      '/model/status': {
        status: 200,
        body: { ...modelBody, model_kind: 'GRU', model_version: 'm-1', policy_version: 'p-1', model_loaded: true,
                policy_ready: true, forecast_ready: true, reason_code: null },
      },
    })
    renderPage()
    expect(await within(card('Forecasting model')).findByText('Ready')).toBeInTheDocument()
    expect(within(card('Forecasting model')).getByText('Active: GRU m-1 · policy p-1')).toBeInTheDocument()
  })

  it('shows unavailable state when backend is down or not ready', async () => {
    mockFetch({
      '/health': 'network-error',
      '/ready': { status: 503, body: errorBody('DATABASE_UNAVAILABLE') },
      '/model/status': 'network-error',
    })
    renderPage()
    expect(await within(card('API health')).findByText('Backend unreachable')).toBeInTheDocument()
    const readiness = card('Readiness (database + migrations)')
    expect(await within(readiness).findByText('Unavailable')).toBeInTheDocument()
    expect(within(readiness).getByText('Database unreachable')).toBeInTheDocument()
  })
})
