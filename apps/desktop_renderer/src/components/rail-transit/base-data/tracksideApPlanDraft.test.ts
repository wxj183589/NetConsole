import { describe, expect, it } from 'vitest'
import { sortTracksideAps } from './tracksideApPlanDraft'

describe('sortTracksideAps', () => {
  it('uses formal station order, then switch and natural port order', () => {
    const stations = [
      { id: 'station-2', name: '2号站', sort_order: 2 },
      { id: 'station-1', name: '1号站', sort_order: 1 },
      { id: 'depot', name: '车辆段', sort_order: null, node_type: 'depot' as const },
    ]
    const rows = [
      { id: 'ap-10', station_id: 'station-2', station: '2号站', uplink_switch: 'SW-2', uplink_port: 'GigabitEthernet1/0/1' },
      { id: 'ap-2', station_id: 'station-1', station: '1号站', uplink_switch: 'SW-1', uplink_port: 'GigabitEthernet1/0/10' },
      { id: 'ap-1', station_id: 'station-1', station: '1号站', uplink_switch: 'SW-1', uplink_port: 'GigabitEthernet1/0/2' },
      { id: 'ap-depot', station_id: 'depot', station: '车辆段', uplink_switch: 'SW-0', uplink_port: 'GigabitEthernet1/0/1' },
    ]

    expect(sortTracksideAps(rows, stations).map((row) => row.id)).toEqual([
      'ap-1',
      'ap-2',
      'ap-10',
      'ap-depot',
    ])
  })
})
