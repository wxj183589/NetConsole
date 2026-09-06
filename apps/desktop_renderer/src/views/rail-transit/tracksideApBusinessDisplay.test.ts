import { describe, expect, it } from 'vitest'

import {
  displayLldpStatus,
  formatOpticalEventStatus,
  displayTracksideApReason,
  displayTracksideApRecognitionStatus,
  displaySwitchVendor,
  displayTracksideSnapshotTime,
  displayTracksideValue,
  tracksideApOpticalPresentation,
  tracksideApDeviceOpticalPresentation,
  tracksideApBusinessOpticalPresentation,
  tracksideBusinessOpticalPresentation,
  tracksideDeviceOpticalPresentation,
  tracksideApRecognitionPresentation,
  tracksideOpticalPresentation,
  tracksideRxPresentation,
} from './tracksideApBusinessDisplay'

describe('trackside AP business display', () => {
  it.each([
    ['OPEN', '未恢复'],
    ['RESOLVED', '已恢复'],
  ])('formats optical event status %s as %s', (status, label) => {
    expect(formatOpticalEventStatus(status)).toBe(label)
  })

  it('does not expose unknown optical event status values', () => {
    expect(formatOpticalEventStatus('INTERNAL_UNKNOWN')).toBe('未知')
    expect(formatOpticalEventStatus(null)).toBe('未知')
  })

  it.each([
    ['normal', '正常', 'success'],
    ['notice', '偏低关注', 'warning'],
    ['warning', '提示告警', 'warning'],
    ['alarm', '一般告警', 'danger'],
    ['link_abnormal', '链路异常', 'danger'],
    ['link_down', '链路断开', 'danger'],
    ['no_light', '无光', 'danger'],
    ['no_module', '无光模块', 'info'],
    ['abnormal', '光衰大', 'danger'],
    ['unverified', '状态未知/第三方模块', 'warning'],
    ['dom_unavailable', '不支持 DOM', 'info'],
    ['skipped', '未检查', 'info'],
    ['not_collected', '光诊断未采集', 'info'],
    ['unknown', '未知', 'info'],
    ['offline', '离线', 'danger'],
    ['collection_failed', '采集失败/设备不可达', 'warning'],
  ])('maps %s to a Chinese label and explicit color', (status, label, tagType) => {
    expect(tracksideOpticalPresentation(status)).toMatchObject({ label, tagType })
  })

  it('does not fabricate missing values or alias unknown statuses', () => {
    expect(tracksideOpticalPresentation(null).label).toBe('—')
    expect(tracksideOpticalPresentation('vendor_state').label).toBe('vendor_state')
    expect(displayTracksideValue(null)).toBe('—')
    expect(displayTracksideValue(0)).toBe('0')
  })

  it('formats ZTE vendor and LLDP verification semantics', () => {
    expect(displaySwitchVendor('ZTE')).toBe('中兴 ZTE')
    expect(displayLldpStatus('SAMPLE_REQUIRED')).toBe('待真实样本验证')
  })

  it('keeps configured empty ports neutral and explains unidentified reasons', () => {
    expect(displayTracksideApRecognitionStatus('unidentified')).toBe('未识别')
    expect(displayTracksideApReason('EMPTY_CONFIGURED_PORT')).toBe('空闲/未接 AP')
    expect(displayTracksideApReason('LLDP_STALE')).toBe('LLDP 数据过旧')
    expect(tracksideApRecognitionPresentation('unidentified')).toMatchObject({
      label: '未识别',
      tagType: 'info',
    })
    expect(tracksideApRecognitionPresentation('identified')).toMatchObject({
      label: '已识别',
      tagType: 'success',
    })
  })

  it('marks stale switch snapshots without presenting them as current', () => {
    expect(displayTracksideSnapshotTime('2026-08-03T10:00:00+08:00', 'stale')).toBe(
      '历史数据 · 2026-08-03T10:00:00+08:00',
    )
    expect(displayTracksideSnapshotTime('2026-08-03T10:00:00+08:00', 'current')).toBe(
      '2026-08-03T10:00:00+08:00',
    )
  })

  it('uses the fixed receive threshold even when the switch backend status is normal', () => {
    expect(tracksideRxPresentation('-19.10', 'normal')).toMatchObject({
      label: '光衰大',
      tagType: 'danger',
      className: 'optical-alarm',
    })
    expect(tracksideBusinessOpticalPresentation({
      optical_severity: 'abnormal',
    })).toMatchObject({ label: '光衰大', tagType: 'danger' })
  })

  it.each([
    ['abnormal', '-8.00', '光衰大'],
    ['normal', '-20.00', '正常'],
  ])('uses backend AP business status %s even when Rx is %s', (backendStatus, rxPower, label) => {
    expect(tracksideApBusinessOpticalPresentation({
      ap_business_optical_status: backendStatus,
      ap_rx_power: rxPower,
      ap_optical_data_freshness: 'current',
    })).toMatchObject({ label })
    expect(tracksideApDeviceOpticalPresentation({
      ap_rx_power: rxPower,
      ap_device_optical_status: 'warning',
      ap_optical_status: backendStatus,
      ap_business_optical_status: backendStatus,
      ap_optical_data_freshness: 'fresh',
    })).toMatchObject({ label })
  })

  it('keeps stale AP canonical status visibly historical instead of current', () => {
    expect(tracksideApOpticalPresentation('abnormal', 'stale')).toMatchObject({
      label: '光衰大（数据已过期）',
      tagType: 'warning',
    })
  })

  it('keeps the existing no-module semantic ahead of a dirty AP Rx value', () => {
    expect(tracksideApDeviceOpticalPresentation({
      ap_device_optical_status: 'no_module',
      ap_optical_status: 'abnormal',
      ap_business_optical_status: 'abnormal',
      ap_optical_data_freshness: 'current',
    }).label).toBe('无光模块')
  })

  it('keeps collection failure ahead of a canonical abnormal status', () => {
    expect(tracksideApOpticalPresentation('abnormal', 'collection_failed').label).toBe(
      '采集失败/设备不可达',
    )
  })

  it('does not expose legacy AP alarm levels without a backend canonical status', () => {
    expect(tracksideApDeviceOpticalPresentation({
      ap_device_optical_status: 'critical',
      ap_optical_data_freshness: 'fresh',
    }).label).toBe('未知')
    expect(tracksideApOpticalPresentation('minor', 'fresh').label).toBe('未知')
  })

  it('keeps historical power visible while marking a failed switch collection', () => {
    expect(tracksideRxPresentation('-8.00', 'collection_failed', 'stale')).toMatchObject({
      label: '采集失败/设备不可达（数据已过期）',
      tagType: 'warning',
    })
    expect(tracksideBusinessOpticalPresentation({
      optical_severity: 'collection_failed',
      switch_optical_data_status: 'stale',
    })).toMatchObject({
      label: '采集失败/设备不可达（数据已过期）',
      tagType: 'warning',
    })
  })

  it('keeps WA6522 out of both side and combined optical alarms', () => {
    expect(tracksideRxPresentation('-30', 'critical', 'fresh', 'wa6522')).toMatchObject({
      label: '不适用',
      tagType: 'info',
    })
    expect(tracksideBusinessOpticalPresentation({
      optical_severity: 'not_applicable',
    }).label).toBe('不适用')
    expect(tracksideDeviceOpticalPresentation('critical', 'wa6522').label).toBe('不适用')
  })
})
