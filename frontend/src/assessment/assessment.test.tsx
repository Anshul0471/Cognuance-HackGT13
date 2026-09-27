import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode, useEffect, useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthState } from '../auth/context'
import { ContextCheckinForm } from './ContextCheckinForm'
import { flowReducer, initialFlow, SKIPPED_MEMORY, SKIPPED_REACTION, type FlowState } from './flow'
import { createRunRecorder } from './recorder'
import { ReceiptView } from './ReceiptView'
import { ReviewSubmit } from './ReviewSubmit'
import { AttentionTask } from './tasks/AttentionTask'
import { MemoryTask } from './tasks/MemoryTask'
import { ReactionTask } from './tasks/ReactionTask'
import type {
  AssessmentSubmission,
  AttentionRecord,
  MemoryRecord,
  ReactionRecord,
  Receipt,
  SessionStart,
  Shape,
} from './types'

const FAKE = [
  'setTimeout',
  'clearTimeout',
  'setInterval',
  'clearInterval',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'performance',
  'Date',
] as const

const advance = (ms: number) => act(() => vi.advanceTimersByTime(ms))

function setVisibility(state: 'hidden' | 'visible') {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

const shapes: Shape[] = ['circle', 'square', 'triangle']
const attentionTrials = Array.from({ length: 30 }, (_, i) => ({
  trial_id: `att-${String(i + 1).padStart(2, '0')}`,
  shape: shapes[i % 3],
}))

describe('timed tasks (fake clock, React Strict Mode)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: [...FAKE] })
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('attention: 30 trials once each, auto-repeat ignored, ordered timing', () => {
    const recorder = createRunRecorder(500, 'keyboard')
    const onFinish = vi.fn<(r: AttentionRecord) => void>()
    render(
      <StrictMode>
        <AttentionTask
          trials={attentionTrials}
          stimulusMs={1000}
          gapMs={500}
          mode="keyboard"
          recorder={recorder}
          maxEventsPerTrial={20}
          onFinish={onFinish}
        />
      </StrictMode>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    advance(200)
    fireEvent.keyDown(window, { code: 'Space' })
    fireEvent.keyDown(window, { code: 'Space', repeat: true })
    fireEvent.keyDown(window, { code: 'Space', repeat: true })
    advance(30 * 1500 + 1000)

    expect(onFinish).toHaveBeenCalledTimes(1)
    const result = onFinish.mock.calls[0][0]
    expect(result.completion).toBe('COMPLETED')
    expect(result.end_reason).toBe('FINISHED')
    expect(result.trials.map((t) => t.trial_id)).toEqual(attentionTrials.map((t) => t.trial_id))
    expect(result.trials[0].responses).toHaveLength(1)
    expect(result.trials.every((t) => t.interruptions.length === 0 && !t.event_overflow)).toBe(true)
    for (const t of result.trials) {
      expect(t.offset_ms! - t.onset_ms).toBeGreaterThanOrEqual(1000)
      expect(t.offset_ms! - t.onset_ms).toBeLessThan(1100)
      expect(t.gap_end_ms! - t.offset_ms!).toBeGreaterThanOrEqual(500)
      expect(t.gap_end_ms! - t.offset_ms!).toBeLessThan(650)
    }
    recorder.dispose()
  })

  it('attention: hidden tab stops stimuli, records the interruption, resumes at the next trial', () => {
    const recorder = createRunRecorder(500, 'keyboard')
    const onFinish = vi.fn<(r: AttentionRecord) => void>()
    render(
      <AttentionTask
        trials={attentionTrials}
        stimulusMs={1000}
        gapMs={500}
        mode="keyboard"
        recorder={recorder}
        maxEventsPerTrial={20}
        onFinish={onFinish}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    advance(3 * 1500 + 300) // into trial 4
    act(() => setVisibility('hidden'))
    expect(screen.getByRole('heading', { name: 'Paused' })).toBeInTheDocument()
    act(() => setVisibility('visible'))
    advance(10_000) // nothing presented while paused

    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    advance(27 * 1500 + 1000)

    const result = onFinish.mock.calls[0][0]
    expect(result.trials).toHaveLength(30)
    const cut = result.trials.filter((t) => t.interruptions.length > 0)
    expect(cut.map((t) => t.trial_id)).toEqual(['att-04'])
    expect(cut[0].interruptions[0].kind).toBe('HIDDEN')
    expect(cut[0].interruptions[0].end_ms).toBeGreaterThanOrEqual(cut[0].interruptions[0].start_ms) // closed on Continue
    expect(recorder.telemetry().visibility_events.map((e) => e.state)).toEqual(['hidden', 'visible'])
    recorder.dispose()
  })

  it('reaction: false start ends the trial, response latency and timeout are captured; other channel is flagged', () => {
    const recorder = createRunRecorder(500, 'pointer')
    const onFinish = vi.fn<(r: ReactionRecord) => void>()
    render(
      <StrictMode>
        <ReactionTask
          trials={Array.from({ length: 10 }, (_, i) => ({ trial_id: `rt-${i + 1}`, foreperiod_ms: 2000 }))}
          responseWindowMs={3000}
          intertrialMs={750}
          mode="pointer"
          recorder={recorder}
          maxEventsPerTrial={20}
          onFinish={onFinish}
        />
      </StrictMode>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    const area = () => screen.getByRole('button', { name: /Response area/ })
    advance(500)
    fireEvent.pointerDown(area()) // before GO → false start
    // Wait for the GO stimulus itself, then respond ~300 ms later.
    for (let i = 0; i < 400 && !screen.queryByRole('img', { name: 'GO' }); i++) advance(16)
    expect(screen.getByRole('img', { name: 'GO' })).toBeInTheDocument()
    advance(300)
    fireEvent.pointerDown(area())
    advance(750 + 50 + 2000 + 3100) // ITI, wait, full window → timeout
    fireEvent.keyDown(window, { code: 'Space' }) // wrong channel in pointer mode
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    fireEvent.click(screen.getByRole('button', { name: "Save what I've done and stop" }))

    const { completion, trials } = onFinish.mock.calls[0][0]
    expect(completion).toBe('STOPPED')
    expect(trials[0]).toMatchObject({ end_reason: 'FALSE_START', go_onset_ms: null })
    expect(trials[1].end_reason).toBe('RESPONSE')
    expect(trials[0].intertrial_end_ms).toBeGreaterThanOrEqual(trials[0].end_ms + 750)
    expect(trials[1].max_frame_gap_ms).toBeGreaterThan(0)
    const latency = trials[1].responses[0].offset_ms - trials[1].go_onset_ms!
    expect(latency).toBeGreaterThanOrEqual(250)
    expect(latency).toBeLessThan(340)
    expect(trials[2].end_reason).toBe('TIMEOUT')
    expect(trials[2].end_ms - trials[2].go_onset_ms!).toBeGreaterThanOrEqual(3000)
    const tel = recorder.telemetry()
    expect(tel.mode_changes[0]).toMatchObject({ from: 'pointer', to: 'keyboard' })
    expect(tel.final_input_mode).toBe('keyboard') // the backend flags the timed tasks LOW
    expect(tel.pause_events).toHaveLength(1)
    expect(new Set(trials.map((t) => t.trial_id)).size).toBe(trials.length) // no duplicate trials
    recorder.dispose()
  })

  it('practice feedback advances even while the parent re-renders with a new onFinish every 500 ms', () => {
    // Regression: the session countdown re-renders the page each second; an unstable `finish`
    // restarted the feedback timer forever (found in the live browser run).
    const recorder = createRunRecorder(500, 'keyboard')
    const done = vi.fn()
    function Ticking() {
      const [, setTick] = useState(0)
      useEffect(() => {
        const timer = setInterval(() => setTick((t) => t + 1), 500)
        return () => clearInterval(timer)
      }, [])
      return (
        <AttentionTask
          practice
          trials={[
            { trial_id: 'p1', shape: 'circle', is_target: true },
            { trial_id: 'p2', shape: 'square', is_target: false },
          ]}
          stimulusMs={1000}
          gapMs={500}
          mode="keyboard"
          recorder={recorder}
          maxEventsPerTrial={20}
          onFinish={() => done()}
        />
      )
    }
    render(
      <StrictMode>
        <Ticking />
      </StrictMode>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    // Step the clock so React flushes between timers, as real time would (≈ 8 s total).
    for (let i = 0; i < 100; i++) advance(100)
    expect(done).toHaveBeenCalledTimes(1)
    recorder.dispose()
  })

  it('memory: hiding the page during the delay flags an interruption and never re-shows the words', () => {
    const recorder = createRunRecorder(500, 'keyboard')
    const onFinish = vi.fn<(r: MemoryRecord) => void>()
    render(
      <StrictMode>
        <MemoryTask
          config={{
            word_set_id: 'A',
            words: ['apple', 'chair', 'river', 'candle', 'garden', 'spoon'],
            exposure_ms: 2000,
            distractor_ms: 3000,
            recall_limit_ms: 60000,
            max_entries: 6,
            max_entry_chars: 40,
            distractor_step_ms: 1000,
          }}
          recorder={recorder}
          onFinish={onFinish}
        />
      </StrictMode>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ready' }))
    advance(100)
    expect(screen.getByText('apple')).toBeInTheDocument()
    advance(2100) // into the distractor
    expect(screen.queryByText('apple')).not.toBeInTheDocument()
    act(() => setVisibility('hidden'))
    act(() => setVisibility('visible'))
    expect(screen.getByRole('heading', { name: 'Paused' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Continue to the words' }))
    expect(screen.queryByText('apple')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Word 1'), { target: { value: 'apple' } })
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    const result = onFinish.mock.calls[0][0]
    expect(result).toMatchObject({ completion: 'COMPLETED', end_reason: 'DONE', recall_entries: ['apple'] })
    expect(result.interruptions).toHaveLength(1)
    expect(result.interruptions[0].kind).toBe('HIDDEN')
    const stages = [
      result.exposure_start_ms,
      result.exposure_end_ms,
      result.distractor_start_ms,
      result.distractor_end_ms,
      result.recall_start_ms,
      result.recall_end_ms,
    ]
    expect(stages.every((v) => v !== null)).toBe(true)
    expect(stages.every((v, i) => i === 0 || v! >= stages[i - 1]!)).toBe(true)
    // The delay was cut short: its recorded end is the interruption, not the planned 3 s.
    expect(result.distractor_end_ms! - result.distractor_start_ms!).toBeLessThan(3000)
    recorder.dispose()
  })
})

// --- state machine ------------------------------------------------------------------------------

describe('flow reducer', () => {
  const memoryDone: MemoryRecord = {
    ...SKIPPED_MEMORY,
    completion: 'COMPLETED',
    end_reason: 'DONE',
    recall_entries: ['apple'],
  }

  it('ignores duplicate or out-of-order transitions', () => {
    let s = flowReducer(initialFlow, { type: 'MEMORY_DONE', result: memoryDone })
    expect(s).toBe(initialFlow) // cannot skip practice
    s = flowReducer(s, { type: 'PRACTICE_DONE', record: { completed: true, repeats: 0 } })
    s = flowReducer(s, { type: 'MEMORY_DONE', result: memoryDone })
    const again = flowReducer(s, { type: 'MEMORY_DONE', result: { ...memoryDone, recall_entries: [] } })
    expect(again).toBe(s)
    expect(s.step).toBe('break-attention')
  })

  it('save partial marks untouched tasks SKIPPED, never zero-scored', () => {
    let s = flowReducer(initialFlow, { type: 'PRACTICE_DONE', record: { completed: true, repeats: 0 } })
    s = flowReducer(s, { type: 'MEMORY_DONE', result: memoryDone })
    s = flowReducer(s, { type: 'SAVE_PARTIAL' })
    expect(s.step).toBe('context')
    expect(s.attention).toEqual({ completion: 'SKIPPED', trials: [], end_reason: 'SKIPPED' })
    expect(s.reaction).toEqual(SKIPPED_REACTION)
    expect(s.memory).toBe(memoryDone)
  })
})

// --- context check-in ---------------------------------------------------------------------------

describe('context check-in', () => {
  it('requires explicit answers or skips and records missing reasons; zero sleep is an answer', async () => {
    const onDone = vi.fn()
    const user = userEvent.setup()
    render(<ContextCheckinForm firstCheckIn navigationDeclared={false} onDone={onDone} />)
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Mood')
    expect(onDone).not.toHaveBeenCalled()

    await user.type(screen.getByLabelText('Hours of sleep'), '0')
    const moodGroup = screen.getByRole('group', { name: /mood/i })
    await user.click(within(moodGroup).getByRole('button', { name: 'Skip this question' }))
    const medGroup = screen.getByRole('group', { name: /medication/i })
    await user.click(within(medGroup).getByRole('button', { name: "I don't know" }))
    await user.click(screen.getByLabelText('Me (the patient)'))
    for (const name of [/move between screens/, /enter these answers/, /remember or type/, /shapes activity/, /GO activity/]) {
      await user.click(within(screen.getByRole('group', { name })).getByLabelText('No'))
    }
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onDone).toHaveBeenCalledWith({
      context: {
        sleep_hours: 0,
        mood_score: null,
        medication_change: null,
        reported_by: 'PATIENT',
        missing_fields: { mood_score: 'SKIPPED', medication_change: 'UNKNOWN' },
      },
      assistance: {
        navigation_help: false,
        context_help: false,
        answer_help: { memory: 'NONE', attention: 'NONE', reaction: 'NONE' },
      },
    })
  })
})

// --- submission retries -------------------------------------------------------------------------

describe('review and submit', () => {
  const session = { session_id: 's-1', protocol_version: 'cognitive_tasks_en_v1', input_mode: 'keyboard' } as SessionStart
  const state: FlowState = {
    ...initialFlow,
    step: 'review',
    memory: { ...SKIPPED_MEMORY, completion: 'COMPLETED', end_reason: 'DONE' },
    attention: { completion: 'COMPLETED', trials: [], end_reason: 'FINISHED' },
    reaction: { completion: 'COMPLETED', trials: [], end_reason: 'FINISHED' },
    contextResult: {
      context: { sleep_hours: 7, mood_score: 6, medication_change: false, reported_by: 'PATIENT', missing_fields: {} },
      assistance: {
        navigation_help: false,
        context_help: false,
        answer_help: { memory: 'NONE', attention: 'NONE', reaction: 'NONE' },
      },
    },
  }
  const receipt: Receipt = {
    assessment_id: 'a-1',
    session_id: 's-1',
    received_at: '2026-09-26T16:00:00.000Z',
    saved: true,
    quality: { status: 'VALID', reason_codes: [], message: 'Your check-in was saved.' },
    analysis: { availability: 'BUILDING_BASELINE', reason_codes: ['BUILDING_BASELINE'], message: 'More weekly check-ins are needed.' },
    replayed: false,
  }
  let keyCounter = 0
  const freeze = vi.fn((): AssessmentSubmission => ({ submission_key: `key-${++keyCounter}` }) as AssessmentSubmission)

  function renderReview(auth: Partial<AuthState> = {}) {
    const onSaved = vi.fn()
    const value = {
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
      setDraftActive: vi.fn(),
      reauthenticate: vi.fn(async () => {}),
      ...auth,
    } as AuthState
    render(
      <AuthContext.Provider value={value}>
        <MemoryRouter>
          <ReviewSubmit state={state} session={session} freeze={freeze} onSaved={onSaved} onEditContext={vi.fn()} />
        </MemoryRouter>
      </AuthContext.Provider>,
    )
    return { onSaved, value }
  }

  const bodies = (fetchMock: ReturnType<typeof vi.fn>) => fetchMock.mock.calls.map(([, init]) => init?.body)

  beforeEach(() => {
    freeze.mockClear()
    keyCounter = 0
  })

  it('network failure after server commit: retry resends the identical body and key', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(new Response(JSON.stringify(receipt), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const { onSaved } = renderReview()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Save check-in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not saved yet')
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    expect(onSaved).toHaveBeenCalledWith(receipt)
    expect(freeze).toHaveBeenCalledTimes(1)
    const [first, second] = bodies(fetchMock)
    expect(second).toBe(first)
    expect(JSON.parse(first as string).submission_key).toBe('key-1')
  })

  it('auth expiry with an in-memory draft: re-authenticate, then resend without redoing tasks', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'NOT_AUTHENTICATED', message: 'x', request_id: null, details: {} } }), {
          status: 401,
        }))
      .mockResolvedValueOnce(new Response(JSON.stringify(receipt), { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    const { onSaved, value } = renderReview()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Save check-in' }))
    await user.type(await screen.findByLabelText('Password'), 'pw')
    await user.click(screen.getByRole('button', { name: 'Sign in and save' }))

    expect(value.reauthenticate).toHaveBeenCalledWith('pw')
    expect(onSaved).toHaveBeenCalledWith(receipt)
    const [first, second] = bodies(fetchMock)
    expect(second).toBe(first)
    expect(value.logout).not.toHaveBeenCalled()
  })

  it('first submission after expiry shows not saved', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: 'SESSION_EXPIRED', message: 'x', request_id: null, details: {} } }),
          { status: 409 },
        ),
      ),
    )
    renderReview()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Save check-in' }))
    expect(await screen.findByRole('heading', { name: 'Not saved' })).toBeInTheDocument()
  })
})

describe('receipt', () => {
  const base: Receipt = {
    assessment_id: 'a-1',
    session_id: 's-1',
    received_at: '2026-09-26T16:00:00.000Z',
    saved: true,
    quality: { status: 'VALID', reason_codes: [], message: 'Your check-in was saved.' },
    analysis: { availability: 'COMPLETE', reason_codes: [], message: 'Your check-in has been processed.' },
    replayed: false,
  }

  it('says a completed comparison happened without revealing any result', () => {
    render(
      <MemoryRouter>
        <ReceiptView receipt={base} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/compared with your earlier weekly check-ins/)).toBeInTheDocument()
    expect(screen.queryByText(/deviation|alert|normal|score/i)).not.toBeInTheDocument()
  })

  it('does not claim a comparison when analysis was unavailable', () => {
    render(
      <MemoryRouter>
        <ReceiptView
          receipt={{
            ...base,
            analysis: {
              availability: 'BUILDING_BASELINE',
              reason_codes: ['BUILDING_BASELINE'],
              message: 'More weekly check-ins are needed before changes can be compared.',
            },
          }}
        />
      </MemoryRouter>,
    )
    expect(screen.queryByText(/compared with your earlier weekly check-ins/)).not.toBeInTheDocument()
    expect(screen.getByText(/More weekly check-ins are needed/)).toBeInTheDocument()
  })
})
