import { Link } from 'react-router-dom'
import { BRAND } from '../../config/brand'
import { BrandMark } from '../brand/BrandLogo'

export function LandingFooter() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-8 text-sm text-slate-600 sm:px-6">
        <span className="inline-flex items-center gap-2 font-semibold tracking-[0.12em] text-slate-900">
          <BrandMark className="h-5 w-5" />
          {BRAND.name}
        </span>
        <span>{BRAND.tagline}</span>
        <Link to="/about" className="font-medium text-indigo-800 underline-offset-4 hover:underline sm:ml-auto">
          About {BRAND.name}
        </Link>
      </div>
    </footer>
  )
}
