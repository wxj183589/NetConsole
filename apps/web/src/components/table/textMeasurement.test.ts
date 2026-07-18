// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

import { clearTextMeasurementCache, measureTextWidth } from './textMeasurement'

afterEach(() => {
  vi.restoreAllMocks()
  clearTextMeasurementCache()
})

describe('text measurement', () => {
  it('uses rendered glyph widths instead of a character-count constant', () => {
    const measureText = vi.fn((text: string) => ({ width: text === 'MMMM' ? 48 : 12 }))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      font: '',
      measureText,
    } as unknown as CanvasRenderingContext2D)

    expect(measureTextWidth('MMMM')).toBe(48)
    expect(measureTextWidth('iiii')).toBe(12)
  })

  it('keeps Chinese headers measurable when canvas is unavailable', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    const width = measureTextWidth('轨旁 AP 室外侧收光', '14px sans-serif')
    expect(width).toBeGreaterThan(70)
  })
})
