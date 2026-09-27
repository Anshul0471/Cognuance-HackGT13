import { CircleCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Receipt } from './types'
import { Screen } from './ui'

// The server composes calm, patient-facing messages; no scores, categories or thresholds appear here.
export function ReceiptView({ receipt }: { receipt: Receipt }) {
  const saved = new Date(receipt.received_at).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  const { quality, analysis } = receipt
  return (
    <Screen title="Check-in saved">
      <p className="flex items-center gap-2 text-xl font-semibold text-emerald-900">
        <CircleCheck aria-hidden="true" className="h-7 w-7" />
        Saved on {saved}. Thank you.
      </p>
      {quality.status !== 'VALID' && (
        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <p className="font-medium">{quality.message}</p>
        </div>
      )}
      {analysis.availability === 'COMPLETE' ? (
        <p className="text-base text-slate-700">
          This check-in was compared with your earlier weekly check-ins. Your care team can see the details.
        </p>
      ) : (
        <div className="rounded-lg border border-slate-300 bg-white p-4">
          <p className="font-medium">About comparing with earlier check-ins</p>
          <p className="mt-2">{analysis.message}</p>
        </div>
      )}
      <p className="text-base text-slate-600">
        These activities record changes over time. They are not a diagnosis. Your care team can review your
        check-ins.
      </p>
      <Link to="/patient" className="text-lg font-semibold text-indigo-800 underline">
        Back to home
      </Link>
    </Screen>
  )
}
