import { deviceTaskEntries } from './deviceTaskEntries'

export const NAVIGATION_SCHEMA_VERSION = 3

export type ParityState =
  | 'NOT_STARTED'
  | 'UI_ONLY'
  | 'READ_ONLY'
  | 'FAKE'
  | 'PARTIAL'
  | 'IMPLEMENTED_UNVERIFIED'
  | 'REAL_DEVICE_PENDING'
  | 'COMPLETE'
  | 'BLOCKED'

export interface NavigationItem {
  navigation_id: string
  title: string
  route_name?: string
  route_path?: string
  feature_id?: string
  parent_id?: string
  order: number
  icon: 'dashboard' | 'devices' | 'ac' | 'rail' | 'config' | 'files' | 'network' | 'tools' | 'tasks' | 'system'
  legacy_page_id?: string
  legacy_feature_id?: string
  /** @deprecated 仅用于读取 schema v1 历史数据；新注册项必须使用 legacy_page_id。 */
  qt_page_id?: string
  /** @deprecated 仅用于读取 schema v1 历史数据；新注册项必须使用 legacy_feature_id。 */
  qt_feature_id?: string
  parity_state: ParityState
  desktop_only: boolean
  internal_only: boolean
  implemented: boolean
  children: NavigationItem[]
}

export function normalizeNavigationItem(
  value: Omit<NavigationItem, 'children'> & { children?: NavigationItem[] },
): NavigationItem {
  const { qt_page_id, qt_feature_id, ...current } = value
  return {
    ...current,
    legacy_page_id: current.legacy_page_id ?? qt_page_id,
    legacy_feature_id: current.legacy_feature_id ?? qt_feature_id,
    children: value.children ?? [],
  }
}

const item = normalizeNavigationItem

export const navigationRegistry: NavigationItem[] = [
  item({ navigation_id: 'dashboard', title: '运维工作台', route_name: 'dashboard', route_path: '/', order: 10, icon: 'dashboard', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'device-records', title: '设备资料', order: 20, icon: 'devices', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'devices', title: '设备管理', route_name: 'device-management', route_path: '/network/devices', feature_id: 'module.devices', parent_id: 'device-records', order: 10, icon: 'devices', legacy_page_id: 'devices', legacy_feature_id: 'module.devices', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'device-archives', title: '设备档案', route_name: 'device-archives', route_path: '/devices/archive', feature_id: 'module.devices', parent_id: 'device-records', order: 20, icon: 'devices', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'device-console', title: '控制台', route_name: 'device-console', route_path: '/console', feature_id: 'module.console', order: 25, icon: 'devices', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'ac', title: '无线管理', feature_id: 'module.ac', order: 30, icon: 'ac', legacy_page_id: 'ac', legacy_feature_id: 'module.ac', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'ac.controllers', title: 'AC 管理', route_name: 'ac-controllers', route_path: '/ac-management', feature_id: 'module.ac', parent_id: 'ac', order: 10, icon: 'ac', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.online-overview', title: 'AP 在线概览', route_path: '/ac-management/online-overview', feature_id: 'capability.ac.online_overview', parent_id: 'ac', order: 20, icon: 'ac', legacy_feature_id: 'ac.ap_online_overview', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
    item({ navigation_id: 'ac.fit-aps', title: 'FIT-AP 资源', route_name: 'ac-fit-aps', route_path: '/ac-management/fit-aps', feature_id: 'module.fit_ap', parent_id: 'ac', order: 30, icon: 'ac', legacy_feature_id: 'ac.fit_ap_resources', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.config', title: 'AC 配置快照与对比', route_path: '/ac-management/config', feature_id: 'capability.ac.config_snapshots', parent_id: 'ac', order: 70, icon: 'ac', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  ] }),
  item({ navigation_id: 'rail', title: '轨道交通', feature_id: 'module.rail_transit', order: 40, icon: 'rail', legacy_page_id: 'rail_transit', legacy_feature_id: 'module.rail_transit', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'rail.infrastructure', title: '组织结构', route_name: 'rail-transit-infrastructure', route_path: '/rail-transit/infrastructure', feature_id: 'module.rail_infrastructure', parent_id: 'rail', order: 10, icon: 'rail', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.trackside-ap-business', title: '轨旁 AP 业务', route_name: 'rail-trackside-ap-business', route_path: '/rail-transit/trackside-ap-business', feature_id: 'module.trackside_ap', parent_id: 'rail', order: 15, icon: 'rail', legacy_feature_id: 'rail.trackside_ap_business', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.base-data', title: '基础资料', route_name: 'rail-transit-base-data', route_path: '/rail-transit/base-data', feature_id: 'module.rail_base_data', parent_id: 'rail', order: 20, icon: 'rail', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.wireless-dashboard', title: '轨道交通无线看板', route_name: 'rail-transit-wireless-dashboard', route_path: '/rail-transit/wireless-dashboard', feature_id: 'capability.rail_transit.wireless_dashboard', parent_id: 'rail', order: 25, icon: 'rail', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.ground-unattended', title: '地面无人值守 · 实时采集', route_name: 'ground-unattended', route_path: '/rail-transit/ground-unattended', feature_id: 'module.ground_unattended', parent_id: 'rail', order: 30, icon: 'rail', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.ground-unattended-replay', title: '地面无人值守 · 归档回放', route_name: 'ground-unattended-replay', route_path: '/rail-transit/ground-unattended-replay', feature_id: 'module.ground_unattended', parent_id: 'rail', order: 35, icon: 'rail', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.mesh-analysis', title: 'MR 原始 MESH 日志分析', route_name: 'mesh-analysis', route_path: '/rail-transit/mesh-analysis', feature_id: 'module.mesh_analysis', parent_id: 'rail', order: 70, icon: 'rail', legacy_feature_id: 'rail.raw_mesh_log_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr', title: '车载 MR 实时采集', route_name: 'online-mr-realtime', route_path: '/rail-transit/online-mr', feature_id: 'module.online_mr', parent_id: 'rail', order: 80, icon: 'rail', legacy_feature_id: 'rail.online_mr_collection', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr-analysis', title: '车载 MR 归档回放', route_name: 'online-mr-analysis', route_path: '/rail-transit/online-mr-analysis', feature_id: 'module.online_mr_analysis', parent_id: 'rail', order: 90, icon: 'rail', legacy_feature_id: 'rail.online_mr_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'device-tasks', title: '任务中心', order: 50, icon: 'tasks', feature_id: 'module.task_center', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    ...deviceTaskEntries.map(({ kind, title }, index) => item({
      navigation_id: `tasks.${kind}`, title, route_name: `tasks-${kind}`, route_path: `/tasks/${kind}`,
      feature_id: 'module.devices', parent_id: 'device-tasks', order: index + 1, icon: 'tasks',
      parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true,
    })),
    item({ navigation_id: 'tasks', title: '其他网络设备任务', route_name: 'tasks', route_path: '/tasks', feature_id: 'module.task_center', parent_id: 'device-tasks', order: 10, icon: 'tasks', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'tools', title: '工具集', order: 60, icon: 'tools', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'tools.external-tools', title: '外部工具', route_name: 'tool-collection', route_path: '/tools', feature_id: 'module.tools', parent_id: 'tools', order: 10, icon: 'tools', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: true, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'files', title: '文件管理', order: 70, icon: 'files', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'files.manager', title: '本地受管文件', route_name: 'device-file-manager', route_path: '/file-manager', feature_id: 'module.file_management', parent_id: 'files', order: 10, icon: 'files', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'files.downloads', title: '设备文件传输', route_name: 'device-file-downloads', route_path: '/device-files', feature_id: 'module.file_management', parent_id: 'files', order: 20, icon: 'files', legacy_page_id: 'file_management', legacy_feature_id: 'module.file_management', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'network-services', title: '网络服务', order: 80, icon: 'network', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'tools.connectivity', title: '网络测试与计算', route_name: 'tools-connectivity', route_path: '/tools/connectivity', feature_id: 'capability.network_tools.toolbox', parent_id: 'network-services', order: 10, icon: 'network', legacy_feature_id: 'network_tools.toolbox', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.traffic', title: '流量测试', route_name: 'tools-traffic', route_path: '/tools/traffic', feature_id: 'network_tools.traffic', parent_id: 'network-services', order: 20, icon: 'network', legacy_feature_id: 'network_tools.traffic', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.wireless-scan', title: '无线扫描', route_name: 'tools-wireless-scan', route_path: '/tools/wireless-scan', feature_id: 'capability.network_tools.wireless_scan', parent_id: 'network-services', order: 30, icon: 'network', legacy_feature_id: 'network_tools.wireless_scan', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.network-services', title: '本机监听服务', route_name: 'tools-network-services', route_path: '/tools/network-services', feature_id: 'capability.network_tools.local_services', parent_id: 'network-services', order: 40, icon: 'network', parity_state: 'PARTIAL', desktop_only: true, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.network-components', title: '网络测试组件', route_name: 'tools-network-components', route_path: '/tools/network-components', feature_id: 'capability.network_tools.components', parent_id: 'network-services', order: 50, icon: 'tools', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: true, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'maintenance', title: '软件说明与维护', order: 90, icon: 'system', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'logs', title: '日志与维护', route_name: 'logs', route_path: '/logs', feature_id: 'module.logs', parent_id: 'maintenance', order: 10, icon: 'system', legacy_page_id: 'logs', legacy_feature_id: 'module.logs', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'settings', title: '系统设置', route_name: 'system-settings', route_path: '/settings', feature_id: 'module.system_settings', parent_id: 'maintenance', order: 20, icon: 'system', legacy_page_id: 'system_settings', legacy_feature_id: 'module.system_settings', parity_state: 'PARTIAL', desktop_only: true, internal_only: false, implemented: true }),
  ] }),
]

export function flattenNavigation(items: NavigationItem[] = navigationRegistry): NavigationItem[] {
  return items.flatMap((entry) => [entry, ...flattenNavigation(entry.children)])
}

export function findNavigation(navigationId: string): NavigationItem | undefined {
  return flattenNavigation().find((entry) => entry.navigation_id === navigationId)
}

export function visibleNavigation(
  isVisible: (featureId: string) => boolean,
  items: NavigationItem[] = navigationRegistry,
): NavigationItem[] {
  return items
    .map((entry) => ({ ...entry, children: visibleNavigation(isVisible, entry.children) }))
    .filter((entry) => {
      if (!entry.implemented) return false
      if (entry.desktop_only && !(typeof window !== 'undefined' && window.netconsoleDesktop)) return false
      if (entry.feature_id && !isVisible(entry.feature_id)) return false
      return entry.children.length > 0 || Boolean(entry.route_name && entry.route_path)
    })
    .sort((left, right) => left.order - right.order)
}
