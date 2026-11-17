import { afterEach, describe, expect, it } from 'vitest'

import { setAppLocale, t } from '../../i18n/runtime'

const labels = {
  mainline_rows: ['正线', 'Mainline'],
  depot_rows: ['车辆段', 'Depot'],
  parking_yard_rows: ['停车场', 'Parking yard'],
  station_matched_rows: ['正式站点匹配', 'Formal stations matched'],
  station_pending_create_rows: ['待维护站点', 'Stations pending maintenance'],
  station_unmatched_rows: ['站点未匹配', 'Stations unmatched'],
  duplicate_mac_rows: ['MAC重复', 'Duplicate MACs'],
  duplicate_name_rows: ['名称重复', 'Duplicate names'],
  uplink_switch_missing_rows: ['缺少交换机', 'Switch missing'],
  uplink_port_missing_rows: ['缺少端口', 'Port missing'],
} as const

describe('RailTransitBaseDataView AP import statistics locale', () => {
  afterEach(() => setAppLocale('zh_CN'))

  it('keeps Chinese fallbacks and English translations aligned for every statistic', () => {
    setAppLocale('zh_CN')
    for (const [key, [zh]] of Object.entries(labels)) {
      expect(t(`trackside_ap.import.${key}`, zh)).toBe(zh)
    }

    setAppLocale('en_US')
    for (const [key, [, en]] of Object.entries(labels)) {
      expect(t(`trackside_ap.import.${key}`, 'missing')).toBe(en)
    }
  })
})
