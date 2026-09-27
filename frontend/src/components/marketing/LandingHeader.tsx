import { Menu, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { cn } from '../../lib/utils'
import { BrandLogo } from '../brand/BrandLogo'
import { AuthAction } from './AuthAction'

const linkClass =
  'inline-flex min-h-11 items-center rounded-md px-3 text-sm font-medium text-slate-700 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-900 motion-reduce:transition-none'

function HeaderLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <Link to={{ pathname: '/', hash: '#how-it-works' }} className={linkClass} onClick={onNavigate}>
        How it works
      </Link>
      <NavLink
        to="/about"
        className={({ isActive }) => cn(linkClass, isActive && 'bg-indigo-50 text-indigo-800')}
        onClick={onNavigate}
      >
        About
      </NavLink>
    </>
  )
}

export function LandingHeader() {
  const [open, setOpen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        toggleRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2 sm:px-6">
        <BrandLogo to="/" />
        <nav aria-label="Main" className="ml-auto hidden items-center gap-1 sm:flex">
          <HeaderLinks />
        </nav>
        <AuthAction className="ml-auto min-h-10 px-4 text-sm sm:ml-2" />
        <button
          ref={toggleRef}
          type="button"
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-md border border-slate-300 sm:hidden"
          aria-expanded={open}
          aria-controls="public-mobile-nav"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X aria-hidden="true" className="h-5 w-5" /> : <Menu aria-hidden="true" className="h-5 w-5" />}
          <span className="sr-only">{open ? 'Close menu' : 'Open menu'}</span>
        </button>
      </div>
      {open && (
        <nav id="public-mobile-nav" aria-label="Main" className="flex flex-col border-t border-slate-200 px-4 py-2 sm:hidden">
          <HeaderLinks onNavigate={() => setOpen(false)} />
        </nav>
      )}
    </header>
  )
}
