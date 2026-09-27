import { expect, test, type Browser, type Page } from '@playwright/test'
import { e2eEnv, fixture, signIn } from './helpers'

const env = e2eEnv()
const alertId = env.abrupt.analysis.alert.alert_id
const alertPath = `/doctor/alerts/${alertId}`

async function doctorPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext() // separate authenticated context (memory-only token)
  const page = await context.newPage()
  await signIn(page, env.presenter, alertPath) // deep link → sign-in → back to the alert
  await expect(page.getByRole('heading', { name: /Alert review:/ })).toBeVisible()
  return page
}

test('review lifecycle with a lost response, a stale second reviewer, and reauthentication', async ({ browser }) => {
  const a = await doctorPage(browser)
  const b = await doctorPage(browser) // loaded at lock version 1, before A acts
  for (const page of [a, b]) {
    await expect(page.getByRole('heading', { name: 'Unexpected performance change — clinical review requested' })).toBeVisible()
  }
  expect(fixture('alert-events', alertId).count).toBe(1) // opening the prompt recorded nothing

  // A: the acknowledgement reaches the server but its response is lost.
  let dropped = false
  await a.route('**/api/v1/doctor/alerts/*/events', async (route) => {
    if (route.request().method() === 'POST' && !dropped) {
      dropped = true
      await route.fetch() // the server commits…
      return route.abort('failed') // …but the browser never sees the reply
    }
    return route.continue()
  })
  await a.getByRole('button', { name: 'Acknowledge' }).click()
  await expect(a.getByText(/could not be confirmed/)).toBeVisible()
  await a.getByRole('button', { name: 'Retry the same request' }).click()
  await expect(a.getByText('Acknowledged').first()).toBeVisible()
  expect(fixture('alert-events', alertId).count).toBe(2) // CREATED + one ACKNOWLEDGED, no duplicate

  // B still holds version 1: its action is rejected as stale and its draft is kept.
  await b.getByLabel(/Acknowledgment note/).fill('Second reviewer draft')
  await b.getByRole('button', { name: 'Acknowledge' }).click()
  await expect(b.getByText(/Another update was made to this alert/)).toBeVisible()
  expect(fixture('alert-events', alertId).count).toBe(2)

  // A: note, then resolve with a required note.
  await a.getByLabel(/Review note/).fill('Reviewed the task evidence and recent history.')
  await a.getByRole('button', { name: 'Add note' }).click()
  await expect(a.getByText('Reviewed the task evidence and recent history.').first()).toBeVisible()
  await a.getByRole('button', { name: /Resolve/ }).first().click()
  await a.getByLabel(/Resolution note/).fill('Follow-up discussion planned; no further review needed for this check-in.')
  await a.getByRole('button', { name: 'Resolve alert' }).click()
  await expect(a.getByRole('heading', { name: 'Clinical review completed' })).toBeVisible()
  expect(fixture('alert-events', alertId).count).toBe(4)

  // Reauthenticate in a fresh context: persisted state, history and the historical chart marker.
  const c = await doctorPage(browser)
  await expect(c.getByRole('heading', { name: 'Clinical review completed' })).toBeVisible()
  await expect(c.getByText('Follow-up discussion planned; no further review needed for this check-in.').first()).toBeVisible()
  await c.getByRole('link', { name: 'Open assessment history' }).click()
  await expect(c.getByText('Large change flagged').first()).toBeVisible()
})
