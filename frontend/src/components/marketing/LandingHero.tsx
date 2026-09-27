import { Brain, Shapes, Timer } from 'lucide-react'
import { BRAND } from '../../config/brand'
import { AuthAction } from './AuthAction'

const TASKS = [
  { icon: Brain, label: 'Memory', note: 'Recall a short list of words' },
  { icon: Shapes, label: 'Attention', note: 'Respond only to the target shape' },
  { icon: Timer, label: 'Reaction time', note: 'Respond when the signal appears' },
]

/** Calm abstract visual: labelled task icons over decorative lines. No scores, no patient data. */
function HeroVisual() {
  return (
    <div className="relative mx-auto w-full max-w-md">
      <svg viewBox="0 0 400 320" aria-hidden="true" focusable="false" className="absolute inset-0 h-full w-full">
        <circle cx="320" cy="60" r="90" className="fill-indigo-100/70" />
        <circle cx="70" cy="270" r="70" className="fill-violet-100/70" />
        <path
          d="M20 220 C 90 180, 140 250, 210 190 S 330 150, 390 110"
          fill="none"
          strokeWidth="2"
          strokeDasharray="4 8"
          strokeLinecap="round"
          className="stroke-indigo-300"
        />
      </svg>
      <ul className="relative space-y-3 p-6 sm:p-8">
        {TASKS.map(({ icon: Icon, label, note }) => (
          <li key={label} className="surface-card flex items-center gap-4 p-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
              <Icon aria-hidden="true" className="h-5 w-5" />
            </span>
            <span>
              <span className="block font-semibold text-slate-900">{label}</span>
              <span className="block text-sm text-slate-600">{note}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function LandingHero() {
  return (
    <section aria-labelledby="hero-heading" className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:px-6 md:grid-cols-2 md:py-20">
      <div>
        <p className="text-sm font-semibold tracking-wide text-indigo-700">Welcome to {BRAND.name}</p>
        <h1 id="hero-heading" className="mt-3 text-4xl font-bold tracking-tight text-balance text-slate-900 sm:text-5xl">
          {BRAND.tagline}
        </h1>
        <p className="mt-5 max-w-xl text-lg text-slate-600">
          Complete short memory, attention, and reaction-time activities. Explore changes over time and bring the
          results together in a clear view for doctor review.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <AuthAction />
          <a href="#how-it-works" className="btn-secondary">
            How it works
          </a>
        </div>
      </div>
      <HeroVisual />
    </section>
  )
}
