import { useId, useState, type ReactNode } from 'react'
import { cn } from '../lib/utils'
import type { AnswerHelp, Assistance, ContextCheckin, ContextField } from './types'
import { BigButton, Screen } from './ui'

type Missing = 'SKIPPED' | 'UNKNOWN'
type Answer<T> = { value: T } | { missing: Missing } | null

function Choice<T extends string | number>({
  legend,
  hint,
  options,
  value,
  onChange,
  children,
}: {
  legend: string
  hint?: string
  options: { value: T; label: string }[]
  value: T | null
  onChange: (value: T) => void
  children?: ReactNode
}) {
  const name = useId()
  return (
    <fieldset className="space-y-2">
      <legend className="text-lg font-semibold">{legend}</legend>
      {hint && <p className="text-base text-slate-600">{hint}</p>}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => (
          <label
            key={String(option.value)}
            className={cn(
              'flex min-h-12 min-w-12 cursor-pointer items-center justify-center rounded-lg border-2 px-4 text-lg font-medium focus-within:ring-4 focus-within:ring-indigo-300',
              value === option.value ? 'border-indigo-700 bg-indigo-50 text-indigo-900' : 'border-slate-300 bg-white',
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
      {children}
    </fieldset>
  )
}

function MissingButtons({ onPick, current }: { onPick: (m: Missing) => void; current: Missing | null }) {
  return (
    <div className="flex flex-wrap gap-2">
      {(['SKIPPED', 'UNKNOWN'] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={current === m}
          onClick={() => onPick(m)}
          className={cn(
            'min-h-11 rounded-lg border-2 px-3 text-base focus:outline-none focus-visible:ring-4 focus-visible:ring-indigo-300',
            current === m ? 'border-slate-700 bg-slate-100' : 'border-slate-300 bg-white',
          )}
        >
          {m === 'SKIPPED' ? 'Skip this question' : "I don't know"}
        </button>
      ))}
    </div>
  )
}

const missingOf = <T,>(a: Answer<T>): Missing | null => (a && 'missing' in a ? a.missing : null)
const valueOf = <T,>(a: Answer<T>): T | null => (a && 'value' in a ? a.value : null)

export type ContextResult = { context: ContextCheckin; assistance: Assistance }

export function ContextCheckinForm({
  firstCheckIn,
  navigationDeclared,
  initial,
  onDone,
}: {
  firstCheckIn: boolean
  navigationDeclared: boolean
  initial?: ContextResult
  onDone: (result: ContextResult) => void
}) {
  const init = initial?.context
  const fromInitial = <T,>(field: ContextField, value: T | null): Answer<T> => {
    if (!init) return null
    const missing = init.missing_fields[field]
    return missing ? { missing } : value === null ? null : { value }
  }
  const [sleepText, setSleepText] = useState(init?.sleep_hours != null ? String(init.sleep_hours) : '')
  const [sleepMissing, setSleepMissing] = useState<Missing | null>(
    missingOf(fromInitial('sleep_hours', init?.sleep_hours ?? null)),
  )
  const [mood, setMood] = useState<Answer<number>>(fromInitial('mood_score', init?.mood_score ?? null))
  // "I don't know" (UNKNOWN) replaces a separate "Not sure" option: the contract is true/false/null.
  const [medication, setMedication] = useState<Answer<boolean>>(
    fromInitial('medication_change', init?.medication_change ?? null),
  )
  const [reportedBy, setReportedBy] = useState<ContextCheckin['reported_by'] | null>(init?.reported_by ?? null)
  const [navigation, setNavigation] = useState<'YES' | 'NO' | null>(
    initial ? (initial.assistance.navigation_help ? 'YES' : 'NO') : navigationDeclared ? 'YES' : null,
  )
  const [contextEntry, setContextEntry] = useState<'YES' | 'NO' | null>(
    initial ? (initial.assistance.context_help ? 'YES' : 'NO') : null,
  )
  const [answers, setAnswers] = useState<Partial<Assistance['answer_help']>>(initial?.assistance.answer_help ?? {})
  const [errors, setErrors] = useState<string[]>([])

  const yesNo = [
    { value: 'YES' as const, label: 'Yes' },
    { value: 'NO' as const, label: 'No' },
  ]
  const helpOptions = [
    { value: 'PROVIDED' as const, label: 'Yes' },
    { value: 'NONE' as const, label: 'No' },
    { value: 'UNKNOWN' as const, label: 'Not sure' },
  ]

  const submit = () => {
    const problems: string[] = []
    let sleep: number | null = null
    if (!sleepMissing) {
      const trimmed = sleepText.trim()
      if (!/^\d{1,2}(\.\d{1,2})?$/.test(trimmed) || Number(trimmed) > 24) {
        problems.push('Sleep: enter hours from 0 to 24 (for example 7 or 7.5), or skip the question.')
      } else {
        sleep = Number(trimmed)
      }
    }
    if (mood === null) problems.push('Mood: choose a number, or skip the question.')
    if (medication === null) problems.push('Medication: choose an answer, or skip the question.')
    if (reportedBy === null) problems.push('Please say who is answering these questions.')
    if (navigation === null || contextEntry === null) problems.push('Please answer the questions about help.')
    if (!answers.memory || !answers.attention || !answers.reaction) {
      problems.push('Please answer whether anyone helped with each activity.')
    }
    setErrors(problems)
    if (problems.length) return

    const missing_fields: ContextCheckin['missing_fields'] = {}
    if (sleepMissing) missing_fields.sleep_hours = sleepMissing
    const moodMissing = missingOf(mood)
    if (moodMissing) missing_fields.mood_score = moodMissing
    const medMissing = missingOf(medication)
    if (medMissing) missing_fields.medication_change = medMissing

    onDone({
      context: {
        sleep_hours: sleep,
        mood_score: valueOf(mood),
        medication_change: valueOf(medication),
        reported_by: reportedBy!,
        missing_fields,
      },
      assistance: {
        navigation_help: navigation === 'YES',
        context_help: contextEntry === 'YES',
        answer_help: answers as Assistance['answer_help'],
      },
    })
  }

  return (
    <Screen title="A few questions about today">
      <p>Answer what you can. You can skip any of the first three questions.</p>

      <fieldset className="space-y-2">
        <legend className="text-lg font-semibold">About how many hours did you sleep last night?</legend>
        <label htmlFor="sleep" className="sr-only">
          Hours of sleep
        </label>
        <input
          id="sleep"
          type="number"
          inputMode="decimal"
          min={0}
          max={24}
          step={0.25}
          value={sleepText}
          disabled={sleepMissing !== null}
          onChange={(event) => setSleepText(event.target.value)}
          className="w-40 rounded-md border-2 border-slate-300 px-3 py-3 text-xl disabled:bg-slate-100"
        />
        <MissingButtons
          current={sleepMissing}
          onPick={(m) => setSleepMissing(sleepMissing === m ? null : m)}
        />
      </fieldset>

      <Choice
          legend="How is your mood today?"
          hint="1 = very low, 10 = very good"
          options={Array.from({ length: 10 }, (_, i) => ({ value: i + 1, label: String(i + 1) }))}
          value={valueOf(mood)}
          onChange={(value) => setMood({ value })}
        >
          <MissingButtons current={missingOf(mood)} onPick={(m) => setMood({ missing: m })} />
        </Choice>

      <Choice
          legend={
            firstCheckIn
              ? 'Has any medication changed in the last seven days?'
              : 'Has any medication changed since your previous check-in?'
          }
          options={[
            { value: 'yes', label: 'Yes' },
            { value: 'no', label: 'No' },
          ]}
          value={valueOf(medication) === null ? null : valueOf(medication) ? 'yes' : 'no'}
          onChange={(value) => setMedication({ value: value === 'yes' })}
        >
          <MissingButtons current={missingOf(medication)} onPick={(m) => setMedication({ missing: m })} />
        </Choice>

      <Choice
        legend="Who is answering these questions?"
        options={[
          { value: 'PATIENT' as const, label: 'Me (the patient)' },
          { value: 'CAREGIVER_ASSISTED' as const, label: 'A caregiver is helping' },
        ]}
        value={reportedBy}
        onChange={setReportedBy}
      />

      <h2 className="pt-2 text-xl font-bold">Help during this check-in</h2>
      <Choice legend="Did anyone help you move between screens?" options={yesNo} value={navigation} onChange={setNavigation} />
      <Choice legend="Did anyone help enter these answers?" options={yesNo} value={contextEntry} onChange={setContextEntry} />
      <Choice
        legend="Did anyone help remember or type the words?"
        options={helpOptions}
        value={answers.memory ?? null}
        onChange={(v: AnswerHelp) => setAnswers({ ...answers, memory: v })}
      />
      <Choice
        legend="Did anyone press the button for you in the shapes activity?"
        options={helpOptions}
        value={answers.attention ?? null}
        onChange={(v: AnswerHelp) => setAnswers({ ...answers, attention: v })}
      />
      <Choice
        legend="Did anyone press the button for you in the GO activity?"
        options={helpOptions}
        value={answers.reaction ?? null}
        onChange={(v: AnswerHelp) => setAnswers({ ...answers, reaction: v })}
      />

      {errors.length > 0 && (
        <ul role="alert" className="list-disc space-y-1 rounded-lg bg-rose-50 p-4 pl-8 text-base text-rose-900">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <BigButton onClick={submit}>Continue</BigButton>
    </Screen>
  )
}
