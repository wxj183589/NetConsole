import { describe, expect, it } from 'vitest'

import { formatDbmValue, formatRssiValue } from './rssiPresentation'

describe('RSSI presentation semantics', () => {
  it('keeps raw device RSSI unitless', () => {
    expect(formatRssiValue(49)).toBe('49')
    expect(formatRssiValue(49.4)).toBe('49')
  })

  it('adds dBm only for explicitly physical-power fields', () => {
    expect(formatDbmValue(-67)).toBe('-67 dBm')
    expect(formatRssiValue(-67)).toBe('-67')
  })
})
