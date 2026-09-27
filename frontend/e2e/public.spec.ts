import { expect, test } from '@playwright/test'
import { e2eEnv, signIn } from './helpers'

const env = e2eEnv()

test('public entry: landing → About → sign-in → role home, deep link recovery, logout', async ({ page }) => {
  const apiCalls: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('/api/')) apiCalls.push(r.url())
  })
  await page.goto('/')
  await expect(page.getByText('Welcome to COGNUANCE')).toBeVisible()
  await expect(page).toHaveTitle('COGNUANCE | Welcome')
  await page.getByRole('link', { name: 'About', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'About COGNUANCE' })).toBeVisible()
  expect(apiCalls).toEqual([]) // public pages never request private data

  await page.getByRole('link', { name: 'Sign in' }).first().click()
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  await signIn(page, env.presenter, '/login')
  await expect(page).toHaveURL(/\/doctor$/)
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()

  // Protected deep link while signed out → sign-in → back to the same page (role from the backend).
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('status')).toContainText('You have signed out')
  await page.goto('/doctor/insights')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('Email').fill(env.presenter.email)
  await page.getByLabel('Password', { exact: true }).fill(env.presenter.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/doctor\/insights$/)
  await expect(page.getByRole('heading', { name: 'Visual Insights' })).toBeVisible()

  // Memory-only token: nothing is written to browser storage.
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})
