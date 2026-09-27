// TypeScript mirror of the backend contract `backend_contract_v1` (docs/openapi.json,
// backend/app/schemas/assessments.py). All *_ms offsets are milliseconds on performance.now()
// relative to one run origin. Every submission field is required; absent stages are null / [].

export type InputMode = 'keyboard' | 'pointer'
export type Completion = 'COMPLETED' | 'SKIPPED' | 'STOPPED'
export type AnswerHelp = 'NONE' | 'PROVIDED' | 'UNKNOWN'
export type Shape = 'circle' | 'square' | 'triangle'
export type SchedulePurpose = 'SCHEDULED' | 'RETAKE_AFTER_UNRELIABLE' | 'EXTRA_ATTEMPT' | 'OFF_SCHEDULE'
export type SessionStatus = 'STARTED' | 'SUBMITTED' | 'ABANDONED' | 'EXPIRED'

// --- session start ----------------------------------------------------------------------------

export type StartSessionRequest = {
  start_key: string
  input_mode: InputMode
  device_changed: boolean
  navigation_assistance: boolean
  allow_unscheduled: boolean
}

export type RenderProtocol = {
  protocol_version: string
  language: string
  memory: {
    word_set_id: string
    words: string[]
    exposure_ms: number
    distractor_ms: number
    recall_limit_ms: number
    max_entries: number
    max_entry_chars: number
    distractor_step_ms: number
  }
  attention: {
    trial_count: number
    stimulus_ms: number
    gap_ms: number
    trials: { trial_id: string; shape: Shape }[]
  }
  reaction: {
    trial_count: number
    response_window_ms: number
    minimum_response_ms: number
    intertrial_ms: number
    trials: { trial_id: string; foreperiod_ms: number }[]
  }
  practice: {
    memory_words: string[]
    attention_trials: { trial_id: string; shape: Shape; is_target: boolean }[]
    reaction_foreperiods_ms: number[]
    max_repeats: number
  }
  limits: { max_events_per_trial: number; max_telemetry_events: number; max_run_duration_ms: number }
}

export type SessionSchedule = {
  anchor_at: string
  slot_index: number
  target_at: string
  purpose: SchedulePurpose
  longitudinal_eligible: boolean
  reason_codes: string[]
}

type SessionBase = {
  session_id: string
  status: SessionStatus
  started_at: string
  expires_at: string
  target_at: string
  protocol_version: string
  scoring_version: string
  input_mode: InputMode
  schedule: SessionSchedule
}

export type StartAssessmentResponse = SessionBase & { protocol: RenderProtocol | null; replayed: boolean }
/** A started session whose task material is available (protocol non-null). */
export type SessionStart = SessionBase & { protocol: RenderProtocol; replayed: boolean }
export type SessionRecovery = SessionBase & { assessment_id: string | null; receipt_path: string | null }

// --- submission -------------------------------------------------------------------------------

export type ResponseEvent = { offset_ms: number }
export type TimingInterruption = { kind: 'HIDDEN' | 'PAUSE' | 'TIMING_GAP'; start_ms: number; end_ms: number | null }

export type MemoryRecord = {
  completion: Completion
  exposure_start_ms: number | null
  exposure_end_ms: number | null
  distractor_start_ms: number | null
  distractor_end_ms: number | null
  recall_start_ms: number | null
  recall_end_ms: number | null
  recall_entries: string[]
  end_reason: 'DONE' | 'NONE_RECALLED' | 'TIMEOUT' | 'SKIPPED' | 'STOPPED'
  interruptions: TimingInterruption[]
}

export type AttentionTrialRecord = {
  trial_id: string
  onset_ms: number
  offset_ms: number | null
  gap_end_ms: number | null
  responses: ResponseEvent[]
  interruptions: TimingInterruption[]
  event_overflow: boolean
}

export type AttentionRecord = {
  completion: Completion
  trials: AttentionTrialRecord[]
  end_reason: 'FINISHED' | 'SKIPPED' | 'STOPPED'
}

export type ReactionTrialRecord = {
  trial_id: string
  wait_start_ms: number
  go_onset_ms: number | null
  end_ms: number
  intertrial_end_ms: number | null
  responses: ResponseEvent[]
  end_reason: 'RESPONSE' | 'FALSE_START' | 'TIMEOUT' | 'INTERRUPTED'
  interruptions: TimingInterruption[]
  max_frame_gap_ms: number | null
  event_overflow: boolean
}

export type ReactionRecord = {
  completion: Completion
  trials: ReactionTrialRecord[]
  end_reason: 'FINISHED' | 'SKIPPED' | 'STOPPED'
}

export type PracticeRecord = { completed: boolean; repeats: number }

export type Assistance = {
  navigation_help: boolean
  context_help: boolean
  answer_help: { memory: AnswerHelp; attention: AnswerHelp; reaction: AnswerHelp }
}

export type Telemetry = {
  initial_input_mode: InputMode
  final_input_mode: InputMode
  viewport: { width: number; height: number }
  visibility_events: { offset_ms: number; state: 'visible' | 'hidden' }[]
  pause_events: { start_ms: number; end_ms: number | null }[]
  blur_count: number
  mode_changes: { offset_ms: number; from: InputMode; to: InputMode }[]
  event_overflow: boolean
  assistance: Assistance
}

export type ContextField = 'sleep_hours' | 'mood_score' | 'medication_change'
export type MissingReason = 'SKIPPED' | 'UNKNOWN'

export type ContextCheckin = {
  sleep_hours: number | null
  mood_score: number | null
  /** true = a medication change was reported; null = unknown or skipped (see missing_fields). */
  medication_change: boolean | null
  reported_by: 'PATIENT' | 'CAREGIVER_ASSISTED'
  missing_fields: Partial<Record<ContextField, MissingReason>>
}

export type AssessmentSubmission = {
  submission_key: string
  run_id: string
  protocol_version: string
  run_duration_ms: number
  memory: MemoryRecord
  attention: AttentionRecord
  reaction: ReactionRecord
  practice: PracticeRecord
  telemetry: Telemetry
  context: ContextCheckin
}

// --- receipts / status ------------------------------------------------------------------------

export type AnalysisAvailability =
  | 'PENDING'
  | 'BUILDING_BASELINE'
  | 'INSUFFICIENT_DATA'
  | 'MODEL_UNAVAILABLE'
  | 'ANALYSIS_ERROR'
  | 'COMPLETE'

export type Receipt = {
  assessment_id: string
  session_id: string
  received_at: string
  saved: true
  quality: { status: 'VALID' | 'LOW' | 'INCOMPLETE'; reason_codes: string[]; message: string }
  analysis: { availability: AnalysisAvailability; reason_codes: string[]; message: string }
  replayed: boolean
}

export type AssessmentStatus = {
  patient_id: string
  server_time: string
  current_session: {
    session_id: string
    status: SessionStatus
    started_at: string
    expires_at: string
    target_at: string
  } | null
  last_receipt: Receipt | null
  schedule: {
    anchor_at: string | null
    next_target_at: string | null
    window_opens_at: string | null
    window_closes_at: string | null
    scheduled_start_allowed: boolean
    reason_codes: string[]
  }
}
