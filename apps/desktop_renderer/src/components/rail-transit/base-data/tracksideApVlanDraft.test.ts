import { describe, expect, it } from 'vitest'

import type { TracksideApPlanDraft } from '../../../types/tracksideApBusiness'
import {
  mergeAdjacentVlanGroups,
  splitVlanGroup,
  updateVlanGroupMembers,
} from './tracksideApVlanDraft'

const draft = (sizes: number[], mode: TracksideApPlanDraft['planning']['planning_mode'] = 'station_grouped'): TracksideApPlanDraft => ({
  planning: { line_id: 'current', planning_mode: mode, auto_group_station_count: 4, address_allocation_strategy: 'station_then_point', revision: 1, updated_at: '' },
  groups: sizes.map((size, groupIndex) => ({
    group_id: `g${groupIndex + 1}`, line_id: 'current', group_code: `G${groupIndex + 1}`, group_name: `组${groupIndex + 1}`, sequence: groupIndex,
    management_vlan: 71 + groupIndex, legacy_management_vlans: '', network_address: `10.0.${groupIndex}.0`, prefix_length: 24,
    subnet_mask: '255.255.255.0', default_gateway: `10.0.${groupIndex}.1`, ap_start_ip: `10.0.${groupIndex}.10`, ap_end_ip: '',
    address_allocation_strategy: 'station_then_point', notes: '', created_at: '', updated_at: '',
    members: Array.from({ length: size }, (_, memberIndex) => ({
      station_id: `s${sizes.slice(0, groupIndex).reduce((sum, value) => sum + value, 0) + memberIndex + 1}`,
      station_name: `站${memberIndex + 1}`, station_sequence: memberIndex, ap_count: 1,
    })),
    start_station_name: '', end_station_name: '', station_count: size, ap_count: size,
    address_capacity: 245, used_address_count: size, validation_status: 'valid', issues: [],
  })),
  assignments: [],
  allocations: [],
})

describe('trackside AP VLAN group draft operations', () => {
  it('splits one group at a station boundary without mutating the source', () => {
    const source = draft([4])
    source.allocations.push({
      ap_id: 'ap:1', ap_name: 'AP-1', point_code: 'P01', station_id: 's1', station_name: '站1',
      section_name: '', group_id: 'g1', planned_ip: 'existing-reference', allocation_order: 0,
      is_manual: false, is_locked: false, source: 'existing_ap', group_source: 'station_inherited', updated_at: '',
    })
    const result = splitVlanGroup(source, 'g1', 3, 'g2')
    expect(result.groups.map((group) => group.members.length)).toEqual([3, 1])
    expect(source.groups).toHaveLength(1)
    expect(result.groups[1].management_vlan).toBeNull()
    expect(result.groups[1].ap_start_ip).toBe(source.groups[0].ap_start_ip)
    expect(result.allocations[0].planned_ip).toBe('existing-reference')
  })

  it('rejects an invalid split boundary', () => {
    expect(() => splitVlanGroup(draft([2]), 'g1', 2, 'g2')).toThrow('拆分边界')
  })

  it('merges adjacent groups and remaps overrides', () => {
    const source = draft([1, 3])
    source.assignments.push({ assignment_id: 'a1', assignment_type: 'ap_override', target_id: 'ap:1', group_id: 'g2', source: 'ap_override', updated_at: '' })
    source.allocations.push({
      ap_id: 'ap:1', ap_name: 'AP-1', point_code: 'P01', station_id: 's2', station_name: '站1',
      section_name: '', group_id: 'g2', planned_ip: 'existing-reference', allocation_order: 0,
      is_manual: false, is_locked: false, source: 'existing_ap', group_source: 'station_inherited', updated_at: '',
    })
    const result = mergeAdjacentVlanGroups(source, 'g1', 'g2')
    expect(result.groups.map((group) => group.members.length)).toEqual([4])
    expect(result.assignments[0].group_id).toBe('g1')
    expect(result.allocations[0].planned_ip).toBe('existing-reference')
  })

  it('rejects non-adjacent merges', () => {
    expect(() => mergeAdjacentVlanGroups(draft([1, 1, 1]), 'g1', 'g3')).toThrow('只能合并相邻')
  })

  it('rejects a grouped VLAN with more than four stations', () => {
    expect(() => mergeAdjacentVlanGroups(draft([3, 2]), 'g1', 'g2')).toThrow('最多 4 个站点')
  })

  it('allows line-wide mode to contain more than four stations', () => {
    expect(mergeAdjacentVlanGroups(draft([3, 3], 'line_single'), 'g1', 'g2').groups[0].members).toHaveLength(6)
  })

  it('moves stable station members between groups without duplicating them', () => {
    const source = draft([2, 2])
    const moved = source.groups[1].members[0]
    const result = updateVlanGroupMembers(
      source,
      'g1',
      [...source.groups[0].members, moved],
    )
    expect(result.groups.map((group) => group.members.length)).toEqual([3, 1])
    expect(result.groups.flatMap((group) => group.members).filter((member) => member.station_id === moved.station_id)).toHaveLength(1)
    expect(source.groups.map((group) => group.members.length)).toEqual([2, 2])
  })
})
