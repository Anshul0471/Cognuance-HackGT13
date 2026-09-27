import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { explanationFacts, type AssessmentDetail, type ExplanationFacts } from '../schemas'
import { FORECAST_FIELD, OBSERVED_FIELD, type ChartDomain } from '../utils/chartSeries'
import { formatInZone } from '../utils/dateFormatting'
import {
  AGGREGATE_METHOD_TEXT,
  AVAILABILITY_HELP,
  CONDITION_TEXT,
  COUNTER_LABEL,
  DOMAIN_LABEL,
  MODEL_KIND_LABEL,
  PURPOSE_LABEL,
  QUALITY_LABEL,
  SOURCE_LABEL,
  TASK_LABEL,
  WORKFLOW_LABEL,
  reasonText,
} from '../utils/displayLabels'
import { formatDifference, formatDomainValue, formatRatio } from '../utils/valueFormatting'
import { AlertWorkflowBadge, AnalysisBadges, QualityBadge } from './Badges'

const DOMAINS: ChartDomain[] = ['memory', 'attention', 'reaction_time_ms']
const TASK_OF: Record<ChartDomain, string> = { memory: 'memory', attention: 'attention', reaction_time_ms: 'reaction' }
const HELP_TEXT: Record<string, string> = { NONE: 'No', PROVIDED: 'Yes', UNKNOWN: 'Not sure' }

type Level = 2 | 3

function Heading({ level, children }: { level: Level; children: ReactNode }) {
  const Tag = level === 2 ? 'h2' : 'h3'
  return <Tag className="text-base font-semibold">{children}</Tag>
}

function Section({ title, level, children }: { title: string; level: Level; children: ReactNode }) {
  return (
    <section className="space-y-2 rounded-lg border border-slate-200 bg-white p-4">
      <Heading level={level}>{title}</Heading>
      {children}
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-4 py-1 sm:grid-cols-[14rem_1fr]">
      <dt className="text-sm text-slate-600">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
    </div>
  )
}

function Reasons({ codes }: { codes: string[] }) {
  if (!codes.length) return null
  return (
    <ul className="list-disc space-y-0.5 pl-5 text-sm">
      {codes.map((code) => (
        <li key={code}>{reasonText(code)}</li>
      ))}
    </ul>
  )
}

function readFacts(detail: AssessmentDetail): ExplanationFacts | null {
  const raw = detail.analysis_details.explanation?.facts
  if (!raw) return null
  const parsed = explanationFacts.safeParse(raw)
  return parsed.success ? parsed.data : null
}

function EvidenceLinks({ ids, patientId }: { ids: string[]; patientId: string }) {
  if (!ids.length) return <span className="text-slate-500">None</span>
  return (
    <ul className="space-y-0.5">
      {ids.map((id) => (
        <li key={id}>
          <Link to={`/doctor/patients/${patientId}/assessments/${id}`} className="font-mono text-xs underline">
            {id}
          </Link>
        </li>
      ))}
    </ul>
  )
}

function TaskResults({ detail, level }: { detail: AssessmentDetail; level: Level }) {
  return (
    <Section title="Task results" level={level}>
      <div className="grid gap-3 md:grid-cols-3">
        {DOMAINS.map((domain) => {
          const task = detail.quality_details.tasks[TASK_OF[domain]]
          return (
            <div key={domain} className="rounded-md border border-slate-200 p-3">
              <p className="text-sm font-medium text-slate-700">{DOMAIN_LABEL[domain]}</p>
              <p className="text-2xl font-bold tabular-nums">
                {formatDomainValue(domain, detail.scores[OBSERVED_FIELD[domain]])}
              </p>
              {task ? (
                <dl className="mt-2 space-y-0.5 text-xs">
                  {Object.entries(task.counters).map(([key, value]) => (
                    <div key={key} className="flex justify-between gap-2">
                      <dt className="text-slate-600">{COUNTER_LABEL[key] ?? key}</dt>
                      <dd className="tabular-nums">{value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="mt-2 text-xs text-slate-500">Score components unavailable.</p>
              )}
            </div>
          )
        })}
      </div>
      <p className="text-xs text-slate-500">
        Memory and attention are points out of 100; reaction time is the median usable response in milliseconds.
        Unavailable means the task produced no score, which is different from zero.
      </p>
    </Section>
  )
}

function DataQuality({ detail, level }: { detail: AssessmentDetail; level: Level }) {
  const q = detail.quality_details
  const help = q.assistance as {
    navigation_help?: boolean
    context_help?: boolean
    answer_help?: Record<string, string>
  }
  return (
    <Section title="Data quality" level={level}>
      <dl>
        <Row label="Overall quality">
          <QualityBadge quality={q.overall} />
        </Row>
        <Row label="Weekly comparison">
          {detail.longitudinal_eligible
            ? 'Eligible: this is the week’s representative check-in.'
            : 'Not eligible: saved and shown, but not used as weekly history or for a deviation comparison.'}{' '}
          ({PURPOSE_LABEL[detail.schedule_purpose]})
        </Row>
        <Row label="Answering method">
          {q.initial_input_mode}
          {q.final_input_mode && q.final_input_mode !== q.initial_input_mode ? ` → ${q.final_input_mode}` : ''}
        </Row>
        <Row label="Declared help">
          Navigation: {help.navigation_help ? 'Yes' : 'No'} · Entering context: {help.context_help ? 'Yes' : 'No'}
          {help.answer_help && (
            <span className="block">
              Answering:{' '}
              {Object.entries(help.answer_help)
                .map(([task, value]) => `${TASK_LABEL[task] ?? task} ${HELP_TEXT[value] ?? value}`)
                .join(' · ')}
            </span>
          )}
        </Row>
        {q.practice_repeated && <Row label="Practice">The practice block was repeated.</Row>}
        {q.comparability_flags.length > 0 && (
          <Row label="Comparability">
            <Reasons codes={q.comparability_flags} />
          </Row>
        )}
      </dl>
      <div className="grid gap-3 md:grid-cols-3">
        {Object.entries(q.tasks).map(([name, task]) => (
          <div key={name} className="rounded-md border border-slate-200 p-3 text-sm">
            <p className="font-medium">{TASK_LABEL[name] ?? name}</p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5">
              <QualityBadge quality={task.status} />
              <span className="text-xs text-slate-600">{task.completion.toLowerCase()}</span>
            </p>
            {task.low_flags.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-semibold">Why it is not reliable</p>
                <Reasons codes={task.low_flags} />
              </div>
            )}
            {task.warnings.length > 0 && (
              <div className="mt-2">
                <p className="text-xs font-semibold">Notes (quality unaffected)</p>
                <Reasons codes={task.warnings} />
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
  )
}

function Comparison({ detail, level }: { detail: AssessmentDetail; level: Level }) {
  const forecast = detail.forecast
  const deviations = detail.analysis_details.domain_deviations
  if (!forecast) {
    return (
      <Section title="Comparison with the stored forecast" level={level}>
        <p className="text-sm">
          No forecast was stored for this check-in, so no comparison was made (see the reasons above). The
          observed results remain valid records.
        </p>
      </Section>
    )
  }
  return (
    <Section title="Comparison with the stored forecast" level={level}>
      <div className="relative overflow-x-auto" role="region" aria-label="Forecast comparison table" tabIndex={0}>
        <table className="min-w-full text-sm">
          <thead className="text-left text-slate-600">
            <tr>
              <th scope="col" className="py-1 pr-4">Domain</th>
              <th scope="col" className="py-1 pr-4">Observed</th>
              <th scope="col" className="py-1 pr-4">Forecast</th>
              <th scope="col" className="py-1 pr-4">Actual − predicted</th>
              <th scope="col" className="py-1 pr-4">Directional worsening (server)</th>
              <th scope="col" className="py-1 pr-4">Typical error scale</th>
              <th scope="col" className="py-1 pr-4">Deviation ratio</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {DOMAINS.map((domain) => {
              const observed = detail.scores[OBSERVED_FIELD[domain]]
              const predicted = forecast[FORECAST_FIELD[domain]]
              const dev = deviations?.[domain]
              return (
                <tr key={domain}>
                  <th scope="row" className="py-1 pr-4 text-left font-medium">
                    {DOMAIN_LABEL[domain]}
                  </th>
                  <td className="py-1 pr-4">{formatDomainValue(domain, observed)}</td>
                  <td className="py-1 pr-4">{formatDomainValue(domain, predicted)}</td>
                  <td className="py-1 pr-4">{observed === null ? 'Unavailable' : formatDifference(domain, observed - predicted)}</td>
                  <td className="py-1 pr-4">{dev ? formatDifference(domain, dev.worsening) : '—'}</td>
                  <td className="py-1 pr-4">{dev ? formatDomainValue(domain, dev.scale) : '—'}</td>
                  <td className="py-1 pr-4 tabular-nums">{dev ? formatRatio(dev.z) : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
        <li>Score differences are in points (not percent). A positive reaction-time difference means slower responses.</li>
        <li>
          “Directional worsening” and the deviation ratio come from the server: lower memory/attention or slower
          reaction counts as worsening; better-than-forecast results count as zero.
        </li>
        <li>Deviation ratios are dimensionless comparisons with typical synthetic forecast error, not probabilities.</li>
        {!deviations && <li>No deviation values were computed for this check-in: {AVAILABILITY_HELP[detail.analysis.availability]}</li>}
      </ul>
    </Section>
  )
}

function contextLine(fact: { current: number | null; history_known_count: number; history_mean: number | null } | undefined, unit: string) {
  if (!fact || fact.history_mean === null || fact.history_known_count === 0) return 'No earlier known values to compare.'
  return `Earlier six weekly check-ins: mean ${formatRatio(fact.history_mean)}${unit} (${fact.history_known_count} known).`
}

function Context({ detail, facts, level }: { detail: AssessmentDetail; facts: ExplanationFacts | null; level: Level }) {
  const ctx = detail.context
  const kind = facts?.model?.kind ?? detail.forecast?.model_kind ?? null
  const usesContext = facts?.model ? facts.model.uses_context : kind === 'GRU'
  const missing = (field: string) => {
    const reason = ctx?.missing_fields[field]
    return reason === 'UNKNOWN' ? 'Unknown (answered “I don’t know”)' : reason === 'SKIPPED' ? 'Not answered (skipped)' : 'Not recorded'
  }
  return (
    <Section title="Recorded context" level={level}>
      {!ctx ? (
        <p className="text-sm">No context check-in was recorded with this assessment.</p>
      ) : (
        <dl>
          <Row label="Sleep last night">
            {ctx.sleep_hours === null ? missing('sleep_hours') : `${formatRatio(ctx.sleep_hours)} hours`}
            {facts?.context?.sleep_hours && (
              <span className="block text-xs text-slate-600">{contextLine(facts.context.sleep_hours, ' h')}</span>
            )}
          </Row>
          <Row label="Mood (1 very low – 10 very good)">
            {ctx.mood_score === null ? missing('mood_score') : `${ctx.mood_score}/10`}
            {facts?.context?.mood_score && (
              <span className="block text-xs text-slate-600">{contextLine(facts.context.mood_score, '')}</span>
            )}
          </Row>
          <Row label="Medication change reported">
            {ctx.medication_change === null ? missing('medication_change') : ctx.medication_change ? 'Yes' : 'No'}
            {facts?.context?.medication_change && (
              <span className="block text-xs text-slate-600">
                Earlier six weekly check-ins: {facts.context.medication_change.history_yes_count} of{' '}
                {facts.context.medication_change.history_known_count} known reports said yes.
              </span>
            )}
          </Row>
          <Row label="Reported by">{ctx.reported_by === 'PATIENT' ? 'Patient' : 'Patient with caregiver help'}</Row>
        </dl>
      )}
      <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
        <li>Context is self-reported (or caregiver-assisted). It is not a verified explanation for a task change.</li>
        {kind &&
          (usesContext ? (
            <li>
              The forecast model ({MODEL_KIND_LABEL[kind] ?? kind}) used sleep, mood and medication reports from the
              earlier check-ins as inputs. This check-in’s own context was recorded afterwards and was not used.
            </li>
          ) : (
            <li>
              The forecast model ({MODEL_KIND_LABEL[kind] ?? kind}) does not use sleep, mood or medication; context
              is shown only for review.
            </li>
          ))}
      </ul>
    </Section>
  )
}

function Explanation({
  detail,
  facts,
  patientId,
  level,
}: {
  detail: AssessmentDetail
  facts: ExplanationFacts | null
  patientId: string
  level: Level
}) {
  const a = detail.analysis_details
  const explanation = a.explanation
  const affected = (facts?.domains_at_or_above_r ?? []).filter((d): d is ChartDomain => d in DOMAIN_LABEL)
  return (
    <Section title="Analysis explanation" level={level}>
      <AnalysisBadges availability={detail.analysis.availability} level={detail.analysis.deviation_level} />
      {explanation ? (
        <>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {explanation.sentences.map((sentence, i) => (
              <li key={i}>{sentence}</li>
            ))}
          </ul>
          <dl>
            <Row label="Domains at or above the threshold">
              {affected.length ? affected.map((d) => DOMAIN_LABEL[d]).join(', ') : 'None'}
            </Row>
            <Row label="Aggregate method">
              {a.aggregate_method ? (AGGREGATE_METHOD_TEXT[a.aggregate_method] ?? a.aggregate_method) : '—'}
              <span className="block text-xs text-slate-600">
                Largest deviation {formatRatio(a.max_deviation)} · aggregate {formatRatio(detail.analysis.aggregate_deviation)}
                {facts?.threshold_r !== undefined && ` · review threshold r = ${formatRatio(facts.threshold_r)}`}
              </span>
            </Row>
            {facts?.conditions_met && facts.conditions_met.length > 0 && (
              <Row label="Rule conditions met">
                <ul className="list-disc pl-5">
                  {facts.conditions_met.map((c) => (
                    <li key={c}>{CONDITION_TEXT[c] ?? `Unrecognized condition (${c})`}</li>
                  ))}
                </ul>
              </Row>
            )}
            <Row label="Repetition">
              {a.persistent_count === null || a.persistent_count === 0
                ? 'No qualifying deviation in this check-in.'
                : a.persistent_count === 1
                  ? 'Isolated: first qualifying deviation in the current weekly sequence.'
                  : `Repeated: qualifying deviation ${a.persistent_count} in consecutive weekly check-ins.`}
              {a.streak_evidence_assessment_ids.length > 0 && (
                <div className="mt-1 text-xs">
                  Earlier check-ins in this sequence:
                  <EvidenceLinks ids={a.streak_evidence_assessment_ids} patientId={patientId} />
                </div>
              )}
            </Row>
          </dl>
          {explanation.caveats.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">
              {explanation.caveats.map((caveat, i) => (
                <li key={i}>{caveat}</li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="text-sm">{AVAILABILITY_HELP[detail.analysis.availability]}</p>
      )}
      {detail.analysis.reason_codes.length > 0 && (
        <div>
          <p className="text-sm font-medium">Reasons recorded by the server</p>
          <Reasons codes={detail.analysis.reason_codes} />
        </div>
      )}
    </Section>
  )
}

/** Per-record provenance (refinement 03 §9): kept here, collapsed, instead of on every chart. */
function RecordDetails({ detail }: { detail: AssessmentDetail }) {
  return (
    <details className="rounded-lg border border-slate-200 bg-white p-4">
      <summary className="cursor-pointer font-semibold">Record details (data provenance)</summary>
      <dl className="mt-2">
        <Row label="Data source">{SOURCE_LABEL[detail.source]}</Row>
        <Row label="Schedule purpose">{PURPOSE_LABEL[detail.schedule_purpose]}</Row>
        <Row label="Assessment ID">
          <span className="font-mono text-xs">{detail.assessment_id}</span>
        </Row>
      </dl>
      <p className="mt-2 text-xs text-slate-600">
        Source labels are explained on{' '}
        <Link to="/about" className="underline">
          About COGNUANCE
        </Link>
        .
      </p>
    </details>
  )
}

function TechnicalDetails({
  detail,
  facts,
  patientId,
  timeZone,
}: {
  detail: AssessmentDetail
  facts: ExplanationFacts | null
  patientId: string
  timeZone: string
}) {
  const a = detail.analysis_details
  const f = detail.forecast
  const when = (iso: string | null | undefined) => (iso ? formatInZone(iso, timeZone) : '—')
  return (
    <details className="rounded-lg border border-slate-200 bg-white p-4">
      <summary className="cursor-pointer font-semibold">Analysis details (versions and provenance)</summary>
      <p className="mt-2 text-xs text-slate-600">
        Recorded with this assessment. These are not necessarily the currently active model or policy.
      </p>
      <dl className="mt-2">
        <Row label="Protocol / scoring">
          {detail.protocol_version} / {detail.scoring_version}
        </Row>
        <Row label="Forecast model">
          {f ? `${MODEL_KIND_LABEL[f.model_kind] ?? f.model_kind} · ${f.model_version}` : 'No forecast stored'}
        </Row>
        <Row label="Anomaly policy">{f?.policy_version ?? a.policy_version ?? '—'}</Row>
        <Row label="Preprocessing">{a.preprocessing_version ?? '—'}</Row>
        <Row label="Forecast issued">{when(f?.issued_at)}</Row>
        <Row label="History cutoff">{when(f?.history_cutoff_at)}</Row>
        <Row label="Observed (saved)">{when(detail.observed_at)}</Row>
        <Row label="Target (weekly slot)">{when(detail.target_at)}</Row>
        <Row label="Analysis computed">{when(a.computed_at)}</Row>
        <Row label="Quality">{QUALITY_LABEL[detail.quality_status]}</Row>
        <Row label="Comparability segment">
          <code className="text-xs">{detail.quality_details.comparability_key || '—'}</code>
        </Row>
        <Row label="Forecast inputs (six earlier check-ins)">
          <EvidenceLinks ids={facts?.forecast?.input_assessment_ids ?? []} patientId={patientId} />
        </Row>
        <Row label="Streak evidence">
          <EvidenceLinks ids={a.streak_evidence_assessment_ids} patientId={patientId} />
        </Row>
        <Row label="Reason codes">
          {detail.analysis.reason_codes.length ? (
            <code className="text-xs">{detail.analysis.reason_codes.join(', ')}</code>
          ) : (
            'None'
          )}
        </Row>
        <Row label="IDs">
          <span className="font-mono text-xs">
            assessment {detail.assessment_id}
            {f && <span className="block">forecast {f.forecast_id}</span>}
            {facts?.forecast?.feature_sha256 && <span className="block">features sha256 {facts.forecast.feature_sha256}</span>}
          </span>
        </Row>
      </dl>
    </details>
  )
}

/** Everything the server recorded for one assessment, in separate sections (guide 06 §8). */
export function AssessmentEvidence({
  detail,
  patientId,
  timeZone,
  level = 2,
}: {
  detail: AssessmentDetail
  patientId: string
  timeZone: string
  level?: Level
}) {
  const facts = readFacts(detail)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-700">
        <span>Observed {formatInZone(detail.observed_at, timeZone)}</span>
        <span>Target {formatInZone(detail.target_at, timeZone)}</span>
        <span>{PURPOSE_LABEL[detail.schedule_purpose]}</span>
        {detail.alert && (
          <Link
            to={`/doctor/alerts/${detail.alert.alert_id}`}
            aria-label={`Open review (status ${WORKFLOW_LABEL[detail.alert.workflow_status]})`}
            className="inline-flex items-center gap-1 underline"
          >
            <AlertWorkflowBadge status={detail.alert.workflow_status} />
            Open review
          </Link>
        )}
      </div>
      <Explanation detail={detail} facts={facts} patientId={patientId} level={level} />
      <Comparison detail={detail} level={level} />
      <TaskResults detail={detail} level={level} />
      <DataQuality detail={detail} level={level} />
      <Context detail={detail} facts={facts} level={level} />
      <RecordDetails detail={detail} />
      <TechnicalDetails detail={detail} facts={facts} patientId={patientId} timeZone={timeZone} />
    </div>
  )
}
