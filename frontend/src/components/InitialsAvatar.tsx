import { cn } from '../lib/utils'

/** Decorative initials tile (no photos). The name itself is always rendered as text next to it. */
export function InitialsAvatar({ name, className }: { name: string; className?: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-xs font-semibold text-indigo-700',
        className,
      )}
    >
      {initials}
    </span>
  )
}
