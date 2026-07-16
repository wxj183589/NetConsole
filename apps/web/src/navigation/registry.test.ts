import { describe, expect, it } from 'vitest'

import {
  flattenNavigation,
  navigationRegistry,
  visibleNavigation,
  type NavigationItem,
} from './registry'

describe('Web navigation registry', () => {
  it('keeps the fixed top-level order', () => {
    expect(navigationRegistry.map((item) => item.title)).toEqual([
      'Dashboard',
      '设备管理',
      'AC 管理',
      '轨道交通',
      '配置采集中心',
      '文件管理',
      '网络工具',
      '任务中心',
      'Agent 管理',
      '命令说明',
      '日志中心',
      '系统设置',
      '功能开关配置',
    ])
  })

  it('keeps AC, rail transit, and network tools ownership stable', () => {
    const flat = flattenNavigation()
    const parent = (id: string) => flat.find((item) => item.navigation_id === id)?.parent_id

    expect(parent('ac.trackside-plan')).toBe('ac')
    expect(parent('rail.trackside-ap-business')).toBe('rail')
    expect(parent('rail.trackside-ap-plan')).toBe('rail')
    expect(parent('rail.online-mr')).toBe('rail')
    expect(parent('rail.online-mr-analysis')).toBe('rail')
    expect(parent('network.traffic')).toBe('network')
    expect(parent('network.wireless-scan')).toBe('network')
    expect(flat.some((item) => /snmp|wifi-survey/.test(item.navigation_id))).toBe(false)
  })

  it('registers the fixed child ordering without exposing unfinished routes', () => {
    expect(navigationRegistry.find((item) => item.navigation_id === 'ac')?.children.map((item) => item.title)).toEqual([
      '轨旁 AP 规划', 'AP 在线概览', 'FIT-AP 资源', '光衰', 'AP 扩展信息', 'Mesh-Link 在线监控', 'AC 配置快照与对比',
    ])
    expect(navigationRegistry.find((item) => item.navigation_id === 'rail')?.children.map((item) => item.title)).toEqual([
      '轨道交通无线看板', '基础资料', '列车在线情况', '车内通信检测', '在线列车车地通信检测', '轨旁 AP 业务', '轨旁 AP 规划', 'MR 原始 MESH 日志分析', '车载 MR 实时收集', '车载 MR 收集分析',
    ])
    expect(navigationRegistry.find((item) => item.navigation_id === 'network')?.children.map((item) => item.title)).toEqual([
      '流量测试', '小工具与连通性检测', '无线扫描',
    ])
    const visible = flattenNavigation(visibleNavigation(() => true))
    expect(visible.every((item) => item.children.length > 0 || Boolean(item.route_name && item.route_path))).toBe(true)
    expect(visible.some((item) => item.navigation_id === 'network.wireless-scan')).toBe(true)
  })

  it('hides a group when none of its children are visible', () => {
    const child: NavigationItem = { navigation_id: 'child', title: 'child', route_name: 'child', route_path: '/child', feature_id: 'hidden', parent_id: 'group', order: 1, icon: 'system', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: true, children: [] }
    const group: NavigationItem = { navigation_id: 'group', title: 'group', order: 1, icon: 'system', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: true, children: [child] }

    expect(visibleNavigation(() => false, [group])).toEqual([])
  })

  it('has no duplicate navigation ids or routes', () => {
    const flat = flattenNavigation()
    const ids = flat.map((item) => item.navigation_id)
    const routes = flat.flatMap((item) => item.route_path ? [item.route_path] : [])
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(routes).size).toBe(routes.length)
  })

  it('keeps device management at implemented but unverified', () => {
    const device = flattenNavigation().find((item) => item.navigation_id === 'devices')
    expect(device?.parity_state).toBe('IMPLEMENTED_UNVERIFIED')
  })

  it('keeps configuration collection pending real-device acceptance', () => {
    const config = flattenNavigation().find((item) => item.navigation_id === 'config')
    expect(config?.parity_state).toBe('IMPLEMENTED_UNVERIFIED')
  })
})
