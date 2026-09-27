import { ApiError, UNEXPECTED_RESPONSE } from '../../../lib/api'

export const UNAVAILABLE_TEXT = 'This record is unavailable or you no longer have access.'

/** Plain-language cause for a failed read. Never implies anything about the patient's condition. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong while loading this section.'
  if (error.code === UNEXPECTED_RESPONSE)
    return 'The server sent data in an unexpected format, so this section is not shown.'
  if (error.isNetworkError) return 'The server could not be reached. Check the connection and try again.'
  switch (error.status) {
    case 403:
      return 'Access denied. Your account cannot view this record.'
    case 404:
      return UNAVAILABLE_TEXT
    case 400:
      return error.code === 'INVALID_CURSOR'
        ? 'This list changed or expired while paging. Refresh to start again.'
        : (error.detail ?? 'The request was not accepted.')
    case 422:
      return error.code === 'INSIGHTS_RANGE_TOO_LARGE'
        ? (error.detail ?? 'This range has more than 500 assessments. Choose a shorter date range.')
        : (error.detail ?? 'The request was not accepted.')
    case 429:
      return `Too many requests right now.${error.retryAfterSeconds ? ` Try again in ${error.retryAfterSeconds} s.` : ' Try again shortly.'}`
    case 503:
      return 'The service is temporarily unavailable. Saved records are not affected; try again shortly.'
    default:
      return 'The server could not complete this request. Try again shortly.'
  }
}
