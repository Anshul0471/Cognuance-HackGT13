import { expect, test, type Page } from '@playwright/test'
import { clientNavigate, e2eEnv, fixture, signIn } from './helpers'

/**
 * Patient save + alert handoff (guide 07 §6.4): the real rendered tasks at their real protocol
 * durations, answered with trusted keyboard input in a visible (headless, unthrottled) page.
 * Answers are deliberately weaker than this fictional patient's history, but every task is
 * completed normally (no interruptions, no skipped trials): whether an alert results is decided by
 * the stored forecast and policy, never by the test.
 */

const env = e2eEnv()
const patient = env.livePatient

type Outcome = { circlesAnswered: number; falseAlarms: number; goResponses: number }

async function heading(page: Page): Promise<string> {
  return ((await page.locator('h1').first().textContent({ timeout: 30_000 })) ?? '').trim()
}

/** Resolve with the stimulus label once it differs from `previous` ('__gone__' when the task ends). */
function nextLabel(page: Page, region: string, previous: string | null): Promise<string> {
  return page.evaluate(
    ({ region, previous }) =>
      new Promise<string>((resolve) => {
        const area = [...document.querySelectorAll('[role=region],[role=button]')].find(
          (el) => el.getAttribute('aria-label') === region,
        )
        const img = area?.querySelector('[role=img]')
        if (!img) return resolve('__gone__')
        const timer = setTimeout(() => {
          observer.disconnect()
          resolve(document.contains(img) ? '__timeout__' : '__gone__')
        }, 9000)
        const check = () => {
          const label = img.getAttribute('aria-label') ?? ''
          if (label !== previous) {
            observer.disconnect()
            clearTimeout(timer)
            resolve(label)
          }
        }
        const observer = new MutationObserver(check)
        observer.observe(img, { attributes: true, attributeFilter: ['aria-label'] })
        check()
      }),
    { region, previous },
  )
}

async function shapes(page: Page, practice: boolean, out: Outcome) {
  await page.getByRole('region', { name: 'Shapes (press Space for circles)' }).waitFor()
  let label: string | null = null
  let circles = 0
  let squares = 0
  for (;;) {
    label = await nextLabel(page, 'Shapes (press Space for circles)', label)
    if (label === '__gone__') return
    if (label === '__timeout__') continue
    if (label === 'Circle') {
      circles += 1
      // Practice: answer every circle. Real task: answer every other circle.
      if (practice || circles % 2 === 1) {
        await page.waitForTimeout(250)
        await page.keyboard.press('Space')
        if (!practice) out.circlesAnswered += 1
      }
    } else if (label === 'Square' && !practice) {
      squares += 1
      if (squares <= 4) {
        await page.waitForTimeout(250)
        await page.keyboard.press('Space') // a few false alarms on the real task
        out.falseAlarms += 1
      }
    }
  }
}

async function go(page: Page, practice: boolean, out: Outcome) {
  await page.getByRole('region', { name: 'GO signal (press Space)' }).waitFor()
  let label: string | null = null
  for (;;) {
    label = await nextLabel(page, 'GO signal (press Space)', label)
    if (label === '__gone__') return
    if (label === 'GO') {
      await page.waitForTimeout(practice ? 350 : 900) // slower, still well inside the 3 s window
      await page.keyboard.press('Space')
      if (!practice) out.goResponses += 1
    }
  }
}

test('patient check-in with real tasks, lost-response retry, and doctor alert handoff', async ({ browser }) => {
  test.setTimeout(15 * 60_000)
  const out: Outcome = { circlesAnswered: 0, falseAlarms: 0, goResponses: 0 }

  // The doctor is already signed in, in a separate context, watching the unresolved inbox.
  const doctorContext = await browser.newContext()
  const doctor = await doctorContext.newPage()
  await signIn(doctor, env.presenter)
  await clientNavigate(doctor, '/doctor/alerts')
  await expect(doctor.getByRole('heading', { name: 'Alerts' })).toBeVisible()
  await expect(doctor.getByText(patient.display_name)).toHaveCount(0)

  const patientContext = await browser.newContext()
  const page = await patientContext.newPage()
  await signIn(page, patient)
  await expect(page.getByRole('heading', { name: `Hello, ${patient.display_name}` })).toBeVisible()
  const before = fixture('assessment-count', patient.patient_id).count as number
  await page.getByRole('link', { name: 'Start check-in' }).click()

  let rememberedWord = ''
  let saved = false
  let transitional = 0
  const started = Date.now()
  while (!saved) {
    const title = await heading(page)
    switch (title) {
      case 'Before you start': {
        await page.getByLabel('Keyboard — press the Space bar').check()
        const device = page.getByRole('group', { name: /different device/ })
        if (await device.count()) await device.getByLabel('No').check()
        await page.getByRole('group', { name: /helping you move between screens/ }).getByLabel('No').check()
        await page.getByRole('button', { name: 'Start', exact: true }).click()
        break
      }
      case 'Practice':
        await page.getByRole('button', { name: 'Start practice' }).click()
        break
      case 'Practice: typing words': {
        const words = ((await page.locator('main strong').first().textContent()) ?? '').split(', ')
        await page.getByLabel('Word 1').fill(words[0])
        await page.getByLabel('Word 2').fill(words[1])
        await page.getByRole('button', { name: 'Next' }).click()
        break
      }
      case 'Practice: shapes':
        await page.getByRole('button', { name: 'Ready' }).click() // instructions → trials
        await shapes(page, true, out)
        break
      case 'Practice: GO':
        await page.getByRole('button', { name: 'Ready' }).click() // instructions → trials
        await go(page, true, out)
        break
      case 'Practice finished':
        await page.getByRole('button', { name: 'Start the activities' }).click()
        break
      case 'Word memory':
        await page.getByRole('button', { name: 'Ready' }).click()
        break
      case 'Remember these words':
        rememberedWord = ((await page.getByRole('list', { name: 'Words to remember' }).locator('li').first().textContent()) ?? '').trim()
        await expect(page.getByRole('heading', { name: 'Remember these words' })).toHaveCount(0, { timeout: 30_000 })
        break
      case 'Short wait':
        await expect(page.getByRole('heading', { name: 'Short wait' })).toHaveCount(0, { timeout: 45_000 })
        break
      case 'Type the words you remember':
        await page.getByLabel('Word 1').fill(rememberedWord) // one of six words
        await page.getByRole('button', { name: 'Done' }).click()
        break
      case 'Shapes activity':
        await page.getByRole('button', { name: 'Ready' }).click() // instructions → trials
        await shapes(page, false, out)
        break
      case 'GO activity':
        await page.getByRole('button', { name: 'Ready' }).click() // instructions → trials
        await go(page, false, out)
        break
      case 'Short break':
        await page.getByRole('button', { name: 'Continue' }).click()
        break
      case 'A few questions about today': {
        await page.getByLabel('Hours of sleep').fill('6.5')
        const group = (name: RegExp) => page.getByRole('group', { name })
        await group(/mood/i).getByLabel('6', { exact: true }).check()
        await group(/medication/i).getByLabel('No', { exact: true }).check()
        await group(/Who is answering/).getByLabel('Me (the patient)').check()
        await group(/move between screens/).getByLabel('No').check()
        await group(/enter these answers/).getByLabel('No').check()
        await group(/remember or type the words/).getByLabel('No').check()
        await group(/shapes activity/).getByLabel('No').check()
        await group(/GO activity/).getByLabel('No').check()
        await page.getByRole('button', { name: 'Continue' }).click()
        break
      }
      case 'Review and save': {
        // The first save reaches the server, but its response is lost on the way back.
        let dropped = false
        await page.route('**/api/v1/patient/assessment-sessions/*/submissions', async (route) => {
          if (!dropped) {
            dropped = true
            await route.fetch()
            return route.abort('failed')
          }
          return route.continue()
        })
        await page.getByRole('button', { name: 'Save check-in' }).click()
        await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
        await page.getByRole('button', { name: 'Try again' }).click() // identical frozen body
        break
      }
      case 'Paused':
        throw new Error('A task was interrupted (the page lost focus/visibility): the run is not valid')
      case 'Check-in saved':
        saved = true
        break
      default:
        // Route changes and short loading states (e.g. the home heading right after "Start check-in").
        if ((title === '' || title.startsWith('Hello,')) && transitional++ < 60) {
          await page.waitForTimeout(250)
          break
        }
        throw new Error(`Unexpected screen "${title}": ${(await page.locator('main').innerText()).slice(0, 400)}`)
    }
  }
  const taskMinutes = (Date.now() - started) / 60_000
  test.info().annotations.push({ type: 'task-duration-min', description: taskMinutes.toFixed(1) })

  // The patient sees only a calm receipt — no score, level, or doctor note.
  const receipt = await page.locator('main').innerText()
  expect(receipt).not.toMatch(/deviation|HIGH|REVIEW|\/ 100|points/i)

  // Server record: exactly one new assessment despite the retry; genuinely analysed.
  expect(fixture('assessment-count', patient.patient_id).count).toBe(before + 1)
  const stored = fixture('latest-analysis', patient.patient_id) as Record<string, string | null>
  test.info().annotations.push({ type: 'stored-result', description: JSON.stringify(stored) })
  expect(stored.source).toBe('LIVE_DEMO')
  expect(stored.quality).toBe('VALID')
  expect(stored.availability).toBe('COMPLETE') // forecast frozen before the tasks, compared after

  // Handoff: the doctor's open inbox shows the persisted alert on its normal poll.
  const t0 = Date.now()
  expect(stored.alert_id, `analysis was ${stored.deviation_level}; no alert to hand off`).not.toBeNull()
  await expect(doctor.getByText(patient.display_name).first()).toBeVisible({ timeout: 30_000 })
  test.info().annotations.push({ type: 'doctor-visibility-s', description: ((Date.now() - t0) / 1000).toFixed(1) })
  await doctor.getByRole('link', { name: new RegExp(`Open review.*${patient.display_name}|Open review`) }).first().click()
  await expect(doctor.getByRole('heading', { name: 'Unexpected performance change — clinical review requested' })).toBeVisible()
  await expect(doctor.getByText(/Below forecast by/)).toBeVisible()
  console.log(`tasks ${taskMinutes.toFixed(1)} min, answers ${JSON.stringify(out)}, stored ${JSON.stringify(stored)}`)
})
