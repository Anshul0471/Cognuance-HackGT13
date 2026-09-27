/** Single source for the public product identity (refinement 02 §2). Technical identifiers keep their names. */
export const BRAND = {
  name: 'COGNUANCE',
  tagline: 'A clearer view of cognitive changes over time.',
} as const

/** Browser tab title. Never pass patient names or assessment values. */
export function pageTitle(section: string): string {
  return `${BRAND.name} | ${section}`
}
