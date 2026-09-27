import { createContext, useContext, useLayoutEffect, type RefObject } from 'react'

/**
 * Presentation-only chart entrance (refinement 04 §3–§4).
 *
 * Charts render their final axes, grid and geometry first. The series layers are then revealed with
 * the Web Animations API: each line/bar layer scales vertically about the chart's zero baseline
 * (`display_y = zero_y + p · (final_y − zero_y)` in screen space — x positions never move), markers
 * fade in as the lines settle, donuts/heatmaps/timelines fade in. Nothing touches data, query
 * caches, axis domains, tooltips or tables: those always use the final values, and missing points
 * stay missing because they were never drawn.
 *
 * It runs once per *view entry*: mount, or a change of the surrounding `ChartViewKey` (patient,
 * dates, source). Polls, resizes, hovers and new points do not replay it. Reduced motion, a hidden
 * page, or a browser without WAAPI render the final chart immediately.
 */

export const ENTRANCE_MS = 700
const STAGGER_MS = 40
const MAX_STAGGER_MS = 100
const MARKER_DELAY_MS = 450
const MARKER_MS = 300
const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)'
const PENDING = 'chart-entrance-pending'
const REDUCED = '(prefers-reduced-motion: reduce)'

/** Identifies the data view (e.g. `patient|from|to|source`); a new value means a new entrance. */
export const ChartViewKey = createContext<string>('default')

export type EntranceKind = 'cartesian' | 'zero-line' | 'scatter' | 'pie' | 'html'

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(REDUCED).matches
}

function canAnimate(): boolean {
  return typeof Element !== 'undefined' && typeof Element.prototype.animate === 'function' && !document.hidden
}

/** Pixel y of the value axis' zero (or its minimum) inside the chart SVG. */
function baselineY(svg: SVGSVGElement, kind: EntranceKind): number | null {
  if (kind === 'zero-line') {
    const zero = svg.querySelector('.recharts-reference-line line')
    const y = zero ? Number(zero.getAttribute('y1')) : NaN
    if (Number.isFinite(y)) return y
  }
  const clip = svg.querySelector('clipPath rect')
  if (clip) {
    const y = Number(clip.getAttribute('y')) + Number(clip.getAttribute('height'))
    if (Number.isFinite(y) && y > 0) return y
  }
  const grid = [...svg.querySelectorAll('.recharts-cartesian-grid-horizontal line')]
    .map((line) => Number(line.getAttribute('y1')))
    .filter(Number.isFinite)
  if (grid.length) return Math.max(...grid)
  const axis = svg.querySelector('.recharts-xAxis .recharts-cartesian-axis-line')
  const y = axis ? Number(axis.getAttribute('y1')) : NaN
  return Number.isFinite(y) ? y : null
}

/**
 * Recharts 3 re-creates a series' inner shapes when its data identity changes (e.g. a background
 * refetch right after navigation), but keeps the chart's top-level z-index layer groups for the
 * chart's lifetime. Animating those stable layers means a refetch cannot cut an entrance short.
 */
function stableLayers(svg: SVGSVGElement, selector: string): SVGGElement[] {
  const layers = new Set<SVGGElement>()
  svg.querySelectorAll(selector).forEach((el) => {
    const layer = el.closest<SVGGElement>('g[class*="recharts-zIndex-layer_"]')
    layers.add(layer ?? (el as SVGGElement))
  })
  return [...layers]
}

function run(el: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions, into: Animation[]) {
  into.push(el.animate(keyframes, { easing: EASE_OUT, fill: 'backwards', ...options }))
}

/** Start the entrance if the chart is rendered; returns false to retry on the next frame. */
function startEntrance(root: HTMLElement, kind: EntranceKind, into: Animation[]): boolean {
  const html = [...root.querySelectorAll<HTMLElement>('[data-entrance]')]
  for (const el of html) {
    if (el.dataset.entrance === 'bar-x') {
      el.style.transformOrigin = '0 50%'
      run(el, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: ENTRANCE_MS }, into)
    } else {
      run(el, [{ opacity: 0 }, { opacity: 1 }], { duration: 400 }, into)
    }
  }
  if (kind === 'html') return true

  const svg = root.querySelector<SVGSVGElement>('svg.recharts-surface')
  if (!svg || svg.clientWidth === 0 || svg.clientHeight === 0) return false

  if (kind === 'pie') {
    const pies = stableLayers(svg, '.recharts-pie')
    if (!pies.length) return false
    pies.forEach((pie) => {
      pie.style.transformBox = 'fill-box'
      pie.style.transformOrigin = '50% 50%'
      run(pie, [{ opacity: 0, transform: 'rotate(-90deg) scale(0.9)' }, { opacity: 1, transform: 'none' }], { duration: ENTRANCE_MS }, into)
    })
    return true
  }

  const markers = stableLayers(svg, '.recharts-scatter, .recharts-line-dots, .recharts-reference-dot')
  if (kind === 'scatter') {
    // Markers fade in at their final coordinates (no movement through invented positions).
    if (!markers.length) return false
    markers.forEach((layer) => run(layer, [{ opacity: 0 }, { opacity: 1 }], { duration: 500 }, into))
    return true
  }

  const rising = stableLayers(svg, '.recharts-line .recharts-curve, .recharts-bar-rectangles')
  if (!rising.length && !markers.length) return false
  const base = baselineY(svg, kind)
  if (base === null) return false
  rising.forEach((layer, i) => {
    layer.style.transformBox = 'view-box'
    layer.style.transformOrigin = `0px ${base}px`
    run(
      layer,
      [{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }],
      { duration: ENTRANCE_MS, delay: Math.min(i * STAGGER_MS, MAX_STAGGER_MS) },
      into,
    )
  })
  // Markers (observed dots, forecasts, alert rings) appear as the lines settle, never mid-flight.
  markers.forEach((layer) =>
    run(layer, [{ opacity: 0 }, { opacity: 1 }], { duration: MARKER_MS, delay: rising.length ? MARKER_DELAY_MS : 0 }, into),
  )
  return true
}

/**
 * Attach to the element that wraps one chart. `ready` = usable data is rendered in it.
 * Below-the-fold charts start when they first become visible.
 */
export function useChartEntrance(ref: RefObject<HTMLElement | null>, ready: boolean, kind: EntranceKind = 'cartesian') {
  const viewKey = useContext(ChartViewKey)
  useLayoutEffect(() => {
    const root = ref.current
    if (!root || !ready || prefersReducedMotion() || !canAnimate()) return
    root.classList.add(PENDING) // hide series until the entrance starts (no flash of the final chart)
    const running: Animation[] = []
    let frame = 0
    let tries = 0
    let stopped = false
    let observer: IntersectionObserver | null = null
    const media = window.matchMedia(REDUCED)
    const finish = () => {
      for (const animation of running) animation.finish() // settle at the real values
      root.classList.remove(PENDING)
    }
    const onMotionChange = () => {
      if (media.matches) finish()
    }
    const onVisibility = () => {
      if (document.hidden) finish() // never leave a half-drawn chart behind a hidden tab
    }
    const attempt = () => {
      if (stopped) return
      if (startEntrance(root, kind, running) || ++tries > 90) {
        root.classList.remove(PENDING)
        return
      }
      frame = requestAnimationFrame(attempt)
    }
    media.addEventListener('change', onMotionChange)
    document.addEventListener('visibilitychange', onVisibility)
    if (typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer?.disconnect()
            attempt()
          }
        },
        { threshold: 0.15 },
      )
      observer.observe(root)
    } else {
      attempt()
    }
    return () => {
      stopped = true
      cancelAnimationFrame(frame)
      observer?.disconnect()
      media.removeEventListener('change', onMotionChange)
      document.removeEventListener('visibilitychange', onVisibility)
      finish()
    }
  }, [ref, ready, kind, viewKey])
}
