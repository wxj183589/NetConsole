import { describe, expect, it } from 'vitest'

import {
  apOpticalStatusPresentation,
  formatOpticalPower,
  opticalValuePresentation,
} from './opticalPresentation'

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

  it.each([
    ['-17.80', 'abnormal'],
    ['-13.91', 'abnormal'],
    ['-13.90', 'normal'],
    ['-13.89', 'normal'],
  ])('applies the fixed AP business threshold to %s', (rxPower, status) => {
    expect(apOpticalStatusPresentation({ backendStatus: 'normal', rxPower }).status).toBe(status)
  })

  it('does not let a stale backend normal status hide low AP receive power', () => {
    const presentation = apOpticalStatusPresentation({
      backendStatus: 'normal',
      rxPower: '-17.80 dBm',
    })

    expect(presentation.label).toBe('光衰大')
    expect(presentation.tagType).toBe('danger')
  })

  it.each([null, '', '--', 'invalid'])('shows missing or invalid AP receive power as not collected', (rxPower) => {
    expect(apOpticalStatusPresentation({ backendStatus: 'normal', rxPower }).label).toBe('光诊断未采集')
  })

  it('treats WA6522 as not applicable regardless of legacy backend values', () => {
    const presentation = apOpticalStatusPresentation({
      backendStatus: 'critical',
      rxPower: '-30',
      model: ' wa6522 ',
    })

    expect(presentation).toMatchObject({ status: 'not_applicable', label: '不适用', tagType: 'info' })
  })
})
