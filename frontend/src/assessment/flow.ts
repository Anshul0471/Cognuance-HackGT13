// Typed assessment state machine. Every transition is guarded by the step it may leave, so a
// duplicate dispatch (double click, Strict Mode re-run, late timer) can never skip a task or mark
// a task complete twice.

import type { ContextResult } from './ContextCheckinForm'
import type { RunRecorder } from './recorder'
import type {
  AssessmentSubmission,
  AttentionRecord,
  MemoryRecord,
  PracticeRecord,
  ReactionRecord,
  Receipt,
  SessionStart,
} from './types'

export type FlowStep =
  | 'practice'
  | 'memory'
  | 'break-attention'
  | 'attention'
  | 'break-reaction'
  | 'reaction'
  | 'context'
  | 'review'
  | 'receipt'

export type FlowState = {
  step: FlowStep
  practice: PracticeRecord | null
  memory: MemoryRecord | null
  attention: AttentionRecord | null
  reaction: ReactionRecord | null
  contextResult: ContextResult | null
  receipt: Receipt | null
}

export type FlowAction =
  | { type: 'PRACTICE_DONE'; record: PracticeRecord }
  | { type: 'MEMORY_DONE'; result: MemoryRecord }
  | { type: 'CONTINUE' }
  | { type: 'ATTENTION_DONE'; result: AttentionRecord }
  | { type: 'REACTION_DONE'; result: ReactionRecord }
  | { type: 'SAVE_PARTIAL'; practice?: PracticeRecord }
  | { type: 'CONTEXT_DONE'; result: ContextResult }
  | { type: 'EDIT_CONTEXT' }
  | { type: 'SAVED'; receipt: Receipt }

export const SKIPPED_MEMORY: MemoryRecord = {
  completion: 'SKIPPED',
  exposure_start_ms: null,
  exposure_end_ms: null,
  distractor_start_ms: null,
  distractor_end_ms: null,
  recall_start_ms: null,
  recall_end_ms: null,
  recall_entries: [],
  end_reason: 'SKIPPED',
  interruptions: [],
}
export const SKIPPED_ATTENTION: AttentionRecord = { completion: 'SKIPPED', trials: [], end_reason: 'SKIPPED' }
export const SKIPPED_REACTION: ReactionRecord = { completion: 'SKIPPED', trials: [], end_reason: 'SKIPPED' }
const NO_PRACTICE: PracticeRecord = { completed: false, repeats: 0 }

export const initialFlow: FlowState = {
  step: 'practice',
  practice: null,
  memory: null,
  attention: null,
  reaction: null,
  contextResult: null,
  receipt: null,
}

const TASK_STEPS: FlowStep[] = ['practice', 'memory', 'break-attention', 'attention', 'break-reaction', 'reaction']

/** Save partial: untouched tasks become SKIPPED (never zero), then context → review → submit. */
function toPartial(state: FlowState, practice?: PracticeRecord): FlowState {
  return {
    ...state,
    step: 'context',
    practice: state.practice ?? practice ?? NO_PRACTICE,
    memory: state.memory ?? SKIPPED_MEMORY,
    attention: state.attention ?? SKIPPED_ATTENTION,
    reaction: state.reaction ?? SKIPPED_REACTION,
  }
}

export function flowReducer(state: FlowState, action: FlowAction): FlowState {
  switch (action.type) {
    case 'PRACTICE_DONE':
      return state.step === 'practice' ? { ...state, step: 'memory', practice: action.record } : state
    case 'MEMORY_DONE':
      if (state.step !== 'memory') return state
      return action.result.completion === 'COMPLETED'
        ? { ...state, step: 'break-attention', memory: action.result }
        : toPartial({ ...state, memory: action.result })
    case 'CONTINUE':
      if (state.step === 'break-attention') return { ...state, step: 'attention' }
      if (state.step === 'break-reaction') return { ...state, step: 'reaction' }
      return state
    case 'ATTENTION_DONE':
      if (state.step !== 'attention') return state
      return action.result.completion === 'COMPLETED'
        ? { ...state, step: 'break-reaction', attention: action.result }
        : toPartial({ ...state, attention: action.result })
    case 'REACTION_DONE':
      return state.step === 'reaction' ? { ...state, step: 'context', reaction: action.result } : state
    case 'SAVE_PARTIAL':
      return TASK_STEPS.includes(state.step) ? toPartial(state, action.practice) : state
    case 'CONTEXT_DONE':
      return state.step === 'context' ? { ...state, step: 'review', contextResult: action.result } : state
    case 'EDIT_CONTEXT':
      return state.step === 'review' ? { ...state, step: 'context' } : state
    case 'SAVED':
      return state.step === 'review' ? { ...state, step: 'receipt', receipt: action.receipt } : state
  }
}

// Coarse viewport only (rounded to 100 px, at least 100): no device fingerprinting.
const coarse = (px: number) => Math.min(10000, Math.max(100, Math.round(px / 100) * 100))

/** Freeze the final payload. Called once per submission key. */
export function buildSubmission(
  state: FlowState,
  session: SessionStart,
  recorder: RunRecorder,
  submissionKey: string,
): AssessmentSubmission {
  if (!state.contextResult) throw new Error('Context check-in missing')
  return {
    submission_key: submissionKey,
    run_id: recorder.runId,
    protocol_version: session.protocol_version,
    run_duration_ms: recorder.offset(),
    memory: state.memory ?? SKIPPED_MEMORY,
    attention: state.attention ?? SKIPPED_ATTENTION,
    reaction: state.reaction ?? SKIPPED_REACTION,
    practice: state.practice ?? NO_PRACTICE,
    telemetry: {
      ...recorder.telemetry(),
      viewport: { width: coarse(window.innerWidth), height: coarse(window.innerHeight) },
      assistance: state.contextResult.assistance,
    },
    context: state.contextResult.context,
  }
}
