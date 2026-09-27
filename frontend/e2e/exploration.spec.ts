import { expect, test } from '@playwright/test'
import { e2eEnv, signIn } from './helpers'

const env = e2eEnv()

test('populated exploration: search, next page, chart stack, Insights selection and comparison', async ({ page }) => {
  await signIn(page, env.presenter)
  await expect(page.getByText('Assigned patients', { exact: true }).first()).toBeVisible()
  await page.getByRole('link', { name: /Assigned patients/ }).first().click()
  await expect(page).toHaveURL(/\/doctor\/patients$/)
  const rows = page.locator('main tbody tr')
  await expect(rows).toHaveCount(20)
  await page.getByRole('button', { name: 'Load more' }).click()
  await expect(rows).toHaveCount(env.counts.assigned) // 25: a second server page, not a client sort

  await page.getByLabel('Search by name').fill(env.abrupt.display_name.split(' ')[0])
  await expect(rows).toHaveCount(1)
  await rows.first().getByRole('link', { name: /View patient/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: env.abrupt.display_name })).toBeVisible()

  // Preserved chart stack: Cognitive Score directly above the three original task charts.
  const order = await page.locator('main h2, main h3').allTextContents()
  const idx = (name: string) => order.findIndex((t) => t.trim() === name)
  expect(idx('Cognitive Score')).toBeGreaterThan(-1)
  expect([idx('Cognitive Score'), idx('Memory task'), idx('Attention task'), idx('Reaction time')]).toEqual(
    [...[idx('Cognitive Score'), idx('Memory task'), idx('Attention task'), idx('Reaction time')]].sort((a, b) => a - b),
  )
  await expect(page.getByText(/−35\.3 points/)).toBeVisible()

  // Separate Visual Insights: complete snapshot, date preset, selection and pinned comparison.
  await page.getByRole('link', { name: /Explore Visual Insights/ }).click()
  await expect(page.getByRole('heading', { name: 'Visual Insights' })).toBeVisible()
  await expect(page.getByText(/assessments? in a complete snapshot/)).toBeVisible()
  for (const panel of ['Domain performance heatmap', 'Change between comparable assessments', 'Score distribution',
    'Context explorer', 'Assessment quality and analysis availability', 'Alert and review timeline']) {
    await expect(page.getByRole('heading', { name: panel })).toBeVisible()
  }
  await page.getByRole('button', { name: 'Last 30 days' }).click()
  await expect(page).toHaveURL(/from=/)
  await page.getByRole('button', { name: 'Last 90 days' }).click()
  await page.getByRole('region', { name: 'Domain heatmap' }).getByRole('button').first().click()
  await expect(page.getByText(/Selected check-in/)).toBeVisible()
  const pin = page.getByRole('button', { name: /Pin/ })
  await pin.first().click()
  await page.getByRole('region', { name: 'Domain heatmap' }).getByRole('button').nth(2).click()
  await page.getByRole('button', { name: /Pin/ }).first().click()
  await expect(page.getByText(/Compare|comparison/i).first()).toBeVisible()
  await expect(page.getByText('Advanced filters')).toBeVisible()

  // Return to the patient without a reload.
  await page.getByRole('link', { name: /assessment history/i }).first().click()
  await expect(page.getByRole('heading', { name: 'Cognitive Score' })).toBeVisible()
})
