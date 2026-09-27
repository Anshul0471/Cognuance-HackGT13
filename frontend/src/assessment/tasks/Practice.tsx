import { useState } from 'react'
import type { RunRecorder } from '../recorder'
import type { InputMode, PracticeRecord, RenderProtocol } from '../types'
import { BigButton, Screen } from '../ui'
import { AttentionTask } from './AttentionTask'
import { ReactionTask } from './ReactionTask'

type Step = 'intro' | 'memory' | 'attention' | 'reaction' | 'summary'

export type PracticeProps = {
  protocol: RenderProtocol
  mode: InputMode
  recorder: RunRecorder
  onDone: (record: PracticeRecord) => void
  /** Patient could not use the interaction: offer Stop (discard) or Save partial. */
  onCannotContinue: (record: PracticeRecord, choice: 'stop' | 'save') => void
}

function MemoryEntryExample({ words, onNext }: { words: string[]; onNext: () => void }) {
  const [typed, setTyped] = useState(['', ''])
  const [checked, setChecked] = useState(false)
  const correct = words.every((w) => typed.some((t) => t.trim().toLowerCase() === w))
  return (
    <Screen title="Practice: typing words">
      <p>
        In the word activity you will type words you remember, one per box. Try it with these example words:{' '}
        <strong>{words.join(', ')}</strong>
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {typed.map((value, i) => (
          <label key={i} className="block">
            <span className="text-base font-medium">Word {i + 1}</span>
            <input
              value={value}
              onChange={(event) => {
                const next = [...typed]
                next[i] = event.target.value
                setTyped(next)
                setChecked(false)
              }}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              className="mt-1 w-full rounded-md border-2 border-slate-300 px-3 py-3 text-xl focus:border-indigo-600 focus:outline-none"
            />
          </label>
        ))}
      </div>
      {checked && (
        <p role="status" className="font-medium">
          {correct ? 'That’s it — one word in each box.' : `Type each example word (${words.join(', ')}) in its own box.`}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <BigButton variant="secondary" onClick={() => setChecked(true)}>
          Check
        </BigButton>
        <BigButton onClick={onNext}>Next</BigButton>
      </div>
    </Screen>
  )
}

export function Practice({ protocol, mode, recorder, onDone, onCannotContinue }: PracticeProps) {
  const [step, setStep] = useState<Step>('intro')
  const [repeats, setRepeats] = useState(0)
  const [round, setRound] = useState(0) // remounts task components on repeat
  const practice = protocol.practice

  if (step === 'intro') {
    return (
      <Screen title="Practice">
        <p>Before the real activities, let's practise each one. Practice is not scored.</p>
        <BigButton onClick={() => setStep('memory')}>Start practice</BigButton>
      </Screen>
    )
  }
  if (step === 'memory') {
    return <MemoryEntryExample key={round} words={practice.memory_words} onNext={() => setStep('attention')} />
  }
  if (step === 'attention') {
    return (
      <AttentionTask
        key={round}
        practice
        trials={practice.attention_trials}
        stimulusMs={protocol.attention.stimulus_ms}
        gapMs={protocol.attention.gap_ms}
        mode={mode}
        recorder={recorder}
        maxEventsPerTrial={protocol.limits.max_events_per_trial}
        onFinish={() => setStep('reaction')}
      />
    )
  }
  if (step === 'reaction') {
    return (
      <ReactionTask
        key={round}
        practice
        trials={practice.reaction_foreperiods_ms.map((ms, i) => ({ trial_id: `prt-${i + 1}`, foreperiod_ms: ms }))}
        responseWindowMs={protocol.reaction.response_window_ms}
        intertrialMs={protocol.reaction.intertrial_ms}
        mode={mode}
        recorder={recorder}
        maxEventsPerTrial={protocol.limits.max_events_per_trial}
        onFinish={() => setStep('summary')}
      />
    )
  }

  const record = (completed: boolean): PracticeRecord => ({ completed, repeats })
  return (
    <Screen title="Practice finished">
      <p>Next come the real activities: words, shapes, then GO. You can take short breaks between them.</p>
      <div className="flex flex-wrap gap-3">
        <BigButton onClick={() => onDone(record(true))}>Start the activities</BigButton>
        {repeats < practice.max_repeats && (
          <BigButton
            variant="secondary"
            onClick={() => {
              setRepeats(repeats + 1)
              setRound(round + 1)
              setStep('memory')
            }}
          >
            Practise once more
          </BigButton>
        )}
      </div>
      <details className="rounded-lg border border-slate-300 bg-white p-4">
        <summary className="cursor-pointer font-medium">These activities aren't working for me</summary>
        <p className="mt-3">You can stop now without saving, or save this check-in as unfinished.</p>
        <div className="mt-3 flex flex-wrap gap-3">
          <BigButton variant="secondary" onClick={() => onCannotContinue(record(false), 'save')}>
            Save as unfinished
          </BigButton>
          <BigButton variant="danger" onClick={() => onCannotContinue(record(false), 'stop')}>
            Stop without saving
          </BigButton>
        </div>
      </details>
    </Screen>
  )
}
