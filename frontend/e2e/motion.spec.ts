import { expect, test, type Page } from '@playwright/test'
import { clientNavigate, e2eEnv, signIn } from './helpers'

const env = e2eEnv()

/** Count Web Animations started on Recharts layers (the entrance never touches data). */
async function countChartAnimations(page: Page) {
  await page.addInitScript(() => {
    const original = Element.prototype.animate
    ;(window as unknown as { __chartAnimations: number }).__chartAnimations = 0
    Element.prototype.animate = function (...args: Parameters<Element['animate']>) {
      if (this.closest?.('svg.recharts-surface')) (window as unknown as { __chartAnimations: number }).__chartAnimations++
      return original.apply(this, args)
    }
  })
}
const chartAnimations = (page: Page) => page.evaluate(() => (window as unknown as { __chartAnimations: number }).__chartAnimations)

test('charts rise from the zero baseline once per view entry; polling does not replay it', async ({ page }) => {
  await countChartAnimations(page)
  await signIn(page, env.presenter)
  await clientNavigate(page, `/doctor/patients/${env.steady.patient_id}`)
  // Sample the line layer while the entrance runs: a real intermediate vertical scale is observed.
  const scales = await page.evaluate(async () => {
    const seen: number[] = []
    const t0 = performance.now()
    while (performance.now() - t0 < 2500) {
      const layer = document.querySelector('svg.recharts-surface g[class*="recharts-zIndex-layer_400"]')
      if (layer) {
        const m = getComputedStyle(layer).transform
        const match = m.match(/^matrix\(([^)]+)\)$/)
        seen.push(match ? Number(match[1].split(',')[3]) : 1)
      }
      await new Promise((r) => requestAnimationFrame(r))
    }
    return seen
  })
  expect(scales.some((s) => s > 0.02 && s < 0.98)).toBe(true) // mid-rise geometry
  expect(scales.at(-1)).toBe(1) // settled at the real values
  const afterEntrance = await chartAnimations(page)
  expect(afterEntrance).toBeGreaterThan(0)
  await page.waitForTimeout(12_000) // one visible-page poll (≈10 s) later…
  expect(await chartAnimations(page)).toBe(afterEntrance) // …no replay
})

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' })
  test('renders final values immediately', async ({ page }) => {
    await countChartAnimations(page)
    await signIn(page, env.presenter)
    await clientNavigate(page, `/doctor/patients/${env.steady.patient_id}`)
    await expect(page.getByRole('heading', { name: 'Reaction time' })).toBeVisible()
    await page.waitForTimeout(1500)
    expect(await chartAnimations(page)).toBe(0)
  })
})

test.describe('responsive, light, keyboard', () => {
  test.use({ viewport: { width: 390, height: 844 }, colorScheme: 'dark' })
  test('390 px layouts fit, the theme stays light under a dark OS preference, skip link first', async ({ page }) => {
    await page.goto('/')
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused()
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    const [r, g, b] = (bg.match(/\d+/g) ?? []).map(Number)
    expect(Math.min(r, g, b)).toBeGreaterThan(200) // light surface, no dark theme
    await signIn(page, env.presenter)
    for (const path of ['/doctor', '/doctor/patients', `/doctor/patients/${env.abrupt.patient_id}`, '/doctor/alerts']) {
      await clientNavigate(page, path)
      await page.waitForTimeout(800)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, path).toBeLessThanOrEqual(0)
    }
    await page.getByRole('button', { name: 'Open menu' }).click()
    await page.locator('#doctor-mobile-nav').getByRole('link', { name: /Patients/ }).click()
    await expect(page.locator('#doctor-mobile-nav')).toHaveCount(0)
  })
})
