import { BarChart3, Bell, Info, LayoutDashboard, LogOut, Menu, Users, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../../auth/context'
import { BrandLogo } from '../../../components/brand/BrandLogo'
import { BRAND } from '../../../config/brand'
import { cn } from '../../../lib/utils'
import { useDocumentTitle } from '../../../lib/useDocumentTitle'
import { useDoctorSummary } from '../queries'

function sectionTitle(pathname: string): string {
  if (/^\/doctor\/patients\/[^/]+\/assessments\//.test(pathname)) return 'Assessment detail'
  if (/^\/doctor\/patients\/[^/]+/.test(pathname)) return 'Assessment history'
  if (pathname.startsWith('/doctor/patients')) return 'Patients'
  if (/^\/doctor\/alerts\/[^/]+/.test(pathname)) return 'Alert review'
  if (pathname.startsWith('/doctor/alerts')) return 'Alerts'
  if (pathname.startsWith('/doctor/insights')) return 'Visual Insights'
  return /^\/doctor\/?$/.test(pathname) ? 'Overview' : 'Page not found'
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-slate-700 transition-colors duration-150 hover:bg-slate-100 motion-reduce:transition-none',
    isActive && 'bg-indigo-50 font-semibold text-indigo-800 shadow-[inset_3px_0_0_var(--color-indigo-600)]',
  )

function NavItems({ unresolved, onNavigate }: { unresolved: number | null; onNavigate?: () => void }) {
  return (
    <ul className="space-y-1">
      <li>
        <NavLink to="/doctor" end className={linkClass} onClick={onNavigate}>
          <LayoutDashboard aria-hidden="true" className="h-4 w-4" />
          Overview
        </NavLink>
      </li>
      <li>
        <NavLink to="/doctor/patients" className={linkClass} onClick={onNavigate}>
          <Users aria-hidden="true" className="h-4 w-4" />
          Patients
        </NavLink>
      </li>
      <li>
        <NavLink to="/doctor/insights" className={linkClass} onClick={onNavigate}>
          <BarChart3 aria-hidden="true" className="h-4 w-4" />
          Visual Insights
        </NavLink>
      </li>
      <li>
        <NavLink to="/doctor/alerts" className={linkClass} onClick={onNavigate}>
          <Bell aria-hidden="true" className="h-4 w-4" />
          Alerts
          {unresolved !== null && unresolved > 0 && (
            <span className="ml-auto rounded-full bg-amber-100 px-2 text-xs font-semibold text-amber-900">
              {unresolved} unresolved
            </span>
          )}
        </NavLink>
      </li>
      <li className="mt-2 border-t border-slate-200 pt-2">
        <NavLink to="/about" className={linkClass} onClick={onNavigate}>
          <Info aria-hidden="true" className="h-4 w-4" />
          About {BRAND.name}
        </NavLink>
      </li>
    </ul>
  )
}

export function DoctorLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // The menu belongs to the path it was opened on, so any navigation closes it.
  const [menuPath, setMenuPath] = useState<string | null>(null)
  const menuOpen = menuPath === pathname
  const setMenuOpen = (open: boolean) => setMenuPath(open ? pathname : null)
  const [signingOut, setSigningOut] = useState(false)
  const summary = useDoctorSummary()
  const unresolved = summary.data ? summary.data.open_alert_count + summary.data.acknowledged_alert_count : null
  const title = sectionTitle(pathname)

  const toggleRef = useRef<HTMLButtonElement>(null)
  useDocumentTitle(title)

  // Escape closes the mobile menu and returns focus to its button.
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setMenuPath(null)
      toggleRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const signOut = async () => {
    setSigningOut(true)
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <a
        href="#doctor-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <BrandLogo to="/doctor" />
          <span aria-hidden="true" className="hidden text-slate-300 sm:inline">
            /
          </span>
          <span className="font-medium text-slate-700">{title}</span>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-sm text-slate-600 md:inline">{user?.display_name}</span>
            <button
              type="button"
              onClick={() => void signOut()}
              disabled={signingOut}
              className="inline-flex min-h-11 items-center gap-1 rounded-md px-3 text-sm font-medium hover:bg-slate-100 disabled:opacity-60"
            >
              <LogOut aria-hidden="true" className="h-4 w-4" />
              {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
            <button
              ref={toggleRef}
              type="button"
              className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-slate-300 md:hidden"
              aria-expanded={menuOpen}
              aria-controls="doctor-mobile-nav"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X aria-hidden="true" className="h-5 w-5" /> : <Menu aria-hidden="true" className="h-5 w-5" />}
              <span className="sr-only">{menuOpen ? 'Close menu' : 'Open menu'}</span>
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="doctor-mobile-nav" aria-label="Doctor" className="border-t border-slate-200 px-4 py-2 md:hidden">
            <p className="px-3 pb-1 text-sm text-slate-600">{user?.display_name}</p>
            <NavItems unresolved={unresolved} onNavigate={() => setMenuOpen(false)} />
          </nav>
        )}
      </header>
      <div className="flex">
        <nav aria-label="Doctor" className="hidden w-60 shrink-0 border-r border-slate-200 bg-white p-3 md:block">
          <NavItems unresolved={unresolved} />
        </nav>
        <main id="doctor-main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 md:px-8">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>
      <footer className="px-4 pb-6 text-xs text-slate-500 md:pl-64">
        Flags request human review; they are not diagnoses, disease stages, emergency classifications or treatment
        recommendations.
      </footer>
    </div>
  )
}
