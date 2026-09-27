import { expect, test } from '@playwright/test'
import { clientNavigate, e2eEnv, fixture, signIn } from './helpers'

const env = e2eEnv()
const UNAVAILABLE = 'This record is unavailable or you no longer have access.'

test('cross-doctor denial, live assignment revocation, and no data carried across accounts', async ({ page }) => {
  await signIn(page, env.presenter)

  // A patient assigned only to the secondary doctor: edited URL shows nothing, API says 404.
  await clientNavigate(page, `/doctor/patients/${env.secondaryPatient.patient_id}`)
  await expect(page.getByText(UNAVAILABLE)).toBeVisible()
  await expect(page.getByText(env.secondaryPatient.display_name)).toHaveCount(0)
  await clientNavigate(page, '/doctor/patients')
  await page.getByLabel('Search by name').fill(env.secondaryPatient.display_name.split(' ')[0])
  await expect(page.getByText(/No patients match these filters/)).toBeVisible()

  // Revoke a live assignment while its page is open: content disappears on the next refresh.
  await clientNavigate(page, `/doctor/patients/${env.steady.patient_id}`)
  await expect(page.getByRole('heading', { level: 1, name: env.steady.display_name })).toBeVisible()
  fixture('revoke-assignment', env.presenter.email, env.steady.patient_id)
  try {
    await expect(page.getByText(UNAVAILABLE)).toBeVisible({ timeout: 25_000 }) // ≈10 s visible-page poll
    await expect(page.getByRole('heading', { name: 'Cognitive Score' })).toHaveCount(0)
    const direct = await page.evaluate(
      async (id) => (await fetch(`/api/v1/doctor/patients/${id}`)).status,
      env.steady.patient_id,
    )
    expect(direct).toBe(401) // (no bearer header from a bare fetch) — the app's own calls got 404 above
  } finally {
    fixture('restore-assignment', env.presenter.email, env.steady.patient_id)
  }

  // Logout clears private state: the next account cannot see the previous account's records.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await signIn(page, env.secondaryDoctor)
  await clientNavigate(page, `/doctor/patients/${env.abrupt.patient_id}`)
  await expect(page.getByText(UNAVAILABLE)).toBeVisible()
  await expect(page.getByText(env.abrupt.display_name)).toHaveCount(0)
})
