import type { CognitiveIndex, CognitiveIndexMetadata } from '../schemas'
import { SCORE_CAVEATS, formulaSummary } from '../utils/cognitiveScore'
import { formatDomainValue, formatIndex } from '../utils/valueFormatting'

/** "How this is calculated": formula, the selected check-in's components, weights and version. */
export function CognitiveScoreExplanation({
  meta,
  index,
  reactionTimeMs,
}: {
  meta: CognitiveIndexMetadata
  index: CognitiveIndex | null
  reactionTimeMs?: number | null
}) {
  const components = index?.observed_components ?? null
  const weight = meta.weights.memory ?? 1 / 3
  return (
    <details className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">How this is calculated</summary>
      <p className="mt-2">{formulaSummary(meta)}</p>
      {components ? (
        <dl className="mt-2 grid gap-x-4 gap-y-1 sm:grid-cols-2">
          <div className="flex justify-between gap-2">
            <dt className="text-slate-600">Memory</dt>
            <dd className="tabular-nums">{formatDomainValue('memory', components.memory)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-slate-600">Attention</dt>
            <dd className="tabular-nums">{formatDomainValue('attention', components.attention)}</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-slate-600">
              Response speed{reactionTimeMs != null && ` (from ${Math.round(reactionTimeMs)} ms)`}
            </dt>
            <dd className="tabular-nums">{components.response_speed.toFixed(1)} / 100</dd>
          </div>
          <div className="flex justify-between gap-2">
            <dt className="text-slate-600">Cognitive Score</dt>
            <dd className="tabular-nums font-semibold">{formatIndex(index?.observed_value)}</dd>
          </div>
        </dl>
      ) : (
        <p className="mt-2 text-slate-600">
          No component values for this check-in, so no composite is shown.
        </p>
      )}
      <p className="mt-2 text-xs text-slate-600">
        Weights: memory {weight.toFixed(3)}, attention {weight.toFixed(3)}, response speed {weight.toFixed(3)} ·
        score version {meta.version} · task versions {meta.supported_protocol_versions.join(', ')} /{' '}
        {meta.supported_scoring_versions.join(', ')}
      </p>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-600">
        {SCORE_CAVEATS.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </details>
  )
}
