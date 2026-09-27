import { Link } from 'react-router-dom'
import { BRAND } from '../config/brand'
import { useDocumentTitle } from '../lib/useDocumentTitle'

/** The one consolidated prototype / data disclosure (refinement 02 §5). */
export const PROTOTYPE_DISCLOSURE =
  'COGNUANCE is a research prototype. The current presentation uses synthetic patient records and simulated histories. Its activities, Cognitive Score, and change flags are exploratory and have not been clinically validated. They are not a diagnosis or a substitute for clinical assessment.'

const SOURCES = [
  {
    label: 'Interactive assessment',
    text: 'Task responses recorded in this app. This describes how the responses were collected; it does not mean the account belongs to a verified real patient.',
  },
  { label: 'Synthetic history', text: 'Generated earlier weekly results used to give each presentation account a history.' },
  { label: 'Simulated scenario', text: 'Fictional weekly histories replayed in date order through the app’s own forecast, comparison, and review rules to demonstrate the workflow.' },
]

export function AboutPage() {
  useDocumentTitle('About')
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight">About {BRAND.name}</h1>
      <p className="mt-2 text-lg text-slate-600">{BRAND.tagline}</p>

      <section aria-labelledby="disclosure-heading" className="surface-card mt-8 border-indigo-200 bg-indigo-50/60 p-6">
        <h2 id="disclosure-heading" className="text-lg font-semibold">
          Prototype and data
        </h2>
        <p className="mt-2 text-slate-800">{PROTOTYPE_DISCLOSURE}</p>
      </section>

      <section aria-labelledby="what-heading" className="mt-10">
        <h2 id="what-heading" className="text-xl font-semibold">
          What it does
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-6 text-slate-700">
          <li>Patients complete a short weekly check-in: a word-memory activity, a shape-attention activity, a reaction-time activity, and a few context questions (sleep, mood, medication changes).</li>
          <li>Each new result is compared with a forecast built from that person’s own earlier weekly results. Unusual changes are flagged for the assigned doctor to review.</li>
          <li>Doctors see task results over time, a combined Cognitive Score for orientation, Visual Insights charts, and the review history of each flag.</li>
          <li>Patients do not see scores, flags, or doctor notes.</li>
        </ul>
      </section>

      <section aria-labelledby="not-heading" className="mt-10">
        <h2 id="not-heading" className="text-xl font-semibold">
          What it is not
        </h2>
        <ul className="mt-3 list-disc space-y-2 pl-6 text-slate-700">
          <li>It does not diagnose, stage, or treat any condition, and flags are not clinical cutoffs.</li>
          <li>It is not monitored in real time and is not an emergency service.</li>
        </ul>
      </section>

      <section aria-labelledby="sources-heading" className="mt-10">
        <h2 id="sources-heading" className="text-xl font-semibold">
          Record sources
        </h2>
        <p className="mt-2 text-slate-700">Each assessment keeps a source label in its details and chart tooltips:</p>
        <dl className="mt-3 space-y-3">
          {SOURCES.map((source) => (
            <div key={source.label}>
              <dt className="font-semibold text-slate-900">{source.label}</dt>
              <dd className="text-slate-700">{source.text}</dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="mt-12 flex flex-wrap gap-3">
        <Link to="/" className="btn-secondary">
          Back to home
        </Link>
      </div>
    </article>
  )
}
