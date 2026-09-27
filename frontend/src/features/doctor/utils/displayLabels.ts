import type {
  Availability,
  DeviationLevel,
  Domain,
  Quality,
  ReviewAction,
  SchedulePurpose,
  Source,
  WorkflowStatus,
} from '../schemas'

// One place for doctor-facing wording (guide 06 §9) so every screen agrees. Availability,
// deviation category and review workflow are separate dimensions with separate labels.

export const AVAILABILITY_LABEL: Record<Availability, string> = {
  PENDING: 'Analysis pending',
  BUILDING_BASELINE: 'Building a personal baseline',
  INSUFFICIENT_DATA: 'Not enough usable history',
  MODEL_UNAVAILABLE: 'Forecast unavailable',
  ANALYSIS_ERROR: 'Analysis could not be completed',
  COMPLETE: 'Comparison complete',
}

export const AVAILABILITY_HELP: Record<Availability, string> = {
  PENDING: 'The check-in is saved; its comparison has not finished yet.',
  BUILDING_BASELINE: 'Fewer than six earlier weekly check-ins, so no deviation conclusion yet.',
  INSUFFICIENT_DATA: 'This check-in could not be compared reliably (see the reasons).',
  MODEL_UNAVAILABLE: 'No stored forecast exists for this check-in; observed results remain visible.',
  ANALYSIS_ERROR: 'The saved results are kept; the comparison can be retried by the operator.',
  COMPLETE: 'Compared with the forecast stored before the tasks began.',
}

export const DEVIATION_LABEL: Record<DeviationLevel, string> = {
  NORMAL: 'No configured deviation detected',
  REVIEW: 'Change flagged for review',
  PERSISTENT_DEVIATION: 'Repeated change flagged',
  HIGH_DEVIATION: 'Large change flagged',
}

export const WORKFLOW_LABEL: Record<WorkflowStatus, string> = {
  OPEN: 'Open',
  ACKNOWLEDGED: 'Acknowledged',
  RESOLVED: 'Resolved',
}

export const ACTION_LABEL: Record<ReviewAction | 'CREATED', string> = {
  CREATED: 'Review item created',
  ACKNOWLEDGED: 'Acknowledged',
  NOTE_ADDED: 'Note added',
  RESOLVED: 'Resolved',
}

export const SOURCE_LABEL: Record<Source, string> = {
  // Readable provenance (refinement 02 §5). Stored enums are unchanged; "Interactive assessment"
  // describes how responses were collected, not that the account is a verified real patient.
  LIVE_DEMO: 'Interactive assessment',
  SYNTHETIC_HISTORY: 'Synthetic history',
  SCENARIO_REPLAY: 'Simulated scenario',
}

export const PURPOSE_LABEL: Record<SchedulePurpose, string> = {
  SCHEDULED: 'Weekly check-in',
  RETAKE_AFTER_UNRELIABLE: 'Retake after an unreliable attempt',
  EXTRA_ATTEMPT: 'Extra attempt',
  OFF_SCHEDULE: 'Off-schedule check-in',
}

export const QUALITY_LABEL: Record<Quality, string> = {
  VALID: 'Valid',
  LOW: 'Low quality',
  INCOMPLETE: 'Incomplete',
}

export const DOMAIN_LABEL: Record<Domain, string> = {
  memory: 'Memory',
  attention: 'Attention',
  reaction_time_ms: 'Reaction time',
}

export const MODEL_KIND_LABEL: Record<string, string> = {
  GRU: 'GRU forecaster',
  LAST_VALUE: 'Last-value baseline',
  LINEAR_TREND: 'Linear-trend baseline',
}

export const TASK_LABEL: Record<string, string> = {
  memory: 'Word memory',
  attention: 'Shapes (attention)',
  reaction: 'GO (reaction time)',
}

export const COUNTER_LABEL: Record<string, string> = {
  correct: 'Words recalled correctly',
  incorrect: 'Incorrect entries',
  duplicates: 'Duplicate entries',
  hits: 'Hits (pressed for a circle)',
  misses: 'Misses (circle, no press)',
  false_alarms: 'False alarms (pressed for another shape)',
  correct_rejections: 'Correct rejections',
  extra_presses: 'Extra presses in a window',
  gap_presses: 'Presses between shapes',
  trials_presented: 'Trials presented',
  usable: 'Usable responses',
  false_starts: 'False starts',
  anticipatory: 'Anticipatory responses (< 100 ms)',
  timeouts: 'Timeouts',
  interrupted: 'Interrupted trials',
  aborted: 'Aborted trials',
}

export const REASON_TEXT: Record<string, string> = {
  // analysis / history / model
  BUILDING_BASELINE: 'Fewer than six earlier weekly check-ins.',
  HISTORY_GAP: 'One of the six previous weekly slots has no usable check-in.',
  INCOMPLETE_TARGET: 'This check-in was incomplete, so it was not compared.',
  LOW_QUALITY_TARGET: 'This check-in had a quality problem, so it was not compared.',
  EXTRA_ATTEMPT: 'Extra attempt in a week that already had a check-in; not used for weekly comparison.',
  OFF_SCHEDULE: 'Outside the weekly window; not used for weekly comparison.',
  RETAKE_AFTER_UNRELIABLE: 'Second attempt this week after an unreliable one; practice effects are possible.',
  REPRESENTATIVE_ALREADY_EXISTS: 'Another check-in already represents this week.',
  COMPARABILITY_CHANGE: 'The device or answering method changed; a new comparison history starts here.',
  PROTOCOL_MISMATCH: 'The task or scoring version differs from the earlier history.',
  LATE_AVAILABILITY: 'An earlier check-in arrived after the forecast cutoff.',
  HISTORICAL_IMPORT: 'Imported synthetic history; it was never compared when recorded.',
  MODEL_NOT_CONFIGURED: 'No forecasting model was configured when this session started.',
  MODEL_UNAVAILABLE: 'No forecast was issued when this session started.',
  NO_ACTIVE_MODEL: 'No active forecasting model was registered when this session started.',
  MODEL_MODE_MISMATCH: 'The server configuration did not match the active model, so no forecast was issued.',
  ARTIFACT_LOAD_FAILED: 'The model files could not be loaded when this session started.',
  ARTIFACT_VERSION_MISMATCH: 'The model files did not match their registration.',
  ARTIFACT_CHECKSUM_MISMATCH: 'The model files failed verification.',
  TORCH_NOT_INSTALLED: 'The neural-model runtime was not installed on the server.',
  POLICY_INVALID: 'The anomaly policy could not be used.',
  POLICY_MODEL_MISMATCH: 'The anomaly policy did not match the forecast model.',
  POLICY_OR_FORECAST_MISSING: 'The stored forecast or its policy could not be found.',
  FORECAST_FAILED: 'The forecast could not be prepared for this session.',
  FORECAST_MISSING: 'No forecast was stored for this session.',
  STORED_VALUES_INVALID: 'Stored values could not be used for the comparison.',
  CALCULATION_FAILED: 'The comparison calculation failed.',
  PROCESSING_FAILED: 'Processing failed; it can be retried.',
  ANALYSIS_ERROR: 'The comparison could not be finished; it can be retried.',
  WAITING_FOR_PREVIOUS_ANALYSIS: 'Waiting for the previous week’s analysis to finish.',
  // composite score (cognitive_index_v1)
  MISSING_DOMAIN: 'At least one of the three task results is unavailable, so no composite is shown.',
  INVALID_DOMAIN_VALUE: 'A task result is outside the range this score version can use.',
  UNSUPPORTED_PROTOCOL: 'This check-in used a task or scoring version the score version does not cover.',
  // quality: incomplete
  INCOMPLETE_ASSESSMENT: 'Not every activity was finished.',
  LOW_QUALITY: 'A quality rule was not met.',
  TASK_NOT_COMPLETED: 'The activity was not finished.',
  NOT_ALL_TRIALS_PRESENTED: 'The activity stopped before all items were shown.',
  MEMORY_SKIPPED: 'Word memory was skipped.',
  MEMORY_STOPPED: 'Word memory was stopped early.',
  ATTENTION_SKIPPED: 'Shapes was skipped.',
  ATTENTION_STOPPED: 'Shapes was stopped early.',
  REACTION_SKIPPED: 'GO was skipped.',
  REACTION_STOPPED: 'GO was stopped early.',
  // quality: LOW flags
  INTERRUPTION: 'The screen was hidden or paused during the activity.',
  TRIAL_INTERRUPTED: 'At least one trial was interrupted.',
  EXPOSURE_TIMING_DEVIATION: 'Word display time was more than 1 s off the protocol.',
  DISTRACTOR_TIMING_DEVIATION: 'The delay before recall was more than 1 s off the protocol.',
  RECALL_TIMING_DEVIATION: 'Recall time exceeded the protocol limit.',
  TIMING_DEVIATION: 'Shape or gap timing exceeded the protocol tolerance.',
  TIMER_INTERRUPTION: 'GO timing exceeded the protocol tolerance.',
  INPUT_MODE_CHANGED: 'The answering method changed during a timed activity.',
  ANSWER_ASSISTANCE: 'Someone helped answer this activity.',
  ASSISTANCE_UNCERTAIN: 'It is uncertain whether someone helped answer.',
  RT_TIMEOUT_PRESENT: 'At least one GO trial had no response within 3 s.',
  INSUFFICIENT_USABLE_TRIALS: 'Fewer than eight usable GO responses.',
  RESPONSE_OVERFLOW: 'Too many responses were recorded for a trial.',
  TELEMETRY_OVERFLOW: 'Too many telemetry events were recorded.',
  // warnings (quality stays VALID)
  FALSE_START_PRESENT: 'One or two presses before GO.',
  ANTICIPATORY_PRESENT: 'One or two responses under 100 ms.',
  NO_RESPONSES: 'No presses in this activity.',
  ALL_RESPONSES: 'A press for every shape.',
  BLUR_OBSERVED: 'Another window may briefly have had focus.',
  PRACTICE_REPEATED: 'The practice block was repeated.',
  CLIENT_OUTCOME_MISMATCH: 'Browser and server classified an item differently; the server result was used.',
}

/** Readable text for a backend reason code; unmapped codes stay visible with a neutral fallback. */
export function reasonText(code: string): string {
  return REASON_TEXT[code] ?? `Unrecognized reason code (${code}); see technical details.`
}

export const CONDITION_TEXT: Record<string, string> = {
  MAX_AT_OR_ABOVE_R: 'Largest domain deviation reached the review threshold (r)',
  'AGGREGATE_AT_OR_ABOVE_0.8R': 'Mean of the two largest deviations reached 0.8 × r',
  MAX_AT_OR_ABOVE_2R: 'Largest domain deviation reached 2 × r',
  TWO_OR_MORE_DOMAINS_AT_OR_ABOVE_R: 'Two or more domains reached r',
}

export const AGGREGATE_METHOD_TEXT: Record<string, string> = {
  mean_top_two_v1: 'Mean of the two largest directional deviations (mean_top_two_v1)',
}
