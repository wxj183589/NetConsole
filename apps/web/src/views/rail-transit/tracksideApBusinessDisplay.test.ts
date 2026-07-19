import { describe, expect, it } from 'vitest'

import { displayTracksideValue, tracksideOpticalPresentation } from './tracksideApBusinessDisplay'

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
})
