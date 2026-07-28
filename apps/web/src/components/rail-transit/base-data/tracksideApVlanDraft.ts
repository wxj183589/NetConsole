import type {
  ApManagementVlanGroupMember,
  TracksideApPlanDraft,
} from '../../../types/tracksideApBusiness'

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function splitVlanGroup(
  draft: TracksideApPlanDraft,
  groupId: string,
  splitAt: number,
  newGroupId: string,
): TracksideApPlanDraft {
  const result = copy(draft)
  const index = result.groups.findIndex((group) => group.group_id === groupId)
  if (index < 0) throw new Error('VLAN 组不存在')
  const original = result.groups[index]
  if (splitAt < 1 || splitAt >= original.members.length) throw new Error('拆分边界必须位于组内相邻站点之间')
  const right = copy(original)
  right.group_id = newGroupId
  right.group_code = `${original.group_code}-B`
  right.group_name = `${original.group_name} B`
  right.members = original.members.splice(splitAt)
  right.management_vlan = null
  right.network_address = ''
  right.default_gateway = ''
  right.ap_start_ip = ''
  right.ap_end_ip = ''
  result.groups.splice(index + 1, 0, right)
  return result
}

export function mergeAdjacentVlanGroups(
  draft: TracksideApPlanDraft,
  firstGroupId: string,
  secondGroupId: string,
): TracksideApPlanDraft {
  const result = copy(draft)
  const first = result.groups.find((group) => group.group_id === firstGroupId)
  const second = result.groups.find((group) => group.group_id === secondGroupId)
  if (!first || !second) throw new Error('VLAN 组不存在')
  if (Math.abs(first.sequence - second.sequence) !== 1) throw new Error('只能合并相邻 VLAN 组')
  const [left, right] = first.sequence < second.sequence ? [first, second] : [second, first]
  if (result.planning.planning_mode !== 'line_single' && left.members.length + right.members.length > 4) {
    throw new Error('按站点分组时每组最多 4 个站点')
  }
  left.members.push(...right.members)
  result.groups = result.groups.filter((group) => group.group_id !== right.group_id)
  result.assignments = result.assignments.map((item) => item.group_id === right.group_id ? { ...item, group_id: left.group_id } : item)
  return result
}

export function updateVlanGroupMembers(
  source: TracksideApPlanDraft,
  groupId: string,
  members: ApManagementVlanGroupMember[],
): TracksideApPlanDraft {
  const result = copy(source)
  const target = result.groups.find((group) => group.group_id === groupId)
  if (!target) throw new Error('VLAN 组不存在')
  const selectedIds = new Set(members.map((member) => member.station_id))
  for (const group of result.groups) {
    group.members = group.group_id === groupId
      ? copy(members).sort((left, right) => left.station_sequence - right.station_sequence)
      : group.members.filter((member) => !selectedIds.has(member.station_id))
  }
  return result
}
