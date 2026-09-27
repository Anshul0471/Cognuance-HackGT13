import { Pause } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunRecorder } from '../recorder'
import type { InputMode, ReactionRecord, ReactionTrialRecord, TimingInterruption } from '../types'
import { addResponse } from '../stimuli'
import { BigButton, Screen } from '../ui'
import { useFrameLoop } from '../useFrameLoop'
import { useLatest } from '../useLatest'
import { useResponseInput } from '../useResponseInput'

type Trial = { trial_id: string; foreperiod_ms: number }
type Phase = 'instructions' | 'running' | 'interrupted' | 'done'
type Stage = 'wait' | 'go' | 'iti'

type Current = { rec: ReactionTrialRecord; waitAbs: number; goAbs: number; lastFrameAbs: number; maxGap: number }

export type ReactionTaskProps = {
  trials: Trial[]
  responseWindowMs: number
  intertrialMs: number
  mode: InputMode
  recorder: RunRecorder
  maxEventsPerTrial: number
  practice?: boolean
  onFinish: (result: ReactionRecord) => void
}

const PRACTICE_FEEDBACK_MS = 1800

// Waiting and GO differ in text and shape, not colour alone.
const WAIT_HTML =
  '<div class="flex flex-col items-center gap-3"><svg viewBox="0 0 100 100" width="120" height="120" aria-hidden="true"><rect x="12" y="12" width="76" height="76" fill="none" stroke="#475569" stroke-width="8"/></svg><span class="text-3xl font-semibold text-slate-600">Wait…</span></div>'
const GO_HTML =
  '<div class="flex flex-col items-center gap-3"><svg viewBox="0 0 100 100" width="120" height="120" aria-hidden="true"><circle cx="50" cy="50" r="44" fill="#1e293b"/></svg><span class="text-5xl font-black tracking-wide">GO!</span></div>'

export function ReactionTask({
  trials,
  responseWindowMs,
  intertrialMs,
  mode,
  recorder,
  maxEventsPerTrial,
  practice = false,
  onFinish,
}: ReactionTaskProps) {
  const [phase, setPhase] = useState<Phase>('instructions')
  const [progress, setProgress] = useState(0)
  const [feedback, setFeedback] = useState('')
  const stimulusRef = useRef<HTMLDivElement>(null)
  const records = useRef<ReactionTrialRecord[]>([])
  const current = useRef<Current | null>(null)
  const stage = useRef<Stage>('iti')
  const itiEnds = useRef(0)
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

  const show = useCallback((html: string, label: string) => {
    const el = stimulusRef.current
    if (!el) return
    el.innerHTML = html
    el.setAttribute('aria-label', label)
  }, [])

  const endTrial = useCallback((reason: ReactionTrialRecord['end_reason'], endOffset: number, now: number) => {
    const cur = current.current
    if (!cur) return
    const rec = cur.rec
    rec.end_ms = Math.max(endOffset, rec.go_onset_ms ?? rec.wait_start_ms)
    rec.end_reason = reason
    // Largest gap between animation frames during the trial: evidence of throttling/jank.
    rec.max_frame_gap_ms = Math.round(cur.maxGap * 1000) / 1000
    records.current.push(rec)
    current.current = null
    index.current += 1
    show('', 'Blank')
    stage.current = 'iti'
    let pause = intertrialMs
    if (practice) {
      setFeedback(
        reason === 'FALSE_START'
          ? 'That was before GO. Wait for GO, then press.'
          : reason === 'TIMEOUT'
            ? 'GO appeared — press as soon as you see it.'
            : 'Good — you pressed after GO.',
      )
      pause = PRACTICE_FEEDBACK_MS
    }
    itiEnds.current = now + pause
  }, [intertrialMs, practice, show])

  useFrameLoop(phase === 'running', (ts) => {
    if (!running.current) return
    const cur = current.current
    if (cur) {
      cur.maxGap = Math.max(cur.maxGap, ts - cur.lastFrameAbs)
      cur.lastFrameAbs = ts
    }
    if (stage.current === 'iti') {
      if (ts < itiEnds.current) return
      // The pause after a trial ended: stamp it on that trial.
      const previous = records.current[records.current.length - 1]
      if (previous && previous.intertrial_end_ms === null && previous.end_reason !== 'INTERRUPTED') {
        previous.intertrial_end_ms = Math.max(previous.end_ms, recorder.offset(ts))
      }
      setFeedback('')
      if (index.current >= trials.length) {
        finish('COMPLETED')
        return
      }
      const spec = trials[index.current]
      show(WAIT_HTML, 'Wait')
      current.current = {
        rec: {
          trial_id: spec.trial_id,
          wait_start_ms: recorder.offset(ts),
          go_onset_ms: null,
          end_ms: 0,
          intertrial_end_ms: null,
          responses: [],
          end_reason: 'TIMEOUT',
          interruptions: [],
          max_frame_gap_ms: null,
          event_overflow: false,
        },
        waitAbs: ts,
        goAbs: 0,
        lastFrameAbs: ts,
        maxGap: 0,
      }
      stage.current = 'wait'
      setProgress(index.current + 1)
    } else if (cur && stage.current === 'wait' && ts - cur.waitAbs >= trials[index.current].foreperiod_ms) {
      show(GO_HTML, 'GO')
      cur.rec.go_onset_ms = recorder.offset(ts)
      cur.goAbs = ts
      stage.current = 'go'
    } else if (cur && stage.current === 'go' && ts - cur.goAbs >= responseWindowMs) {
      endTrial('TIMEOUT', recorder.offset(ts), ts)
    }
  })

  const respond = useCallback(
    (timestamp: number) => {
      const cur = current.current
      if (!running.current || !cur || stage.current === 'iti') return
      const t = recorder.offset(timestamp)
      if (t < cur.rec.wait_start_ms) return
      if (!addResponse(cur.rec, t, maxEventsPerTrial)) return
      // A press before GO is a false start and ends the trial (it is not restarted).
      endTrial(stage.current === 'wait' ? 'FALSE_START' : 'RESPONSE', t, performance.now())
    },
    [recorder, maxEventsPerTrial, endTrial],
  )

  const openInterruption = useRef<TimingInterruption | null>(null)

  const interrupt = useCallback((kind: TimingInterruption['kind']) => {
    running.current = false
    if (current.current) {
      const interruption: TimingInterruption = { kind, start_ms: recorder.offset(), end_ms: null }
      current.current.rec.interruptions.push(interruption)
      openInterruption.current = interruption
      endTrial('INTERRUPTED', recorder.offset(), performance.now())
    }
    show('', 'Blank')
    if (index.current >= trials.length) {
      finish('COMPLETED')
    } else {
      setPhase('interrupted')
    }
  }, [recorder, trials.length, finish, endTrial, show])

  useEffect(() => {
    if (phase !== 'running') return
    return recorder.onHidden(() => interrupt('HIDDEN'))
  }, [phase, recorder, interrupt])

  const pointerProps = useResponseInput(mode, phase === 'running', respond, recorder)

  if (phase === 'instructions' || phase === 'interrupted') {
    return (
      <Screen title={practice ? 'Practice: GO' : phase === 'interrupted' ? 'Paused' : 'GO activity'}>
        {phase === 'interrupted' ? (
          <p>
            The activity was paused. You can continue with the next round (the pause will be noted), or save what
            you have done and stop.
          </p>
        ) : (
          <>
            <p>Wait until GO appears, then press as soon as you can.</p>
            <p>{mode === 'keyboard' ? 'Press the Space bar.' : 'Tap the large box.'} Don't press while it says “Wait…”.</p>
          </>
        )}
        <div className="flex flex-wrap gap-3">
          <BigButton
            onClick={() => {
              if (phase === 'interrupted') {
                const open = openInterruption.current
                if (open) open.end_ms = Math.max(open.start_ms, recorder.offset())
                openInterruption.current = null
                recorder.resume()
                setPhase('instructions')
              } else {
                stage.current = 'iti'
                itiEnds.current = 0
                running.current = true
                setPhase('running')
              }
            }}
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
        <span>
          {practice ? 'Practice' : 'GO'}: {progress} of {trials.length}
        </span>
        {!practice && phase === 'running' && (
          <BigButton
            variant="secondary"
            onClick={() => {
              recorder.pause()
              interrupt('PAUSE')
            }}
          >
            <Pause aria-hidden="true" className="h-5 w-5" /> Pause
          </BigButton>
        )}
      </div>
      <div
        {...pointerProps}
        role={mode === 'pointer' ? 'button' : 'region'}
        aria-label={mode === 'pointer' ? 'Response area: tap when GO appears' : 'GO signal (press Space)'}
        className="flex h-72 touch-none select-none flex-col items-center justify-center rounded-xl border-4 border-slate-300 bg-white"
      >
        <div ref={stimulusRef} role="img" aria-label="Blank" className="flex min-h-40 items-center justify-center" />
        {practice && feedback && <p className="mt-2 text-center text-lg font-medium">{feedback}</p>}
      </div>
    </div>
  )
}
