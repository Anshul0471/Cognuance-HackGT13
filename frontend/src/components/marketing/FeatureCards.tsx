import { ClipboardCheck, LineChart, MessagesSquare } from 'lucide-react'

const FEATURES = [
  { icon: ClipboardCheck, title: 'Focused assessments', body: 'Short activities for memory, attention, and reaction time.' },
  {
    icon: LineChart,
    title: 'Clear visual insights',
    body: 'Explore task results and recorded context through complementary charts.',
  },
  {
    icon: MessagesSquare,
    title: 'Connected review',
    body: 'Keep flagged changes and the doctor’s review history in one place.',
  },
]

export function FeatureCards() {
  return (
    <section aria-labelledby="features-heading" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
      <h2 id="features-heading" className="sr-only">
        Features
      </h2>
      <ul className="grid gap-5 md:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <li key={title} className="surface-card p-6">
            <Icon aria-hidden="true" className="h-6 w-6 text-indigo-700" />
            <h3 className="mt-4 font-semibold text-slate-900">{title}</h3>
            <p className="mt-1 text-slate-600">{body}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
