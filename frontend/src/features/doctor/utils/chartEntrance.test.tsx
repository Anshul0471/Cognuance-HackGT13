import { render } from '@testing-library/react'
import { StrictMode, useRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ChartViewKey, ENTRANCE_MS, useChartEntrance } from './chartEntrance'

type Call = { el: Element; keyframes: Keyframe[]; options: KeyframeAnimationOptions; anim: { finish: ReturnType<typeof vi.fn> } }
let calls: Call[] = []
let reduced = false
const motionListeners = new Set<() => void>()

beforeEach(() => {
  calls = []
  reduced = false
  motionListeners.clear()
  Object.defineProperty(Element.prototype, 'animate', {
    configurable: true,
    value: function (this: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions) {
      const anim = { finish: vi.fn() }
      calls.push({ el: this, keyframes, options, anim })
      return anim
    },
  })
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() {
      return query.includes('reduce') && reduced
    },
    addEventListener: (_: string, fn: () => void) => motionListeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => motionListeners.delete(fn),
  }))
  // The fake chart needs a laid-out surface.
  Object.defineProperty(SVGElement.prototype, 'clientWidth', { configurable: true, get: () => 400 })
  Object.defineProperty(SVGElement.prototype, 'clientHeight', { configurable: true, get: () => 220 })
})

afterEach(() => {
  delete (Element.prototype as { animate?: unknown }).animate
  delete (SVGElement.prototype as { clientWidth?: unknown }).clientWidth
  delete (SVGElement.prototype as { clientHeight?: unknown }).clientHeight
  vi.unstubAllGlobals()
})

/** A stand-in for a rendered Recharts line chart: grid bottom at y=200, one line, one marker layer. */
function FakeChart({ values }: { values: number[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useChartEntrance(ref, values.length > 0)
  return (
    <div ref={ref}>
      <svg className="recharts-surface">
        <g className="recharts-cartesian-grid-horizontal">
          <line y1="20" y2="20" />
          <line y1="200" y2="200" />
        </g>
        <g className="recharts-zIndex-layer_400">
          <g className="recharts-line">
            <path className="recharts-curve" d={`M0,${200 - values[0]}L10,${200 - (values[1] ?? 0)}`} />
          </g>
        </g>
        <g className="recharts-zIndex-layer_600">
          <g className="recharts-scatter" data-values={values.join(',')} />
        </g>
      </svg>
    </div>
  )
}

// Recharts keeps its z-index layers stable across re-renders, so those layers are what animate.
const rising = () => calls.filter((c) => c.el.classList.contains('recharts-zIndex-layer_400'))
const markers = () => calls.filter((c) => c.el.classList.contains('recharts-zIndex-layer_600'))

describe('chart entrance', () => {
  it('rises from the zero baseline with fixed x and reveals markers after the line settles', () => {
    render(<FakeChart values={[40, 80]} />)
    expect(rising()).toHaveLength(1)
    const [line] = rising()
    expect(line.keyframes).toEqual([{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }]) // y only
    expect((line.el as SVGElement).style.transformOrigin).toBe('0px 200px')
    expect(line.options.duration).toBe(ENTRANCE_MS)
    expect(markers()[0].options.delay).toBeGreaterThan(0)
    // The data in the DOM is untouched: the path still carries the final geometry.
    expect(line.el.querySelector('path')!.getAttribute('d')).toBe('M0,160L10,120')
  })

  it('does not replay on polls with the same view, but does for a new patient or range', () => {
    const { rerender } = render(
      <ChartViewKey.Provider value="p1|a|b">
        <FakeChart values={[40, 80]} />
      </ChartViewKey.Provider>,
    )
    expect(rising()).toHaveLength(1)
    rerender(
      <ChartViewKey.Provider value="p1|a|b">
        <FakeChart values={[40, 80, 60]} />
      </ChartViewKey.Provider>,
    )
    expect(rising()).toHaveLength(1) // refetch / new point: no second entrance
    rerender(
      <ChartViewKey.Provider value="p2|a|b">
        <FakeChart values={[10, 20]} />
      </ChartViewKey.Provider>,
    )
    expect(rising()).toHaveLength(2)
    expect(rising()[0].anim.finish).toHaveBeenCalled() // the previous view's animation settled first
  })

  it('shows final values immediately under reduced motion and finishes on a mid-animation switch', () => {
    reduced = true
    render(<FakeChart values={[40, 80]} />)
    expect(calls).toHaveLength(0)

    reduced = false
    render(<FakeChart values={[40, 80]} />)
    expect(rising()).toHaveLength(1)
    reduced = true
    motionListeners.forEach((fn) => fn())
    expect(rising()[0].anim.finish).toHaveBeenCalled()
  })

  it('never animates an empty chart and cleans up on unmount (incl. Strict Mode)', () => {
    render(<FakeChart values={[]} />)
    expect(calls).toHaveLength(0)

    const { unmount } = render(
      <StrictMode>
        <FakeChart values={[40, 80]} />
      </StrictMode>,
    )
    // Strict Mode's extra mount/unmount settles the first run before the real one starts.
    const lines = rising()
    expect(lines.slice(0, -1).every((c) => c.anim.finish.mock.calls.length > 0)).toBe(true)
    unmount()
    expect(lines.at(-1)!.anim.finish).toHaveBeenCalled()
  })
})
