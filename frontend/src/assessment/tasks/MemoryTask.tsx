import { Pause } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunRecorder } from '../recorder'
import type { MemoryRecord, RenderProtocol, TimingInterruption } from '../types'
import { formatMs } from '../stimuli'
import { BigButton, Screen } from '../ui'
import { useFrameLoop } from '../useFrameLoop'
import { useLatest } from '../useLatest'

type Phase = 'instructions' | 'exposure' | 'distractor' | 'interrupted' | 'recall' | 'done'

// Fixed distractor positions (percent of the area); the dot moves every distractor_step_ms.
const DOT_POSITIONS = [
  [20, 25],
  [75, 30],
  [50, 70],
  [15, 75],
  [80, 75],
  [45, 20],
  [30, 50],
  [70, 55],
]

export type MemoryTaskProps = {
  config: RenderProtocol['memory']
  recorder: RunRecorder
  onFinish: (result: MemoryRecord) => void
}

export function MemoryTask({ config, recorder, onFinish }: MemoryTaskProps) {
  const [phase, setPhase] = useState<Phase>('instructions')
  const [dot, setDot] = useState(0)
  const [remaining, setRemaining] = useState(config.recall_limit_ms)
  const [entries, setEntries] = useState<string[]>(() => Array(config.max_entries).fill(''))
  const entriesRef = useRef(entries)
  const timeline = useRef<{
    exposureStartAbs: number | null
    exposureEndAbs: number | null
    recallStartAbs: number | null
    exposure_start_ms: number | null
    exposure_end_ms: number | null
    distractor_start_ms: number | null
    distractor_end_ms: number | null
    recall_start_ms: number | null
    interruptions: TimingInterruption[]
  }>({
    exposureStartAbs: null,
    exposureEndAbs: null,
    recallStartAbs: null,
    exposure_start_ms: null,
    exposure_end_ms: null,
    distractor_start_ms: null,
    distractor_end_ms: null,
    recall_start_ms: null,
    interruptions: [],
  })
  const finished = useRef(false)
  const onFinishRef = useLatest(onFinish)
  const phaseRef = useRef<Phase>('instructions')
  useEffect(() => {
    phaseRef.current = phase
    entriesRef.current = entries
  }, [phase, entries])

  const finish = useCallback(
    (endReason: MemoryRecord['end_reason'], recallEnd: number | null) => {
      if (finished.current) return
      finished.current = true
      const tl = timeline.current
      const completed = endReason === 'DONE' || endReason === 'NONE_RECALLED' || endReason === 'TIMEOUT'
      setPhase('done')
      onFinishRef.current({
        completion: completed ? 'COMPLETED' : 'STOPPED',
        exposure_start_ms: tl.exposure_start_ms,
        exposure_end_ms: tl.exposure_end_ms,
        distractor_start_ms: tl.distractor_start_ms,
        distractor_end_ms: tl.distractor_end_ms,
        recall_start_ms: tl.recall_start_ms,
        recall_end_ms: recallEnd,
        recall_entries:
          endReason === 'NONE_RECALLED' ? [] : entriesRef.current.map((e) => e.trim()).filter(Boolean),
        end_reason: endReason,
        interruptions: tl.interruptions.map((i) => ({ ...i })),
      })
    },
    [onFinishRef],
  )

  const startRecall = (ts: number) => {
    const tl = timeline.current
    if (tl.recall_start_ms !== null) return
    tl.recall_start_ms = recorder.offset(ts)
    tl.recallStartAbs = ts
    setPhase('recall')
  }

  const timed = phase === 'exposure' || phase === 'distractor' || phase === 'recall'
  useFrameLoop(timed, (ts) => {
    const tl = timeline.current
    const current = phaseRef.current
    if (current === 'exposure') {
      if (tl.exposureStartAbs === null) {
        tl.exposureStartAbs = ts
        tl.exposure_start_ms = recorder.offset(ts)
      } else if (ts - tl.exposureStartAbs >= config.exposure_ms) {
        tl.exposureEndAbs = ts
        tl.exposure_end_ms = recorder.offset(ts)
        tl.distractor_start_ms = tl.exposure_end_ms
        phaseRef.current = 'distractor'
        setPhase('distractor') // words unmount: gone from the screen and accessibility tree
      }
    } else if (current === 'distractor' && tl.exposureEndAbs !== null) {
      const elapsed = ts - tl.exposureEndAbs
      setDot(Math.floor(elapsed / config.distractor_step_ms) % DOT_POSITIONS.length)
      if (elapsed >= config.distractor_ms) {
        tl.distractor_end_ms = recorder.offset(ts)
        phaseRef.current = 'recall'
        startRecall(ts) // recall opens automatically
      }
    } else if (current === 'recall' && tl.recallStartAbs !== null) {
      const left = config.recall_limit_ms - (ts - tl.recallStartAbs)
      setRemaining(left)
      if (left <= 0) finish('TIMEOUT', recorder.offset(ts))
    }
  })

  // Hiding the page or pausing during exposure/delay ends that phase: words are never re-shown.
  const interrupt = useCallback(
    (kind: TimingInterruption['kind']) => {
      const current = phaseRef.current
      if (current !== 'exposure' && current !== 'distractor') return
      const tl = timeline.current
      const now = recorder.offset()
      // Stages end where the interruption happened (a skipped delay is recorded, not invented).
      if (tl.exposure_start_ms === null) tl.exposure_start_ms = now
      if (tl.exposure_end_ms === null) tl.exposure_end_ms = now
      if (tl.distractor_start_ms === null) tl.distractor_start_ms = tl.exposure_end_ms
      if (tl.distractor_end_ms === null) tl.distractor_end_ms = now
      tl.interruptions.push({ kind, start_ms: now, end_ms: null })
      phaseRef.current = 'interrupted'
      setPhase('interrupted')
    },
    [recorder],
  )

  useEffect(() => {
    if (phase !== 'exposure' && phase !== 'distractor') return
    return recorder.onHidden(() => interrupt('HIDDEN'))
  }, [phase, recorder, interrupt])

  const pause = () => {
    recorder.pause()
    interrupt('PAUSE')
  }

  const closeInterruption = () => {
    const open = timeline.current.interruptions.find((i) => i.end_ms === null)
    if (open) open.end_ms = Math.max(open.start_ms, recorder.offset())
    recorder.resume()
  }

  if (phase === 'instructions') {
    return (
      <Screen title="Word memory">
        <p>
          You will see {config.words.length} words for {config.exposure_ms / 1000} seconds. Try to remember them. Then
          there is a short wait, and you will be asked to type the words you remember.
        </p>
        <BigButton onClick={() => setPhase('exposure')}>Ready</BigButton>
      </Screen>
    )
  }

  if (phase === 'exposure') {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Remember these words</h1>
          <BigButton variant="secondary" onClick={pause}>
            <Pause aria-hidden="true" className="h-5 w-5" /> Pause
          </BigButton>
        </div>
        <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3" aria-label="Words to remember">
          {config.words.map((word) => (
            <li key={word} className="rounded-lg border-2 border-slate-300 bg-white py-6 text-center text-3xl font-semibold">
              {word}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (phase === 'distractor') {
    const [x, y] = DOT_POSITIONS[dot]
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Short wait</h1>
          <BigButton variant="secondary" onClick={pause}>
            <Pause aria-hidden="true" className="h-5 w-5" /> Pause
          </BigButton>
        </div>
        <p className="text-lg">Watch the dot. You can tap it if you like — this part is not scored.</p>
        <div className="relative h-72 rounded-xl border-4 border-slate-300 bg-white" aria-hidden="true">
          <span
            className="absolute h-14 w-14 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-800"
            style={{ left: `${x}%`, top: `${y}%` }}
          />
        </div>
      </div>
    )
  }

  if (phase === 'interrupted') {
    return (
      <Screen title="Paused">
        <p>
          The word activity was interrupted. The words won't be shown again. You can go on to type the words you
          remember (the interruption will be noted), or save what you have done and stop.
        </p>
        <div className="flex flex-wrap gap-3">
          <BigButton
            onClick={() => {
              closeInterruption()
              startRecall(performance.now())
            }}
          >
            Continue to the words
          </BigButton>
          <BigButton variant="danger" onClick={() => finish('STOPPED', null)}>
            Save what I've done and stop
          </BigButton>
        </div>
      </Screen>
    )
  }

  return (
    <form
      className="space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        finish('DONE', recorder.offset())
      }}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">Type the words you remember</h1>
        <span className="text-lg text-slate-600" aria-live="off">
          Time left: {formatMs(remaining)}
        </span>
      </div>
      <p className="text-lg">One word per box, in any order. Leave boxes empty if you don't remember more.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {entries.map((value, i) => (
          <label key={i} className="block">
            <span className="text-base font-medium">Word {i + 1}</span>
            <input
              value={value}
              maxLength={config.max_entry_chars}
              onChange={(event) => {
                const next = [...entries]
                next[i] = event.target.value.replace(/\s+/g, '')
                setEntries(next)
              }}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              inputMode="text"
              className="mt-1 w-full rounded-md border-2 border-slate-300 px-3 py-3 text-xl focus:border-indigo-600 focus:outline-none"
            />
          </label>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <BigButton type="submit">Done</BigButton>
        <BigButton variant="secondary" onClick={() => finish('NONE_RECALLED', recorder.offset())}>
          I don't remember any
        </BigButton>
      </div>
    </form>
  )
}
