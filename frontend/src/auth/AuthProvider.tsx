import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, hasAccessToken, setAccessToken, setUnauthorizedHandler, type CurrentUser } from '../lib/api'
import { AuthContext, type AuthState } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [lastSignOut, setLastSignOut] = useState<{ revocationConfirmed: boolean } | null>(null)
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const draftActive = useRef(false)
  const userRef = useRef<CurrentUser | null>(null)
  useEffect(() => {
    userRef.current = user
  }, [user])

  const clearSession = useCallback(() => {
    if (expiryTimer.current) clearTimeout(expiryTimer.current)
    expiryTimer.current = null
    setAccessToken(null)
    setUser(null)
    // Drop cached patient data so the next account never sees it.
    queryClient.clear()
    // Recharts keeps a hidden, page-global text-measurement node holding the last measured label;
    // remove it so nothing from a chart outlives the session (Recharts recreates it on demand).
    document.getElementById('recharts_measurement_span')?.remove()
  }, [queryClient])

  // Sign-out: stop private reads first, try to revoke the server session with the current token, then
  // clear everything locally whatever the outcome. The result says whether revocation was confirmed.
  const logout = useCallback(async () => {
    void queryClient.cancelQueries()
    let revocationConfirmed = true
    if (hasAccessToken()) {
      try {
        await api.logout(typeof AbortSignal.timeout === 'function' ? AbortSignal.timeout(5000) : undefined)
      } catch {
        revocationConfirmed = false
      }
    }
    clearSession()
    setLastSignOut({ revocationConfirmed })
    return { revocationConfirmed }
  }, [clearSession, queryClient])

  // Session ended by expiry/401: keep an in-memory draft recoverable, otherwise clear it locally.
  const sessionEnded = useCallback(() => {
    if (draftActive.current) setAccessToken(null)
    else clearSession()
  }, [clearSession])

  const startTokenTimer = useCallback(
    (expiresIn: number) => {
      if (expiryTimer.current) clearTimeout(expiryTimer.current)
      expiryTimer.current = setTimeout(sessionEnded, expiresIn * 1000)
    },
    [sessionEnded],
  )

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.login(email, password)
      queryClient.clear()
      setAccessToken(result.access_token)
      setUser(result.user)
      setLastSignOut(null)
      startTokenTimer(result.expires_in)
      return result.user
    },
    [queryClient, startTokenTimer],
  )

  const reauthenticate = useCallback(
    async (password: string) => {
      const current = userRef.current
      if (!current) throw new Error('Not signed in')
      const result = await api.login(current.email, password)
      if (result.user.id !== current.id) {
        // Never attach one user's draft to another account.
        void logout()
        throw new Error('Different account')
      }
      setAccessToken(result.access_token)
      startTokenTimer(result.expires_in)
    },
    [logout, startTokenTimer],
  )

  const setDraftActive = useCallback(
    (active: boolean) => {
      draftActive.current = active
      // The token lapsed while a draft was protected and the draft is now gone: end the session.
      if (!active && userRef.current && !hasAccessToken()) void logout()
    },
    [logout],
  )

  useEffect(() => {
    setUnauthorizedHandler(sessionEnded)
    return () => {
      setUnauthorizedHandler(null)
      setAccessToken(null)
      if (expiryTimer.current) clearTimeout(expiryTimer.current)
    }
  }, [sessionEnded])

  const value = useMemo<AuthState>(
    () => ({ user, login, logout, lastSignOut, setDraftActive, reauthenticate }),
    [user, login, logout, lastSignOut, setDraftActive, reauthenticate],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
