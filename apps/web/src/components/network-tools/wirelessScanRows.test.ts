import { describe, expect, it } from 'vitest'

import { filterWirelessScanRows } from './wirelessScanRows'

describe('wireless scan row filters', () => {
  const rows = [
    { display_ssid: 'CBTC-Mesh', display_ap_name: '轨旁-01', band: '5G', matched_radio_id: 1, matched_trackside_ap: 1 },
    { display_ssid: 'PIS', display_station: '站台', band: '2.4G', matched_radio_id: 2, matched_trackside_ap: 0 },
  ]

  it('combines trackside, band, radio and text filters', () => {
    expect(filterWirelessScanRows(rows, { only_trackside: true, band: '5G', radio: '1', search: '轨旁' })).toEqual([rows[0]])
    expect(filterWirelessScanRows(rows, { only_trackside: false, band: '', radio: '', search: '站台' })).toEqual([rows[1]])
  })
})
