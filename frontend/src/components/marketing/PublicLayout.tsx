import { Outlet } from 'react-router-dom'
import { LandingFooter } from './LandingFooter'
import { LandingHeader } from './LandingHeader'

/** Shell for public pages (`/`, `/about`). Renders no private data and makes no API calls. */
export function PublicLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-gradient-to-b from-indigo-50/60 via-slate-50 to-slate-50 text-slate-900">
      <a
        href="#public-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to main content
      </a>
      <LandingHeader />
      <main id="public-main" tabIndex={-1} className="flex-1 focus:outline-none">
        <Outlet />
      </main>
      <LandingFooter />
    </div>
  )
}
