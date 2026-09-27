import type { AlertEvent } from '../schemas'
import { formatLocal } from '../utils/dateFormatting'
import { ACTION_LABEL, WORKFLOW_LABEL } from '../utils/displayLabels'

/** Append-only review history, oldest first. Notes render as escaped plain text (React default). */
export function AlertEventTimeline({
  events,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  events: AlertEvent[]
  hasMore: boolean
  loadingMore: boolean
  onLoadMore: () => void
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        {events.length} event{events.length === 1 ? '' : 's'} loaded, oldest first
        {hasMore ? '. More events exist and are not shown yet.' : '. This is the complete history.'} Times are in your
        local time zone.
      </p>
      <ol className="space-y-3 border-l-2 border-slate-200 pl-4">
        {events.map((event) => (
          <li key={event.event_id} className="relative">
            <span aria-hidden="true" className="absolute top-1.5 -left-[1.4rem] h-3 w-3 rounded-full border-2 border-white bg-slate-400" />
            <p className="text-sm font-semibold">
              {ACTION_LABEL[event.action]}
              {event.from_status && event.from_status !== event.to_status && (
                <span className="font-normal text-slate-600">
                  {' '}
                  ({WORKFLOW_LABEL[event.from_status]} → {WORKFLOW_LABEL[event.to_status]})
                </span>
              )}
            </p>
            <p className="text-xs text-slate-600">
              {event.actor ? event.actor.display_name : 'System'} · {formatLocal(event.created_at)}
            </p>
            {event.note !== null && (
              <p className="mt-1 rounded-md bg-slate-50 p-2 text-sm whitespace-pre-wrap break-words">{event.note}</p>
            )}
          </li>
        ))}
      </ol>
      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loadingMore}
          className="min-h-11 rounded-md border border-slate-300 bg-white px-4 font-medium hover:bg-slate-50 disabled:opacity-60"
        >
          {loadingMore ? 'Loading…' : 'Load more events'}
        </button>
      )}
    </div>
  )
}
