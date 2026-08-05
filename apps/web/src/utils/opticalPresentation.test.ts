import { describe, expect, it } from 'vitest'

import {
  apOpticalStatusPresentation,
  dualOpticalReason,
  dualOpticalStatusPresentation,
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

  it('marks the combined status abnormal when only switch Rx is below the fixed threshold', () => {
    const input = {
      apBackendStatus: 'normal',
      apRxPower: '-7.72',
      switchBackendStatus: 'normal',
      switchRxPower: '-19.10',
    }
    const presentation = dualOpticalStatusPresentation(input)

    expect(presentation.ap.status).toBe('normal')
    expect(presentation.switch.status).toBe('abnormal')
    expect(presentation.overall).toMatchObject({ status: 'abnormal', tagType: 'danger' })
    expect(dualOpticalReason(input)).toContain('交换机侧收光异常：-19.10 dBm，低于 -13.90 dBm')
    expect(dualOpticalReason(input)).toContain('AP 侧收光正常：-7.72 dBm')
  })

  it.each([
    ['-13.90', '-13.90', 'normal'],
    ['-13.91', '-13.90', 'abnormal'],
    ['-13.90', '-13.91', 'abnormal'],
    ['-13.89', '-13.89', 'normal'],
    ['-13.89', null, 'not_collected'],
  ])('combines AP Rx %s and switch Rx %s as %s', (apRxPower, switchRxPower, status) => {
    expect(dualOpticalStatusPresentation({
      apBackendStatus: 'normal',
      apRxPower,
      switchBackendStatus: 'normal',
      switchRxPower,
    }).overall.status).toBe(status)
  })

  it('keeps both sides not applicable for WA6522', () => {
    const presentation = dualOpticalStatusPresentation({
      apBackendStatus: 'critical',
      apRxPower: '-30',
      switchBackendStatus: 'critical',
      switchRxPower: '-30',
      model: ' WA6522 ',
    })

    expect(presentation.ap.status).toBe('not_applicable')
    expect(presentation.switch.status).toBe('not_applicable')
    expect(presentation.overall.status).toBe('not_applicable')
  })
})
