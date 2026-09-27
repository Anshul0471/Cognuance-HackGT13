import { createContext, useContext } from 'react'
import type { CurrentUser, UserRole } from '../lib/api'

export type AuthState = {
  user: CurrentUser | null
  login: (email: string, password: string) => Promise<CurrentUser>
  /** Resolves after local sign-out; `revocationConfirmed` is false if the server could not confirm it. */
  logout: () => Promise<{ revocationConfirmed: boolean }>
  /** Outcome of the most recent user sign-out on this page (null after a new sign-in). */
  lastSignOut: { revocationConfirmed: boolean } | null
  /**
   * While true (an unsent check-in is held in memory), token expiry or a 401 only clears the token
   * instead of logging out, so the patient can re-authenticate without redoing timed tasks.
   */
  setDraftActive: (active: boolean) => void
  /** Re-authenticate the *same* user. A different account logs out and rejects (draft discarded). */
  reauthenticate: (password: string) => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}

export function homePathFor(role: UserRole): string {
  return role === 'doctor' ? '/doctor' : '/patient'
}

/** A post-login return path must be an internal path inside the signed-in role's own area. */
export function safeReturnPath(from: unknown, role: UserRole): string {
  const home = homePathFor(role)
  if (typeof from !== 'string' || from.includes('\\') || from.includes('//')) return home
  const rest = from.slice(home.length)
  return from.startsWith(home) && (rest === '' || rest.startsWith('/') || rest.startsWith('?')) ? from : home
}
