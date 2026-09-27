export const NOTE_MAX = 4000

/** The backend limits the trimmed note to 4000 characters counted as Unicode code points. */
export function noteLength(text: string): number {
  return [...text.trim()].length
}
