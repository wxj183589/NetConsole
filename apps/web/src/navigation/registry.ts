export const NAVIGATION_SCHEMA_VERSION = 1

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
  icon: 'dashboard' | 'devices' | 'ac' | 'rail' | 'config' | 'files' | 'network' | 'tasks' | 'agent' | 'system'
  qt_page_id?: string
  qt_feature_id?: string
  parity_state: ParityState
  desktop_only: boolean
  internal_only: boolean
  implemented: boolean
  children: NavigationItem[]
}

function item(value: Omit<NavigationItem, 'children'> & { children?: NavigationItem[] }): NavigationItem {
  return { ...value, children: value.children ?? [] }
}

export const navigationRegistry: NavigationItem[] = [
  item({ navigation_id: 'dashboard', title: 'Dashboard', route_name: 'dashboard', route_path: '/', order: 10, icon: 'dashboard', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'devices', title: '设备管理', route_name: 'device-management', route_path: '/network/devices', feature_id: 'web.device_management', order: 20, icon: 'devices', qt_page_id: 'devices', qt_feature_id: 'module.devices', parity_state: 'IMPLEMENTED_UNVERIFIED', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'ac', title: 'AC 管理', feature_id: 'module.ac', order: 30, icon: 'ac', qt_page_id: 'ac', qt_feature_id: 'module.ac', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'ac.trackside-plan', title: '轨旁 AP 规划', route_path: '/ac-management/trackside-plan', feature_id: 'web.ac_trackside_ap_plan', parent_id: 'ac', order: 10, icon: 'ac', qt_feature_id: 'ac.trackside_ap_plan', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
    item({ navigation_id: 'ac.online-overview', title: 'AP 在线概览', route_path: '/ac-management/online-overview', feature_id: 'web.ac_online_overview', parent_id: 'ac', order: 20, icon: 'ac', qt_feature_id: 'ac.ap_online_overview', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
    item({ navigation_id: 'ac.fit-aps', title: 'FIT-AP 资源', route_name: 'ac-fit-aps', route_path: '/ac-management/fit-aps', feature_id: 'web.ac_fit_ap_resources', parent_id: 'ac', order: 30, icon: 'ac', qt_feature_id: 'ac.fit_ap_resources', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.optical', title: '光衰', route_name: 'ac-optical', route_path: '/ac-management/optical', feature_id: 'web.ac_optical', parent_id: 'ac', order: 40, icon: 'ac', qt_feature_id: 'ac.fit_ap_optical', parity_state: 'REAL_DEVICE_PENDING', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.extensions', title: 'AP 扩展信息', route_name: 'ac-extensions', route_path: '/ac-management/extensions', feature_id: 'web.ac_extensions', parent_id: 'ac', order: 50, icon: 'ac', qt_feature_id: 'ac.fit_ap_extensions', parity_state: 'FAKE', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.mesh-links', title: 'Mesh-Link 在线监控', route_name: 'ac-mesh-links', route_path: '/ac-management/mesh-links', feature_id: 'web.ac_mesh_links', parent_id: 'ac', order: 60, icon: 'ac', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'ac.config', title: 'AC 配置快照与对比', route_path: '/ac-management/config', feature_id: 'web.ac_config_snapshots', parent_id: 'ac', order: 70, icon: 'ac', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  ] }),
  item({ navigation_id: 'rail', title: '轨道交通', feature_id: 'module.rail_transit', order: 40, icon: 'rail', qt_page_id: 'rail_transit', qt_feature_id: 'module.rail_transit', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'rail.wireless-dashboard', title: '轨道交通无线看板', route_name: 'rail-transit-wireless-dashboard', route_path: '/rail-transit/wireless-dashboard', feature_id: 'web.rail_transit_wireless_dashboard', parent_id: 'rail', order: 10, icon: 'rail', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.base-data', title: '基础资料', route_name: 'rail-transit-base-data', route_path: '/rail-transit/base-data', feature_id: 'web.rail_transit_base_data', parent_id: 'rail', order: 20, icon: 'rail', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.train-online', title: '列车在线情况', route_name: 'rail-train-online', route_path: '/rail-transit/train-online', feature_id: 'web.rail_train_online', parent_id: 'rail', order: 30, icon: 'rail', qt_feature_id: 'rail.train_online', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.car-network-diagnostic', title: '车内通信检测', route_name: 'rail-car-network-diagnostic', route_path: '/rail-transit/car-network-diagnostic', feature_id: 'web.rail_car_network_diagnostic', parent_id: 'rail', order: 40, icon: 'rail', qt_feature_id: 'rail.car_network_diagnostic', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.train-communication', title: '在线列车车地通信检测', route_name: 'train-communication', route_path: '/rail-transit/train-communication', feature_id: 'web.train_communication_monitoring', parent_id: 'rail', order: 50, icon: 'rail', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.trackside-ap-business', title: '轨旁 AP 业务', route_name: 'rail-trackside-ap-business', route_path: '/rail-transit/trackside-ap-business', feature_id: 'web.rail_trackside_ap_business', parent_id: 'rail', order: 60, icon: 'rail', qt_feature_id: 'rail.trackside_ap_business', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.mesh-analysis', title: 'MR 原始 MESH 日志分析', route_name: 'mesh-analysis', route_path: '/rail-transit/mesh-analysis', feature_id: 'web.mesh_analysis', parent_id: 'rail', order: 70, icon: 'rail', qt_feature_id: 'rail.raw_mesh_log_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr', title: '车载 MR 实时收集', route_name: 'online-mr-realtime', route_path: '/rail-transit/online-mr', feature_id: 'web.online_mr_realtime', parent_id: 'rail', order: 80, icon: 'rail', qt_feature_id: 'rail.online_mr_collection', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'rail.online-mr-analysis', title: '车载 MR 收集分析', route_name: 'online-mr-analysis', route_path: '/rail-transit/online-mr-analysis', feature_id: 'web.online_mr_analysis', parent_id: 'rail', order: 90, icon: 'rail', qt_feature_id: 'rail.online_mr_analysis', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  ] }),
  item({ navigation_id: 'config', title: '配置采集中心', route_name: 'config-collection', route_path: '/config-center', feature_id: 'web.config_collection', order: 50, icon: 'config', qt_page_id: 'config_collection', qt_feature_id: 'module.config_collection', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'files', title: '文件管理', route_name: 'file-management', route_path: '/file-manager', feature_id: 'web.file_management', order: 60, icon: 'files', qt_page_id: 'file_management', qt_feature_id: 'module.file_management', parity_state: 'READ_ONLY', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'network', title: '网络工具', feature_id: 'module.network_tools', order: 70, icon: 'network', qt_page_id: 'network_tools', qt_feature_id: 'module.network_tools', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true, children: [
    item({ navigation_id: 'network.traffic', title: '流量测试', route_name: 'network-tools-traffic', route_path: '/network-tools/traffic', feature_id: 'network_tools.traffic', parent_id: 'network', order: 10, icon: 'network', qt_feature_id: 'network_tools.traffic', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'network.toolbox', title: '小工具与连通性检测', route_name: 'network-tools-toolbox', route_path: '/network-tools/toolbox', feature_id: 'web.network_tools_toolbox', parent_id: 'network', order: 20, icon: 'network', qt_feature_id: 'network_tools.toolbox', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
    item({ navigation_id: 'network.wireless-scan', title: '无线扫描', route_path: '/network-tools/wireless-scan', feature_id: 'web.network_tools_wireless_scan', parent_id: 'network', order: 30, icon: 'network', qt_feature_id: 'network_tools.wireless_scan', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  ] }),
  item({ navigation_id: 'tasks', title: '任务中心', route_name: 'tasks', route_path: '/tasks', feature_id: 'web.job_center', order: 80, icon: 'tasks', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'agents', title: 'Agent 管理', route_name: 'agents', route_path: '/agents', feature_id: 'web.agent_management', order: 90, icon: 'agent', parity_state: 'PARTIAL', desktop_only: false, internal_only: false, implemented: true }),
  item({ navigation_id: 'command-reference', title: '命令说明', route_path: '/command-reference', feature_id: 'web.command_reference', order: 100, icon: 'system', qt_page_id: 'command_reference', qt_feature_id: 'module.command_reference', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  item({ navigation_id: 'logs', title: '日志中心', route_path: '/logs', feature_id: 'web.logs', order: 110, icon: 'system', qt_page_id: 'logs', qt_feature_id: 'module.logs', parity_state: 'NOT_STARTED', desktop_only: false, internal_only: false, implemented: false }),
  item({ navigation_id: 'settings', title: '系统设置', route_path: '/settings', feature_id: 'web.system_settings', order: 120, icon: 'system', qt_page_id: 'system_settings', qt_feature_id: 'module.system_settings', parity_state: 'NOT_STARTED', desktop_only: true, internal_only: false, implemented: false }),
  item({ navigation_id: 'feature-flags', title: '功能开关配置', route_path: '/feature-flags', feature_id: 'web.feature_switch', order: 130, icon: 'system', qt_page_id: 'feature_flags', qt_feature_id: 'system.feature_flags', parity_state: 'NOT_STARTED', desktop_only: true, internal_only: true, implemented: false }),
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
      if (entry.feature_id && !isVisible(entry.feature_id)) return false
      return entry.children.length > 0 || Boolean(entry.route_name && entry.route_path)
    })
    .sort((left, right) => left.order - right.order)
}
