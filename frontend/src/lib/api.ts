import type {
  AssessmentStatus,
  AssessmentSubmission,
  Receipt,
  SessionRecovery,
  StartAssessmentResponse,
  StartSessionRequest,
} from '../assessment/types'
// Central typed API client. All backend calls go through apiFetch (doctor endpoints: features/doctor/api.ts).

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1'

// The access token lives only in this module's memory: never localStorage/sessionStorage/cookies.
// A page reload therefore requires signing in again (accepted for the MVP).
let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function hasAccessToken(): boolean {
  return accessToken !== null
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

/** Every backend error: `{"error": {code, message, request_id, details}}`. */
export type ErrorBody = { code: string; message: string; request_id: string | null; details: Record<string, unknown> }

/** Client-side code for a 2xx response whose body does not match the declared contract. */
export const UNEXPECTED_RESPONSE = 'UNEXPECTED_RESPONSE'

type ErrorMeta = { requestId?: string | null; retryAfterSeconds?: number | null; code?: string }

export class ApiError extends Error {
  readonly status: number | null
  readonly body: unknown
  private readonly meta: ErrorMeta

  constructor(message: string, status: number | null, body: unknown = null, meta: ErrorMeta = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.meta = meta
  }

  get isNetworkError(): boolean {
    return this.status === null
  }

  private get envelope(): ErrorBody | null {
    const error = (this.body as { error?: unknown } | null)?.error
    return error && typeof error === 'object' ? (error as ErrorBody) : null
  }

  /** Machine-readable `error.code` (e.g. 409 SESSION_EXPIRED); null for network failures. */
  get code(): string | null {
    if (this.meta.code) return this.meta.code
    return typeof this.envelope?.code === 'string' ? this.envelope.code : null
  }

  /** Safe server message for display. */
  get detail(): string | null {
    return typeof this.envelope?.message === 'string' ? this.envelope.message : null
  }

  get requestId(): string | null {
    if (typeof this.envelope?.request_id === 'string') return this.envelope.request_id
    return this.meta.requestId ?? null
  }

  get details(): Record<string, unknown> {
    return this.envelope?.details ?? {}
  }

  /** Seconds from a 429 `Retry-After` header, when the server supplied one. */
  get retryAfterSeconds(): number | null {
    return this.meta.retryAfterSeconds ?? null
  }
}

const NO_RETRY_STATUSES = new Set([400, 401, 403, 404, 409, 413, 415, 422])

/** Bounded retries for transient read failures only; 429 waits for its `Retry-After`. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (!(error instanceof ApiError)) return failureCount < 2
  if (error.code === UNEXPECTED_RESPONSE || NO_RETRY_STATUSES.has(error.status ?? 0)) return false
  if (error.status === 429) return failureCount < 1 && (error.retryAfterSeconds ?? 0) <= 60
  return failureCount < 2
}

export function queryRetryDelay(failureCount: number, error: unknown): number {
  if (error instanceof ApiError && error.status === 429 && error.retryAfterSeconds !== null) {
    return error.retryAfterSeconds * 1000
  }
  return Math.min(1000 * 2 ** failureCount, 8000)
}

type FetchOptions<T = unknown> = RequestInit & {
  /** Let the caller handle a 401 (e.g. re-authenticate while a check-in draft is held in memory). */
  handleUnauthorized?: boolean
  /** Validate a successful body; a mismatch fails visibly as UNEXPECTED_RESPONSE, never coerced. */
  parse?: (body: unknown) => T
}

function retryAfter(response: Response): number | null {
  const value = Number(response.headers.get('Retry-After'))
  return Number.isFinite(value) && value >= 0 ? value : null
}

export function jsonInit<T>(method: string, body: unknown, options?: FetchOptions<T>): FetchOptions<T> {
  return {
    ...options,
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

/** Query string from defined params only (no tokens ever go in URLs). */
export function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export async function apiFetch<T>(path: string, options?: FetchOptions<T>): Promise<T> {
  const { handleUnauthorized, parse, ...init } = options ?? {}
  const headers = new Headers(init?.headers)
  headers.set('Accept', 'application/json')
  const sentToken = accessToken
  if (sentToken) headers.set('Authorization', `Bearer ${sentToken}`)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  } catch (error) {
    if (init.signal?.aborted) throw error
    throw new ApiError('Could not reach the backend', null)
  }
  const requestId = response.headers.get('X-Request-ID')

  // A read answered for a different session (sign-out or account change mid-flight) is never delivered.
  if ((init.method ?? 'GET') === 'GET' && sentToken !== null && accessToken !== sentToken) {
    throw new ApiError('The session changed while this request was in flight', null, null, { requestId })
  }

  const text = await response.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }

  if (!response.ok) {
    // An authenticated request rejected as 401 means the session expired or was revoked.
    if (response.status === 401 && sentToken && !handleUnauthorized) onUnauthorized?.()
    throw new ApiError(`Request failed with status ${response.status}`, response.status, body, {
      requestId,
      retryAfterSeconds: retryAfter(response),
    })
  }
  if (!parse) return body as T
  try {
    return parse(body)
  } catch {
    throw new ApiError('The server response did not match the expected format', response.status, null, {
      requestId,
      code: UNEXPECTED_RESPONSE,
    })
  }
}

export type HealthResponse = { status: 'ok' }
export type ReadyResponse = { status: 'ready' }

export type ModelStatusResponse = {
  model_kind: 'LAST_VALUE' | 'LINEAR_TREND' | 'GRU' | null
  model_version: string | null
  policy_version: string | null
  model_loaded: boolean
  policy_ready: boolean
  forecast_ready: boolean
  reason_code: string | null
}

export type UserRole = 'patient' | 'doctor'

export type CurrentUser = {
  id: string
  email: string
  display_name: string
  role: UserRole
  patient_id: string | null
  doctor_id: string | null
}

export type TokenResponse = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: CurrentUser
}

export const api = {
  health: () => apiFetch<HealthResponse>('/health'),
  ready: () => apiFetch<ReadyResponse>('/ready'),
  modelStatus: () => apiFetch<ModelStatusResponse>('/model/status'),
  login: (email: string, password: string) =>
    apiFetch<TokenResponse>('/auth/login', jsonInit('POST', { email, password })),
  me: () => apiFetch<CurrentUser>('/auth/me'),
  /** Revokes the server-side session; 204 with no body. */
  logout: (signal?: AbortSignal) =>
    apiFetch<null>('/auth/logout', { method: 'POST', handleUnauthorized: true, signal }),

  assessmentStatus: () => apiFetch<AssessmentStatus>('/patient/assessment-status'),
  startSession: (body: StartSessionRequest) =>
    apiFetch<StartAssessmentResponse>('/patient/assessment-sessions', jsonInit('POST', body)),
  session: (sessionId: string) =>
    apiFetch<SessionRecovery>(`/patient/assessment-sessions/${encodeURIComponent(sessionId)}`),
  /** 204 with no body; repeating on an abandoned/expired session is a no-op. */
  abandonSession: (sessionId: string) =>
    apiFetch<null>(`/patient/assessment-sessions/${encodeURIComponent(sessionId)}/abandon`, {
      method: 'POST',
    }),
  submitAssessment: (sessionId: string, body: AssessmentSubmission) =>
    apiFetch<Receipt>(
      `/patient/assessment-sessions/${encodeURIComponent(sessionId)}/submissions`,
      jsonInit('POST', body, { handleUnauthorized: true }),
    ),
  receipt: (assessmentId: string) =>
    apiFetch<Receipt>(`/patient/assessments/${encodeURIComponent(assessmentId)}/receipt`),
}
