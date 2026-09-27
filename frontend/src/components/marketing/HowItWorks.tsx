const STEPS = [
  {
    title: 'Complete an assessment',
    body: 'Record memory, attention, and response speed through short activities.',
  },
  {
    title: 'Explore changes',
    body: 'View results, the combined Cognitive Score, and supporting context over time.',
  },
  {
    title: 'Review together',
    body: 'Give the assigned doctor a clear record of results and flagged changes to review.',
  },
]

export function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-heading" className="border-y border-slate-200 bg-white">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 id="how-heading" className="text-2xl font-bold tracking-tight sm:text-3xl">
          How it works
        </h2>
        <ol className="mt-8 grid gap-6 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-4">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-700 text-sm font-bold text-white"
              >
                {index + 1}
              </span>
              <div>
                <h3 className="font-semibold text-slate-900">{step.title}</h3>
                <p className="mt-1 text-slate-600">{step.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}
