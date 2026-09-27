import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'

type Account = { email: string; password: string }
export type E2EEnv = {
  baseURL: string
  apiURL: string
  presenter: Account
  rivera: Account
  secondaryDoctor: Account
  livePatient: Account & { display_name: string; patient_id: string; email: string }
  abrupt: { display_name: string; patient_id: string; analysis: { alert: { alert_id: string } } }
  steady: { display_name: string; patient_id: string }
  secondaryPatient: { display_name: string; patient_id: string }
  counts: { assigned: number }
}

/** Private, per-run environment written by tests.e2e.serve_api (mode 600, git-ignored). */
export function e2eEnv(): E2EEnv {
  return JSON.parse(readFileSync(path.join(import.meta.dirname, '.auth', 'env.json'), 'utf8')) as E2EEnv
}

/** Fixture commands run against the isolated E2E database only (no public test endpoints). */
export function fixture(...args: string[]): Record<string, unknown> {
  const out = execFileSync('uv', ['run', 'python', '-m', 'tests.e2e.fixture', ...args], {
    cwd: path.join(import.meta.dirname, '..', '..', 'backend'),
    encoding: 'utf8',
  })
  return JSON.parse(out.trim().split('\n').at(-1) ?? '{}') as Record<string, unknown>
}

/** Log in through the real form (tokens are memory-only, so every context logs in itself). */
export async function signIn(page: Page, account: Account, from = '/login') {
  await page.goto(from)
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login$/)
}

/** Navigate inside the SPA without a reload (a reload would end the in-memory session). */
export async function clientNavigate(page: Page, to: string) {
  await page.evaluate((target) => {
    window.history.pushState({}, '', target)
    window.dispatchEvent(new PopStateEvent('popstate'))
  }, to)
}
