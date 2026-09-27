import { Link } from 'react-router-dom'
import { BRAND } from '../../config/brand'
import { cn } from '../../lib/utils'

/** The C mark (decorative; the wordmark text carries the accessible name). */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={cn('h-7 w-7 shrink-0', className)}>
      <rect width="32" height="32" rx="8" className="fill-indigo-700" />
      <path
        d="M21.5 10.2a8 8 0 1 0 0 11.6"
        fill="none"
        strokeWidth="3.4"
        strokeLinecap="round"
        className="stroke-white"
      />
      <circle cx="22.4" cy="16" r="2" className="fill-indigo-200" />
    </svg>
  )
}

type BrandLogoProps = {
  /** Link destination; omit for a plain (non-link) wordmark. */
  to?: string
  className?: string
  onClick?: () => void
}

export function BrandLogo({ to, className, onClick }: BrandLogoProps) {
  const content = (
    <>
      <BrandMark />
      <span className="text-lg font-bold tracking-[0.12em] text-slate-900">{BRAND.name}</span>
    </>
  )
  const classes = cn('inline-flex min-h-11 items-center gap-2 rounded-md', className)
  return to ? (
    <Link to={to} className={classes} onClick={onClick}>
      {content}
    </Link>
  ) : (
    <span className={classes}>{content}</span>
  )
}
