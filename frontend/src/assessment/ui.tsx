import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../lib/utils'
import { SHAPE_LABEL, SHAPE_SVG } from './stimuli'
import type { Shape } from './types'

export function BigButton({
  variant = 'primary',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' }) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex min-h-12 min-w-12 items-center justify-center gap-2 rounded-lg px-5 py-3 text-lg font-semibold focus:outline-none focus-visible:ring-4 focus-visible:ring-indigo-300 disabled:opacity-60',
        variant === 'primary' && 'bg-indigo-700 text-white hover:bg-indigo-800',
        variant === 'secondary' && 'border-2 border-slate-400 bg-white text-slate-900 hover:bg-slate-100',
        variant === 'danger' && 'border-2 border-rose-700 bg-white text-rose-800 hover:bg-rose-50',
        className,
      )}
      {...props}
    />
  )
}

export function Screen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-labelledby="screen-title" className="space-y-5">
      <h1 id="screen-title" className="text-2xl font-bold sm:text-3xl" tabIndex={-1}>
        {title}
      </h1>
      <div className="space-y-5 text-lg leading-relaxed">{children}</div>
    </section>
  )
}

export function ShapeGlyph({ shape, size = 64 }: { shape: Shape; size?: number }) {
  return (
    <span
      role="img"
      aria-label={SHAPE_LABEL[shape]}
      className="inline-block"
      style={{ width: size, height: size }}
      dangerouslySetInnerHTML={{ __html: SHAPE_SVG[shape].replace(/width="160" height="160"/, `width="${size}" height="${size}"`) }}
    />
  )
}
