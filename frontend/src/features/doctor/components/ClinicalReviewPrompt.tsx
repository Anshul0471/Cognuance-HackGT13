import { ClipboardCheck, Stethoscope } from 'lucide-react'
import type { WorkflowStatus } from '../schemas'

/**
 * Dedicated clinician review prompt for a persisted anomaly alert (guide 07 §4.7). It asks for a
 * clinical review; it is not a test order, diagnosis, prescription or emergency escalation, and
 * acknowledging/resolving never records that any test was ordered. The backend's deviation
 * category stays visible separately in the alert header.
 */
export function ClinicalReviewPrompt({ status }: { status: WorkflowStatus }) {
  if (status === 'RESOLVED') {
    return (
      <section
        aria-labelledby="review-prompt-heading"
        className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-slate-700"
      >
        <ClipboardCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />
        <div>
          <h2 id="review-prompt-heading" className="font-semibold text-slate-900">
            Clinical review completed
          </h2>
          <p className="mt-1 text-sm">
            This alert was resolved. Its original evidence stays available below for reference.
          </p>
        </div>
      </section>
    )
  }
  return (
    <section
      aria-labelledby="review-prompt-heading"
      className="flex gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950"
    >
      <Stethoscope aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
      <div className="space-y-1">
        <h2 id="review-prompt-heading" className="font-semibold">
          Unexpected performance change — clinical review requested
        </h2>
        <p className="text-sm">
          Review the affected measurements and recent history. Assess whether follow-up evaluation or additional
          testing is appropriate.
        </p>
        <p className="text-xs text-amber-900">
          {status === 'ACKNOWLEDGED' ? 'Acknowledged, still unresolved. ' : ''}
          This is a request for review — not a diagnosis, a test order or an emergency escalation. Recording a
          review action does not mean any test was ordered.
        </p>
      </div>
    </section>
  )
}
