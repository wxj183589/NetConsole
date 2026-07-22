import { describe, expect, it } from 'vitest'

import { formatOpticalPower, opticalValuePresentation } from './opticalPresentation'

describe('optical presentation utilities', () => {
  it('formats optical power without fabricating missing values', () => {
    expect(formatOpticalPower('-19.75')).toBe('-19.75 dBm')
    expect(formatOpticalPower('-8.63 dBm')).toBe('-8.63 dBm')
    expect(formatOpticalPower('')).toBe('--')
    expect(formatOpticalPower('--')).toBe('--')
  })

  it('keeps stale abnormal values out of the current danger tone', () => {
    expect(opticalValuePresentation('normal', 'fresh').className).toBe('optical-value-normal')
    expect(opticalValuePresentation('alarm', 'fresh').className).toBe('optical-value-danger')
    expect(opticalValuePresentation('alarm', 'stale').className).toBe('optical-value-stale')
    expect(opticalValuePresentation('unknown', 'stale').className).toBe('optical-value-muted')
  })
})
