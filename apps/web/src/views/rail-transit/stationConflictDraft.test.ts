import { describe, expect, it } from 'vitest'

import type { Station, StationSourceCandidate } from '../../types/railTransitBaseData'
import {
  groupStationOrderConflicts,
  overwriteStationFromSource,
  stationCombinationErrors,
} from './stationConflictDraft'

function station(overrides: Partial<Station> = {}): Station {
  return {
    id: 'station:formal',
    node_uid: 'node-formal',
    name: '小洋江站',
    code: '1',
    line_name: '12号线',
    sort_order: 1,
    ap_count: 2,
    section_count: 2,
    mileage_min: 100,
    mileage_max: 200,
    remark: '人工备注',
    source_station_value: '',
    source_station_key: '',
    source_order_text: '',
    source_order: null,
    canonical_station_name: '小洋江站',
    node_type: 'station',
    path_code: 'MAIN',
    participates_in_direction: true,
    structure_type: 'underground',
    platform_layout: 'island',
    center_mileage_text: 'K1+000',
    center_mileage_m: 1000,
    is_line_terminal: false,
    is_service_terminal: false,
    turnback_capable: false,
    turnback_type: 'none',
    track_facilities: [],
    turnback_direction: 'none',
    terminal_extension_enabled: false,
    terminal_endpoint_label: '端点',
    terminal_extension_distance_m: null,
    terminal_endpoint_mileage_text: '',
    enabled: true,
    source_kind: 'manual',
    source_device_count: 0,
    source_sync_status: 'manual',
    source_last_seen_at: '',
    ...overrides,
  }
}

function candidate(source: Station): StationSourceCandidate {
  return {
    candidate_id: 'source:01',
    source_station_value: '01小洋江站',
    source_station_key: '01小洋江站',
    source_order_text: '01',
    source_order: 1,
    code: '01',
    name: '小洋江站',
    canonical_name: '小洋江站',
    canonical_station_name: '小洋江站',
    order_parse_method: 'explicit_prefix',
    parse_confidence: 'high',
    parse_warning: '',
    node_type: 'station',
    path_code: 'MAIN',
    sort_order: 1,
    participates_in_direction: true,
    source_device_count: 4,
    match_status: 'canonical_name',
    matched_station_id: 'station:formal',
    matched_station_name: '1.小洋江站',
    matched_station_ids: ['station:formal'],
    matched_station_names: ['1.小洋江站'],
    match_basis: 'canonical_name',
    suggested_action: '覆盖现有',
    processing_strategy: 'overwrite_existing',
    processing_options: ['overwrite_existing', 'ignore'],
    cleanup_name_prefix_recommended: true,
    proposed_station: source,
    issues: [],
  }
}

describe('站点冲突草稿规则', () => {
  it('来源覆盖默认保留正式 id、node_uid 和人工字段', () => {
    const target = station({ name: '1.小洋江站' })
    const source = station({
      id: 'new:source',
      node_uid: 'node-source',
      name: '小洋江站',
      code: '01',
      source_station_value: '01小洋江站',
      source_station_key: '01小洋江站',
      source_kind: 'device_station_field',
      source_device_count: 4,
      source_sync_status: 'matched',
      center_mileage_text: '',
      center_mileage_m: null,
      structure_type: 'unknown',
      platform_layout: 'unknown',
      remark: '',
    })

    const result = overwriteStationFromSource(target, candidate(source))

    expect(result).toMatchObject({
      id: target.id,
      node_uid: target.node_uid,
      name: '小洋江站',
      code: '01',
      source_station_key: '01小洋江站',
      source_device_count: 4,
      source_sync_status: 'matched',
      center_mileage_text: 'K1+000',
      structure_type: 'underground',
      platform_layout: 'island',
      remark: '人工备注',
    })
  })

  it('允许用户明确选择后覆盖人工字段', () => {
    const target = station()
    const source = station({ center_mileage_text: 'K1+100', center_mileage_m: 1100, remark: '来源备注' })
    const result = overwriteStationFromSource(target, candidate(source), ['center_mileage_text', 'center_mileage_m', 'remark'])
    expect(result.center_mileage_text).toBe('K1+100')
    expect(result.center_mileage_m).toBe(1100)
    expect(result.remark).toBe('来源备注')
  })

  it('按路径和顺序聚合具体冲突站点', () => {
    const groups = groupStationOrderConflicts([
      station(),
      station({ id: 'station:duplicate', node_uid: 'node-duplicate', name: '1.小洋江站' }),
      station({ id: 'station:next', node_uid: 'node-next', name: '云龙站', sort_order: 2 }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({ path_code: 'MAIN', sort_order: 1 })
    expect(groups[0].stations.map((item) => item.station_name)).toEqual(['小洋江站', '1.小洋江站'])
  })

  it('节点类型、路径、端点和中心里程冲突会阻断合并', () => {
    const target = station()
    const errors = stationCombinationErrors(target, [
      station({
        id: 'station:source',
        node_type: 'depot',
        path_code: 'DEPOT',
        is_line_terminal: true,
        center_mileage_m: 1500,
      }),
    ])
    expect(errors).toEqual(expect.arrayContaining([
      expect.stringContaining('节点类型不同'),
      expect.stringContaining('所属路径不同'),
      expect.stringContaining('线路端点属性不同'),
      expect.stringContaining('中心里程差异超过 250 米'),
    ]))
  })
})
