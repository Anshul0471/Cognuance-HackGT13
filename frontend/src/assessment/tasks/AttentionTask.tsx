import { Pause } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunRecorder } from '../recorder'
import type { AttentionRecord, AttentionTrialRecord, InputMode, Shape, TimingInterruption } from '../types'
import { addResponse, SHAPE_LABEL, SHAPE_SVG } from '../stimuli'
import { BigButton, Screen, ShapeGlyph } from '../ui'
import { useFrameLoop } from '../useFrameLoop'
import { useLatest } from '../useLatest'
import { useResponseInput } from '../useResponseInput'

type Trial = { trial_id: string; shape: Shape; is_target?: boolean }
type Phase = 'instructions' | 'running' | 'feedback' | 'interrupted' | 'done'

type Current = { rec: AttentionTrialRecord; onsetAbs: number; offsetAbs: number; stage: 'stim' | 'gap' }

export type AttentionTaskProps = {
  trials: Trial[]
  stimulusMs: number
  gapMs: number
  mode: InputMode
  recorder: RunRecorder
  maxEventsPerTrial: number
  /** Practice: explanatory feedback after each trial; results are not scored. */
  practice?: boolean
  onFinish: (result: AttentionRecord) => void
}

const FEEDBACK_MS = 1800

function practiceFeedback(trial: Trial, rec: AttentionTrialRecord, stimulusMs: number): string {
  const pressed = rec.responses.some((r) => r.offset_ms >= rec.onset_ms && r.offset_ms < rec.onset_ms + stimulusMs)
  const name = SHAPE_LABEL[trial.shape].toLowerCase()
  if (trial.shape === 'circle') {
    return pressed ? 'Correct — you pressed for the circle.' : 'That was a circle. Press when you see a circle.'
  }
  return pressed ? `That was a ${name}. Wait when you see a square or triangle.` : `Correct — you waited for the ${name}.`
}

export function AttentionTask({
  trials,
  stimulusMs,
  gapMs,
  mode,
  recorder,
  maxEventsPerTrial,
  practice = false,
  onFinish,
}: AttentionTaskProps) {
  const [phase, setPhase] = useState<Phase>('instructions')
  const [progress, setProgress] = useState(0)
  const [feedback, setFeedback] = useState('')
  const stimulusRef = useRef<HTMLDivElement>(null)
  const records = useRef<AttentionTrialRecord[]>([])
  const current = useRef<Current | null>(null)
  const index = useRef(0)
  const finished = useRef(false)
  const onFinishRef = useLatest(onFinish)
  // Synchronous guard: a frame can fire after a stop/finish but before React re-renders.
  const running = useRef(false)

  const finish = useCallback(
    (completion: 'COMPLETED' | 'STOPPED') => {
      if (finished.current) return
      finished.current = true
      running.current = false
      setPhase('done')
      onFinishRef.current({
        completion,
        trials: records.current.map((t) => ({ ...t, interruptions: t.interruptions.map((i) => ({ ...i })) })),
        end_reason: completion === 'COMPLETED' ? 'FINISHED' : 'STOPPED',
      })
    },
    [onFinishRef],
  )

  const showStimulus = (shape: Shape | null) => {
    const el = stimulusRef.current
    if (!el) return
    el.innerHTML = shape ? SHAPE_SVG[shape] : ''
    el.setAttribute('aria-label', shape ? SHAPE_LABEL[shape] : 'Blank')
  }

  const startTrial = (ts: number) => {
    const spec = trials[index.current]
    showStimulus(spec.shape)
    current.current = {
      rec: {
        trial_id: spec.trial_id,
        onset_ms: recorder.offset(ts),
        offset_ms: null,
        gap_end_ms: null,
        responses: [],
        interruptions: [],
        event_overflow: false,
      },
      onsetAbs: ts,
      offsetAbs: 0,
      stage: 'stim',
    }
    setProgress(index.current + 1)
  }

  useFrameLoop(phase === 'running', (ts) => {
    if (!running.current) return
    const cur = current.current
    if (!cur) {
      startTrial(ts)
      return
    }
    if (cur.stage === 'stim' && ts - cur.onsetAbs >= stimulusMs) {
      showStimulus(null)
      cur.rec.offset_ms = recorder.offset(ts)
      cur.offsetAbs = ts
      cur.stage = 'gap'
    } else if (cur.stage === 'gap' && ts - cur.offsetAbs >= gapMs) {
      cur.rec.gap_end_ms = recorder.offset(ts)
      records.current.push(cur.rec)
      current.current = null
      index.current += 1
      if (practice) {
        running.current = false
        setFeedback(practiceFeedback(trials[index.current - 1], cur.rec, stimulusMs))
        setPhase('feedback')
      } else if (index.current >= trials.length) {
        finish('COMPLETED')
      } else {
        startTrial(ts)
      }
    }
  })

  // Practice feedback pause, then continue or finish.
  useEffect(() => {
    if (phase !== 'feedback') return
    const timer = setTimeout(() => {
      if (index.current >= trials.length) finish('COMPLETED')
      else {
        running.current = true
        setPhase('running')
      }
    }, FEEDBACK_MS)
    return () => clearTimeout(timer)
  }, [phase, trials.length, finish])

  // The interruption stays open on the cut trial until the patient continues.
  const openInterruption = useRef<TimingInterruption | null>(null)

  const interrupt = useCallback((kind: TimingInterruption['kind']) => {
    const cur = current.current
    running.current = false
    if (!cur) {
      if (!finished.current) setPhase('interrupted')
      return
    }
    const now = recorder.offset()
    if (cur.stage === 'stim') cur.rec.offset_ms = now // early stimulus removal is recorded as such
    cur.rec.gap_end_ms = now
    const interruption: TimingInterruption = { kind, start_ms: now, end_ms: null }
    cur.rec.interruptions.push(interruption)
    openInterruption.current = interruption
    records.current.push(cur.rec) // recorded as interrupted, never silently redone
    current.current = null
    index.current += 1
    showStimulus(null)
    setPhase(index.current >= trials.length ? 'done' : 'interrupted')
    if (index.current >= trials.length) finish('COMPLETED')
  }, [recorder, trials.length, finish])

  useEffect(() => {
    if (phase !== 'running') return
    return recorder.onHidden(() => interrupt('HIDDEN'))
  }, [phase, recorder, interrupt])

  const respond = useCallback(
    (timestamp: number) => {
      const t = recorder.offset(timestamp)
      // Attribute the press to the trial whose span contains it (the event may predate this frame).
      const cur = current.current
      const last = records.current[records.current.length - 1]
      const target =
        cur && t >= cur.rec.onset_ms
          ? cur.rec
          : last && last.interruptions.length === 0 && t >= last.onset_ms && t <= (last.gap_end_ms ?? t)
            ? last
            : null
      if (target) addResponse(target, t, maxEventsPerTrial)
    },
    [recorder, maxEventsPerTrial],
  )

  const pointerProps = useResponseInput(mode, phase === 'running', respond, recorder)

  const pause = () => {
    recorder.pause()
    interrupt('PAUSE')
  }

  const resumeAfterInterruption = () => {
    const open = openInterruption.current
    if (open) open.end_ms = Math.max(open.start_ms, recorder.offset())
    openInterruption.current = null
    recorder.resume()
    setPhase('instructions')
  }

  if (phase === 'instructions' || phase === 'interrupted') {
    return (
      <Screen title={practice ? 'Practice: shapes' : phase === 'interrupted' ? 'Paused' : 'Shapes activity'}>
        {phase === 'interrupted' ? (
          <p>
            The activity was paused. You can continue from the next shape (the pause will be noted), or save
            what you have done and stop.
          </p>
        ) : (
          <>
            <p>Press the button only when you see a circle. When you see a square or triangle, wait.</p>
            <p className="flex items-center gap-4" aria-hidden="true">
              <ShapeGlyph shape="circle" /> press
              <ShapeGlyph shape="square" /> <ShapeGlyph shape="triangle" /> wait
            </p>
            <p>
              {mode === 'keyboard' ? 'Press the Space bar to respond.' : 'Tap the large button to respond.'} Each
              shape shows for one second.
            </p>
          </>
        )}
        <div className="flex flex-wrap gap-3">
          <BigButton
            onClick={
              phase === 'interrupted'
                ? resumeAfterInterruption
                : () => {
                    running.current = true
                    setPhase('running')
                  }
            }
          >
            {phase === 'interrupted' ? 'Continue' : 'Ready'}
          </BigButton>
          {phase === 'interrupted' && !practice && (
            <BigButton variant="danger" onClick={() => finish('STOPPED')}>
              Save what I've done and stop
            </BigButton>
          )}
        </div>
      </Screen>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-base text-slate-600">
        <span aria-live="off">
          {practice ? 'Practice' : 'Shapes'}: {progress} of {trials.length}
        </span>
        {!practice && phase === 'running' && (
          <BigButton variant="secondary" onClick={pause} aria-label="Pause">
            <Pause aria-hidden="true" className="h-5 w-5" /> Pause
          </BigButton>
        )}
      </div>
      <div
        {...pointerProps}
        role={mode === 'pointer' ? 'button' : 'region'}
        aria-label={mode === 'pointer' ? 'Response area: tap for circles' : 'Shapes (press Space for circles)'}
        className="flex h-72 touch-none select-none flex-col items-center justify-center rounded-xl border-4 border-slate-300 bg-white"
      >
        <div ref={stimulusRef} role="img" aria-label="Blank" className="flex h-40 items-center justify-center" />
        {phase === 'feedback' && <p className="mt-2 text-center text-lg font-medium">{feedback}</p>}
      </div>
      <p className="text-center text-base text-slate-600">
        {mode === 'keyboard' ? 'Space bar = circle' : 'Tap the box = circle'}
      </p>
    </div>
  )
}
