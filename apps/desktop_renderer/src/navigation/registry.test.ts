// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'

import {
  flattenNavigation,
  navigationRegistry,
  normalizeNavigationItem,
  NAVIGATION_SCHEMA_VERSION,
  visibleNavigation,
  type NavigationItem,
} from './registry'

describe('Web navigation registry', () => {
  it('keeps the fixed top-level order', () => {
    expect(navigationRegistry.map((item) => item.title)).toEqual([
      '运维工作台', '设备资料', '控制台', '无线管理', '轨道交通', '任务中心', '工具集',
      '文件管理', '网络服务', '软件说明与维护',
    ])
  })

  it('keeps AC, rail transit, and toolbox ownership stable', () => {
    const flat = flattenNavigation()
    const parent = (id: string) => flat.find((item) => item.navigation_id === id)?.parent_id

    expect(parent('rail.trackside-ap-business')).toBe('rail')
    expect(parent('rail.online-mr')).toBe('rail')
    expect(parent('rail.online-mr-analysis')).toBe('rail')
    expect(parent('rail.ground-unattended')).toBe('rail')
    expect(parent('tools.traffic')).toBe('network-services')
    expect(parent('tools.wireless-scan')).toBe('network-services')
    expect(parent('tools.network-components')).toBe('network-services')
    expect(flat.some((item) => item.navigation_id === 'network')).toBe(false)
    expect(flat.find((item) => item.navigation_id === 'tools.external-tools')?.parent_id).toBe('tools')
    expect(flat.some((item) => /snmp|wifi-survey/.test(item.navigation_id))).toBe(false)
  })

  it('registers the fixed child ordering without exposing unfinished routes', () => {
    expect(navigationRegistry.find((item) => item.navigation_id === 'ac')?.children.map((item) => item.title)).toEqual([
      'AC 管理', 'AP 在线概览', 'FIT-AP 资源', 'AC 配置快照与对比',
    ])
    expect(flattenNavigation().some((item) => item.navigation_id === 'ac.mesh-links')).toBe(false)
    expect(flattenNavigation().some((item) => item.navigation_id === 'ac.optical')).toBe(false)
    expect(navigationRegistry.find((item) => item.navigation_id === 'rail')?.children.map((item) => item.title)).toEqual([
      '组织结构', '轨旁 AP 业务', '基础资料', '轨道交通无线看板', '地面无人值守 · 实时采集', '地面无人值守 · 归档回放', 'MR 原始 MESH 日志分析', '车载 MR 实时采集', '车载 MR 归档回放',
    ])
    expect(flattenNavigation().some((item) => item.navigation_id === 'rail.train-online')).toBe(false)
    expect(navigationRegistry.find((item) => item.navigation_id === 'files')?.children.map((item) => item.title)).toEqual([
      '本地受管文件', '设备文件传输',
    ])
    expect(flattenNavigation().some((item) => item.navigation_id === 'config')).toBe(false)
    expect(flattenNavigation().some((item) => item.navigation_id === 'rail.car-network-diagnostic')).toBe(false)
    expect(flattenNavigation().some((item) => item.navigation_id === 'rail.trackside-ap-plan')).toBe(false)
    expect(navigationRegistry.find((item) => item.navigation_id === 'tools')?.children.map((item) => item.navigation_id)).toEqual([
      'tools.external-tools',
    ])
    const visible = flattenNavigation(visibleNavigation(() => true))
    expect(visible.every((item) => item.children.length > 0 || Boolean(item.route_name && item.route_path))).toBe(true)
    expect(visible.some((item) => item.navigation_id === 'tools.wireless-scan')).toBe(true)
    expect(visible.some((item) => item.navigation_id === 'command-reference' || item.navigation_id === 'storage-management')).toBe(false)
  })

  it('shows independent network service entries in Electron', () => {
    const previous = window.netconsoleDesktop
    Object.defineProperty(window, 'netconsoleDesktop', { configurable: true, value: {} })
    const visible = visibleNavigation(() => true)
    const ids = visible.map((entry) => entry.navigation_id)
    expect(ids).toContain('tools')
    expect(ids).toContain('network-services')
    const tools = visible.find((entry) => entry.navigation_id === 'network-services')
    expect(tools?.children.map((item) => item.route_path)).toEqual([
      '/tools/connectivity', '/tools/traffic', '/tools/wireless-scan', '/tools/network-services', '/tools/network-components',
    ])
    if (previous === undefined) Reflect.deleteProperty(window, 'netconsoleDesktop')
    else Object.defineProperty(window, 'netconsoleDesktop', { configurable: true, value: previous })
  })

  it('hides desktop-only tools and listener management in browser navigation', () => {
    const previous = window.netconsoleDesktop
    Reflect.deleteProperty(window, 'netconsoleDesktop')
    const visible = visibleNavigation(() => true)
    expect(visible.some((entry) => entry.navigation_id === 'tools')).toBe(false)
    const tools = visible.find((entry) => entry.navigation_id === 'network-services')
    expect(tools?.children.map((item) => item.navigation_id)).toEqual([
      'tools.connectivity', 'tools.traffic', 'tools.wireless-scan',
    ])
    if (previous === undefined) Reflect.deleteProperty(window, 'netconsoleDesktop')
    else Object.defineProperty(window, 'netconsoleDesktop', { configurable: true, value: previous })
  })

  it('exposes the device task workflows under the task center feature gate', () => {
    const group = visibleNavigation(() => true).find((entry) => entry.navigation_id === 'device-tasks')
    expect(group?.children.map((entry) => entry.title)).toEqual(['诊断收集', '配置备份', '版本升级', '配置生成', '其他网络设备任务'])
    expect(visibleNavigation((id) => id !== 'module.task_center').some((entry) => entry.navigation_id === 'device-tasks')).toBe(false)
  })

  it('keeps the device console on an independent feature gate', () => {
    const entry = navigationRegistry.find((item) => item.navigation_id === 'device-console')
    expect(entry).toMatchObject({ route_path: '/console', feature_id: 'module.console' })
    expect(visibleNavigation((id) => id !== 'module.console').some((item) => item.navigation_id === entry?.navigation_id)).toBe(false)
    expect(visibleNavigation(() => true).some((item) => item.navigation_id === entry?.navigation_id)).toBe(true)
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

  it('writes legacy metadata with neutral names while reading schema v1 fields', () => {
    expect(NAVIGATION_SCHEMA_VERSION).toBe(3)
    expect(flattenNavigation().some((entry) => 'qt_page_id' in entry || 'qt_feature_id' in entry)).toBe(false)

    const migrated = normalizeNavigationItem({
      navigation_id: 'legacy',
      title: 'legacy',
      order: 1,
      icon: 'system',
      qt_page_id: 'old-page',
      qt_feature_id: 'old-feature',
      parity_state: 'COMPLETE',
      desktop_only: false,
      internal_only: true,
      implemented: false,
    })
    expect(migrated.legacy_page_id).toBe('old-page')
    expect(migrated.legacy_feature_id).toBe('old-feature')
    expect('qt_page_id' in migrated).toBe(false)
    expect('qt_feature_id' in migrated).toBe(false)
  })

  it('keeps device management at implemented but unverified', () => {
    const device = flattenNavigation().find((item) => item.navigation_id === 'devices')
    expect(device?.parity_state).toBe('IMPLEMENTED_UNVERIFIED')
  })

  it('keeps file module children implemented but unverified', () => {
    const files = flattenNavigation().find((item) => item.navigation_id === 'files')
    expect(files?.parity_state).toBe('IMPLEMENTED_UNVERIFIED')
    expect(files?.children.map((item) => item.navigation_id)).toEqual([
      'files.manager',
      'files.downloads',
    ])
  })
})
