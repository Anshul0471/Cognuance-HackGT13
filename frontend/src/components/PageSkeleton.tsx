/** Reserved-space placeholder while a route bundle or first page of data loads. */
export function PageSkeleton({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="mx-auto w-full max-w-6xl space-y-4 p-4 md:p-8">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="skeleton h-8 w-56" />
      <div aria-hidden="true" className="grid gap-4 sm:grid-cols-3">
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
        <div className="skeleton h-24" />
      </div>
      <div aria-hidden="true" className="skeleton h-64" />
    </div>
  )
}
