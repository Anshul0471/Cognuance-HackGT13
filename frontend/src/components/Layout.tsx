import { LogOut } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { homePathFor, useAuth } from '../auth/context'
import { BRAND } from '../config/brand'
import { cn } from '../lib/utils'
import { BrandLogo } from './brand/BrandLogo'

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-slate-700 transition-colors duration-150 hover:bg-slate-100 motion-reduce:transition-none',
    isActive && 'bg-indigo-50 text-indigo-800',
  )

/** Authenticated patient shell (also hosts /status and not-found). */
export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)

  const signOut = async () => {
    setSigningOut(true)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <a
        href="#app-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2">
          <BrandLogo to={user ? homePathFor(user.role) : '/'} />
          <nav aria-label="Main" className="flex flex-wrap items-center gap-1">
            {user ? (
              <>
                <NavLink to={homePathFor(user.role)} end className={navClass}>
                  {user.role === 'doctor' ? 'Overview' : 'Check-in'}
                </NavLink>
                <span className="hidden px-2 text-sm text-slate-600 sm:inline">{user.display_name}</span>
                <button
                  type="button"
                  onClick={() => void signOut()}
                  disabled={signingOut}
                  className="inline-flex min-h-11 items-center gap-1 rounded-md px-3 text-sm font-medium hover:bg-slate-100 disabled:opacity-60"
                >
                  <LogOut aria-hidden="true" className="h-4 w-4" />
                  {signingOut ? 'Signing out…' : 'Sign out'}
                </button>
              </>
            ) : (
              <NavLink to="/login" className={navClass}>
                Sign in
              </NavLink>
            )}
          </nav>
        </div>
      </header>
      <main id="app-main" tabIndex={-1} className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 focus:outline-none">
        <Outlet />
      </main>
      <footer className="mx-auto flex w-full max-w-4xl flex-wrap gap-x-4 gap-y-1 px-4 pb-8 text-sm text-slate-500">
        <span>{BRAND.name}</span>
        <NavLink to="/about" className="underline-offset-4 hover:text-slate-800 hover:underline">
          About {BRAND.name}
        </NavLink>
        <NavLink to="/status" className="underline-offset-4 hover:text-slate-800 hover:underline">
          System status
        </NavLink>
      </footer>
    </div>
  )
}
