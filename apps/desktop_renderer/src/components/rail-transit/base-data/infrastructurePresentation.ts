import type { Infrastructure, InfrastructureDevice, InfrastructureNode } from '../../../api/railInfrastructure'

export function uniqueDevices(devices: InfrastructureDevice[]): InfrastructureDevice[] {
  return [...new Map(devices.map(device => [device.device_uuid, device])).values()]
}

export function nodeLabel(node: InfrastructureNode): string {
  return [node.code, node.name].filter(Boolean).join(' ')
}

export function hierarchyGroups(snapshot: Infrastructure | undefined, search: string) {
  const nodes = snapshot?.nodes ?? []
  const query = search.trim().toLocaleLowerCase()
  const matches = (item: InfrastructureNode) => [nodeLabel(item), ...item.aliases.map(alias => alias.name), ...item.devices.map(device => device.name)].some(value => value.toLocaleLowerCase().includes(query))
  const select = (kinds: InfrastructureNode['kind'][]) => nodes.filter(item => kinds.includes(item.kind) && matches(item))
  return [
    { name: '控制中心', items: select(['cocc', 'bocc']) },
    { name: '正线车站', items: select(['station']) },
    { name: '车辆段与停车场', items: select(['depot', 'parking_yard']) },
    { name: '车载设备', items: select(['train']) },
  ]
}

export function nodeFields(node: InfrastructureNode) {
  const fields: { label: string; value: string }[] = []
  const add = (label: string, value?: string | number | null) => {
    if (value !== undefined && value !== null && String(value).trim()) fields.push({ label, value: String(value) })
  }
  if (node.kind === 'train') {
    add('列车编号', node.code)
    for (const position of ['CT', 'CW']) {
      const mrs = uniqueDevices(node.devices).filter(device => device.role === `MR-${position}`)
      add(`MR-${position}`, mrs.length ? mrs.map(device => device.name).join('、') : '未配置')
    }
    add('当前关系', node.devices.some(device => ['MR-CT','MR-CW'].includes(device.role)) ? '已关联' : '未配置')
    return fields
  }
  add(node.kind === 'station' ? '车站编号' : '编号', node.code)
  if (['cocc', 'bocc', 'depot', 'parking_yard'].includes(node.kind)) add('类型', ({ cocc:'COCC', bocc:'BOCC', depot:'车辆段', parking_yard:'停车场' } as Record<string,string>)[node.kind])
  if (node.kind === 'station') add('工程名称', [...new Set(node.aliases.filter(alias => alias.name_type === 'engineering' && !alias.valid_to && alias.name.trim() && alias.name !== node.name).map(alias => alias.name))].join('、'))
  add('建设项目', [...new Map(node.projects.filter(project => project.name.trim()).map(project => [project.project_id, project])).values()].map(project => [project.stage, project.name].filter(Boolean).join(' ')).join('、'))
  if (['station','depot','parking_yard'].includes(node.kind)) {
    add('下属交换机', uniqueDevices(node.devices).filter(device => device.device_role === 'switch').length)
  }
  return fields
}
