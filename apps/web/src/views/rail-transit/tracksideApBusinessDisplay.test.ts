import { describe, expect, it } from 'vitest'

import {
  displayBidirectionalLoss,
  displayLldpStatus,
  displaySwitchVendor,
  displayTracksideValue,
  tracksideOpticalPresentation,
} from './tracksideApBusinessDisplay'

describe('trackside AP business display', () => {
  it.each([
    ['normal', '正常', 'success'],
    ['notice', '偏低关注', 'warning'],
    ['warning', '提示告警', 'warning'],
    ['alarm', '一般告警', 'danger'],
    ['link_abnormal', '链路异常', 'danger'],
    ['link_down', '链路断开', 'danger'],
    ['no_light', '无光', 'danger'],
    ['no_module', '无光模块', 'info'],
    ['abnormal', '功率异常', 'danger'],
    ['unverified', '状态未知/第三方模块', 'warning'],
    ['dom_unavailable', '不支持 DOM', 'info'],
    ['skipped', '未检查', 'info'],
    ['not_collected', '未采集', 'info'],
    ['unknown', '未知', 'info'],
    ['offline', '离线', 'danger'],
  ])('maps %s to a Chinese label and explicit color', (status, label, tagType) => {
    expect(tracksideOpticalPresentation(status)).toMatchObject({ label, tagType })
  })

  it('does not fabricate missing values or alias unknown statuses', () => {
    expect(tracksideOpticalPresentation(null).label).toBe('—')
    expect(tracksideOpticalPresentation('vendor_state').label).toBe('vendor_state')
    expect(displayTracksideValue(null)).toBe('—')
    expect(displayTracksideValue(0)).toBe('0')
  })

  it('formats ZTE vendor, LLDP verification and bidirectional loss semantics', () => {
    expect(displaySwitchVendor('ZTE')).toBe('中兴 ZTE')
    expect(displayLldpStatus('SAMPLE_REQUIRED')).toBe('待真实样本验证')
    expect(displayBidirectionalLoss('SINGLE_ENDED_ONLY', null, null)).toBe(
      '无法计算（仅有单端光功率）',
    )
    expect(displayBidirectionalLoss('CALCULATED', 5.6, 8.8)).toBe(
      '正向 5.6 dB / 反向 8.8 dB',
    )
  })
})
