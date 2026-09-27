import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { InputMode } from './types'
import { BigButton, Screen } from './ui'

export type PreparationChoices = {
  input_mode: InputMode
  device_changed: boolean
  navigation_assistance: boolean
}

const prefersTouch = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches

export function Preparation({
  firstCheckIn,
  extra,
  busy,
  error,
  onStart,
}: {
  firstCheckIn: boolean
  extra: boolean
  busy: boolean
  error: string | null
  onStart: (choices: PreparationChoices) => void
}) {
  const [mode, setMode] = useState<InputMode>(prefersTouch() ? 'pointer' : 'keyboard')
  const [deviceChanged, setDeviceChanged] = useState<boolean | null>(firstCheckIn ? false : null)
  const [helper, setHelper] = useState<boolean | null>(null)
  const [needsFormat, setNeedsFormat] = useState(false)
  const ready = deviceChanged !== null && helper !== null

  const radio = (name: string, checked: boolean, onChange: () => void, label: string) => (
    <label className="flex min-h-12 cursor-pointer items-center gap-3 rounded-lg border-2 border-slate-300 bg-white px-4 has-[:checked]:border-indigo-700 has-[:checked]:bg-indigo-50">
      <input type="radio" name={name} checked={checked} onChange={onChange} className="h-5 w-5" />
      {label}
    </label>
  )

  if (needsFormat) {
    return (
      <Screen title="Other formats">
        <p>
          In this version the activities are only available in English, on screen. Audio or read-aloud versions
          are not available yet, because they would need their own tested version of the activities.
        </p>
        <Link to="/patient" className="text-lg font-semibold text-indigo-800 underline">
          Back to home
        </Link>
      </Screen>
    )
  }

  return (
    <Screen title={extra ? 'Extra check-in' : 'Before you start'}>
      <p>
        These short activities help record changes over time. They are not a diagnosis. Use a quiet place and, when
        possible, the same device and response method.
      </p>
      {extra && (
        <p className="rounded-lg bg-amber-50 p-4">
          This check-in is outside your weekly schedule. It will be saved, but not used for weekly comparison.
        </p>
      )}
      <p>
        It takes about 5 minutes: a short practice, then a word activity, a shapes activity and a GO activity, and
        a few questions. Activities are in English.
      </p>

      <fieldset className="space-y-2">
        <legend className="text-lg font-semibold">How will you answer the timed activities?</legend>
        {radio('mode', mode === 'keyboard', () => setMode('keyboard'), 'Keyboard — press the Space bar')}
        {radio('mode', mode === 'pointer', () => setMode('pointer'), 'Touch or mouse — press a large box on screen')}
        <p className="text-base text-slate-600">Please keep the same way of answering for the whole check-in.</p>
      </fieldset>

      {!firstCheckIn && (
        <fieldset className="space-y-2">
          <legend className="text-lg font-semibold">
            Are you using a different device, or a different way of answering, than last time?
          </legend>
          {radio('device', deviceChanged === true, () => setDeviceChanged(true), 'Yes')}
          {radio('device', deviceChanged === false, () => setDeviceChanged(false), 'No')}
        </fieldset>
      )}

      <fieldset className="space-y-2">
        <legend className="text-lg font-semibold">Is someone helping you move between screens today?</legend>
        {radio('helper', helper === true, () => setHelper(true), 'Yes')}
        {radio('helper', helper === false, () => setHelper(false), 'No')}
        <p className="text-base text-slate-600">
          Help moving between screens is fine. Please don't have anyone remember words or press buttons for you.
        </p>
      </fieldset>

      {error && (
        <p role="alert" className="rounded-lg bg-rose-50 p-4 text-rose-900">
          {error}
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <BigButton
          disabled={!ready || busy}
          onClick={() =>
            onStart({ input_mode: mode, device_changed: deviceChanged ?? false, navigation_assistance: helper ?? false })
          }
        >
          {busy ? 'Starting…' : 'Start'}
        </BigButton>
        <BigButton variant="secondary" onClick={() => setNeedsFormat(true)}>
          I need a different format
        </BigButton>
      </div>
    </Screen>
  )
}
