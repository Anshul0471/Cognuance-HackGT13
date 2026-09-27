import { ArrowRight, LogIn } from 'lucide-react'
import { Link } from 'react-router-dom'
import { homePathFor, useAuth } from '../../auth/context'
import { cn } from '../../lib/utils'

/**
 * Primary public action: Sign in, or Open dashboard for an already signed-in visitor (role from the
 * backend's login response, never from the URL). The in-memory session is known synchronously, so
 * there is no "resolving" state that could flash private content.
 */
export function AuthAction({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const { user } = useAuth()
  return user ? (
    <Link to={homePathFor(user.role)} className={cn('btn-primary', className)} onClick={onNavigate}>
      Open dashboard
      <ArrowRight aria-hidden="true" className="h-4 w-4" />
    </Link>
  ) : (
    <Link to="/login" className={cn('btn-primary', className)} onClick={onNavigate}>
      <LogIn aria-hidden="true" className="h-4 w-4" />
      Sign in
    </Link>
  )
}
