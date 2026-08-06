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
  icon: 'dashboard' | 'devices' | 'ac' | 'rail' | 'config' | 'files' | 'network' | 'tools' | 'tasks' | 'agent' | 'system'
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
  item({ navigation_id: 'dashboard', title: 'Dashboard', route_name: 'dashboard', route_path: '/', order: 10, icon: 'dashboard', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'devices', title: '设备管理', route_name: 'device-management', route_path: '/network/devices', feature_id: 'web.device_management', order: 20, icon: 'devices', legacy_page_id: 'devices', legacy_feature_id: 'module.devices', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'ac', title: 'AC 管理', feature_id: 'module.ac', order: 30, icon: 'ac', legacy_page_id: 'ac', legacy_feature_id: 'module.ac', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'ac.online-overview', title: 'AP 在线概览', route_path: '/ac-management/online-overview', feature_id: 'web.ac_online_overview', parent_id: 'ac', order: 20, icon: 'ac', legacy_feature_id: 'ac.ap_online_overview', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
    item({ navigation_id: 'ac.fit-aps', title: 'FIT-AP 资源', route_name: 'ac-fit-aps', route_path: '/ac-management/fit-aps', feature_id: 'web.ac_fit_ap_resources', parent_id: 'ac', order: 30, icon: 'ac', legacy_feature_id: 'ac.fit_ap_resources', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.extensions', title: 'AP 扩展信息', route_name: 'ac-extensions', route_path: '/ac-management/extensions', feature_id: 'web.ac_extensions', parent_id: 'ac', order: 50, icon: 'ac', legacy_feature_id: 'ac.fit_ap_extensions', parity_state: 'FAKE', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.config', title: 'AC 配置快照与对比', route_path: '/ac-management/config', feature_id: 'web.ac_config_snapshots', parent_id: 'ac', order: 70, icon: 'ac', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  ] }),
  item({ navigation_id: 'rail', title: '轨道交通', feature_id: 'module.rail_transit', order: 40, icon: 'rail', legacy_page_id: 'rail_transit', legacy_feature_id: 'module.rail_transit', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'rail.wireless-dashboard', title: '轨道交通无线看板', route_name: 'rail-transit-wireless-dashboard', route_path: '/rail-transit/wireless-dashboard', feature_id: 'web.rail_transit_wireless_dashboard', parent_id: 'rail', order: 10, icon: 'rail', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.base-data', title: '基础资料', route_name: 'rail-transit-base-data', route_path: '/rail-transit/base-data', feature_id: 'web.rail_transit_base_data', parent_id: 'rail', order: 20, icon: 'rail', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.train-online', title: '列车在线情况', route_name: 'rail-train-online', route_path: '/rail-transit/train-online', feature_id: 'web.rail_train_online', parent_id: 'rail', order: 30, icon: 'rail', legacy_feature_id: 'rail.train_online', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.ground-unattended', title: '地面无人值守', route_name: 'ground-unattended', route_path: '/rail-transit/ground-unattended', feature_id: 'web.ground_unattended', parent_id: 'rail', order: 40, icon: 'rail', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.train-communication', title: '车内通信检测', route_name: 'train-communication', route_path: '/rail-transit/train-communication', feature_id: 'web.train_communication_monitoring', parent_id: 'rail', order: 50, icon: 'rail', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.trackside-ap-business', title: '轨旁 AP 业务', route_name: 'rail-trackside-ap-business', route_path: '/rail-transit/trackside-ap-business', feature_id: 'web.rail_trackside_ap_business', parent_id: 'rail', order: 60, icon: 'rail', legacy_feature_id: 'rail.trackside_ap_business', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.mesh-analysis', title: 'MR 原始 MESH 日志分析', route_name: 'mesh-analysis', route_path: '/rail-transit/mesh-analysis', feature_id: 'web.mesh_analysis', parent_id: 'rail', order: 70, icon: 'rail', legacy_feature_id: 'rail.raw_mesh_log_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr', title: '车载 MR 实时收集', route_name: 'online-mr-realtime', route_path: '/rail-transit/online-mr', feature_id: 'web.online_mr_realtime', parent_id: 'rail', order: 80, icon: 'rail', legacy_feature_id: 'rail.online_mr_collection', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr-analysis', title: '车载 MR 收集分析', route_name: 'online-mr-analysis', route_path: '/rail-transit/online-mr-analysis', feature_id: 'web.online_mr_analysis', parent_id: 'rail', order: 90, icon: 'rail', legacy_feature_id: 'rail.online_mr_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'files', title: '设备文件下载', order: 50, icon: 'files', legacy_page_id: 'file_management', legacy_feature_id: 'module.file_management', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'files.downloads', title: '设备文件下载', route_name: 'device-file-downloads', route_path: '/device-files', feature_id: 'web.file_management', parent_id: 'files', order: 10, icon: 'files', legacy_page_id: 'file_management', legacy_feature_id: 'module.file_management', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'files.config-collection', title: '配置采集中心', route_name: 'config-collection', route_path: '/config-center', feature_id: 'web.config_collection', parent_id: 'files', order: 20, icon: 'config', legacy_page_id: 'config_collection', legacy_feature_id: 'module.config_collection', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'files.device-diagnostics', title: '设备诊断下载', route_name: 'device-diagnostic-downloads', route_path: '/device-files/diagnostics', feature_id: 'web.device_management_collect', parent_id: 'files', order: 30, icon: 'files', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'tools', title: '工具集', order: 70, icon: 'tools', legacy_page_id: 'tools', legacy_feature_id: 'module.tools', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'tools.external-tools', title: '外部工具', route_name: 'tool-collection', route_path: '/tools', feature_id: 'web.tool_collection', parent_id: 'tools', order: 10, icon: 'tools', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: true, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.traffic', title: '流量测试', route_name: 'tools-traffic', route_path: '/tools/traffic', feature_id: 'network_tools.traffic', parent_id: 'tools', order: 20, icon: 'network', legacy_feature_id: 'network_tools.traffic', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.connectivity', title: '小工具与连通性检测', route_name: 'tools-connectivity', route_path: '/tools/connectivity', feature_id: 'web.network_tools_toolbox', parent_id: 'tools', order: 30, icon: 'network', legacy_feature_id: 'network_tools.toolbox', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.wireless-scan', title: '无线扫描', route_name: 'tools-wireless-scan', route_path: '/tools/wireless-scan', feature_id: 'web.network_tools_wireless_scan', parent_id: 'tools', order: 40, icon: 'network', legacy_feature_id: 'network_tools.wireless_scan', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'tools.network-components', title: '网络测试组件', route_name: 'tools-network-components', route_path: '/tools/network-components', feature_id: 'web.network_test_components', parent_id: 'tools', order: 50, icon: 'tools', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: true, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'tasks', title: '任务中心', route_name: 'tasks', route_path: '/tasks', feature_id: 'web.job_center', order: 80, icon: 'tasks', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'agents', title: 'Agent 管理', route_name: 'agents', route_path: '/agents', feature_id: 'web.agent_management', order: 90, icon: 'agent', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'logs', title: '日志中心', route_name: 'logs', route_path: '/logs', feature_id: 'web.logs', order: 110, icon: 'system', legacy_page_id: 'logs', legacy_feature_id: 'module.logs', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'settings', title: '系统设置', route_name: 'system-settings', route_path: '/settings', feature_id: 'web.system_settings', order: 120, icon: 'system', legacy_page_id: 'system_settings', legacy_feature_id: 'module.system_settings', parity_state: 'PARTIAL', desktop_only: true, internal_only: false, implemented: true }),
  item({ navigation_id: 'feature-flags', title: '版本与功能交付', route_name: 'edition-feature-profiles', route_path: '/feature-flags', feature_id: 'web.feature_switch', order: 130, icon: 'system', legacy_page_id: 'feature_flags', legacy_feature_id: 'system.feature_flags', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: true, internal_only: true, implemented: true }),
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
