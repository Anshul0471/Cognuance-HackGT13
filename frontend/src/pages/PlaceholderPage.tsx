import { Construction } from 'lucide-react'

export function PlaceholderPage({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center">
      <Construction aria-hidden="true" className="mx-auto h-8 w-8 text-amber-500" />
      <h1 className="mt-3 text-xl font-bold">{title}</h1>
      <p className="mt-2 text-slate-600">{description}</p>
    </div>
  )
}

export function NotFoundPage() {
  return <PlaceholderPage title="Page not found" description="This route does not exist." />
}
