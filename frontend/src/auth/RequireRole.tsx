import { Navigate, Outlet, useLocation } from 'react-router-dom'
import type { UserRole } from '../lib/api'
import { homePathFor, useAuth } from './context'

/**
 * Client-side routing guard for UX only. The backend enforces every permission independently;
 * hiding a route here is not authorization.
 */
export function RequireRole({ role }: { role: UserRole }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (user.role !== role) return <Navigate to={homePathFor(user.role)} replace />
  return <Outlet />
}
