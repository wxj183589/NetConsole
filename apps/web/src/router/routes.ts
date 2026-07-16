import type { RouteRecordRaw } from 'vue-router'


export const appRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    component: () => import('../layouts/AppLayout.vue'),
    children: [
      { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { navigationId: 'dashboard', moduleId: 'dashboard', title: 'Dashboard', desktopOnly: false } },
      { path: 'network/devices', name: 'device-management', component: () => import('../views/devices/DeviceManagementView.vue'), meta: { navigationId: 'devices', featureId: 'web.device_management', moduleId: 'devices', title: '设备管理', desktopOnly: false } },
      { path: 'ac-management', redirect: { name: 'ac-fit-aps' }, meta: { moduleId: 'ac', title: 'AC 管理', desktopOnly: false, hiddenRoute: true } },
      { path: 'ac-management/fit-aps', name: 'ac-fit-aps', component: () => import('../views/ac-management/AcManagementView.vue'), meta: { navigationId: 'ac.fit-aps', featureId: 'web.ac_fit_ap_resources', moduleId: 'ac', title: 'AC 管理 / FIT-AP 资源', desktopOnly: false } },
      { path: 'ac-management/optical', name: 'ac-optical', component: () => import('../views/ac-management/AcManagementView.vue'), meta: { navigationId: 'ac.optical', featureId: 'web.ac_optical', moduleId: 'ac', title: 'AC 管理 / 光衰', desktopOnly: false } },
      { path: 'ac-management/extensions', name: 'ac-extensions', component: () => import('../views/ac-management/AcWebParityView.vue'), meta: { navigationId: 'ac.extensions', featureId: 'web.ac_extensions', moduleId: 'ac', title: 'AC 管理 / AP 扩展信息', desktopOnly: false } },
      { path: 'ac-management/mesh-links', name: 'ac-mesh-links', component: () => import('../views/ac-management/AcMeshLinkView.vue'), meta: { navigationId: 'ac.mesh-links', featureId: 'web.ac_mesh_links', moduleId: 'ac', title: 'AC 管理 / Mesh-Link 在线监控', desktopOnly: false } },
      { path: 'rail-transit/wireless-dashboard', name: 'rail-transit-wireless-dashboard', component: () => import('../views/rail-transit/RailTransitWirelessDashboardView.vue'), meta: { navigationId: 'rail.wireless-dashboard', featureId: 'web.rail_transit_wireless_dashboard', moduleId: 'rail', title: '轨道交通 / 无线综合看板', desktopOnly: false } },
      { path: 'rail-transit/base-data', name: 'rail-transit-base-data', component: () => import('../views/rail-transit/RailTransitBaseDataView.vue'), meta: { navigationId: 'rail.base-data', featureId: 'web.rail_transit_base_data', moduleId: 'rail', title: '轨道交通 / 基础资料', desktopOnly: false } },
      { path: 'rail-transit/train-online', name: 'rail-train-online', component: () => import('../views/rail-transit/VehicleMrOnlineView.vue'), meta: { navigationId: 'rail.train-online', featureId: 'web.rail_train_online', moduleId: 'rail', title: '轨道交通 / 列车在线情况', desktopOnly: false } },
      { path: 'rail-transit/car-network-diagnostic', name: 'rail-car-network-diagnostic', component: () => import('../views/rail-transit/CarNetworkDiagnosticView.vue'), meta: { navigationId: 'rail.car-network-diagnostic', featureId: 'web.rail_car_network_diagnostic', moduleId: 'rail', title: '轨道交通 / 车内通信检测', desktopOnly: false } },
      { path: 'rail-transit/train-communication', name: 'train-communication', component: () => import('../views/rail-transit/TrainCommunicationView.vue'), meta: { navigationId: 'rail.train-communication', featureId: 'web.train_communication_monitoring', moduleId: 'rail', title: '轨道交通 / 在线列车车地通信检测', desktopOnly: false } },
      { path: 'rail-transit/trackside-ap-business', name: 'rail-trackside-ap-business', component: () => import('../views/rail-transit/TracksideApBusinessView.vue'), meta: { navigationId: 'rail.trackside-ap-business', featureId: 'web.rail_trackside_ap_business', moduleId: 'rail', title: '轨道交通 / 轨旁 AP 业务', desktopOnly: false } },
      { path: 'rail-transit/trackside-ap-plan', name: 'rail-trackside-ap-plan', component: () => import('../views/rail-transit/TracksideApPlanView.vue'), meta: { navigationId: 'rail.trackside-ap-plan', featureId: 'web.rail_trackside_ap_plan', moduleId: 'rail', title: '轨道交通 / 轨旁 AP 规划', desktopOnly: false } },
      { path: 'rail-transit/mesh-analysis', name: 'mesh-analysis', component: () => import('../views/rail-transit/MeshAnalysisView.vue'), meta: { navigationId: 'rail.mesh-analysis', featureId: 'web.mesh_analysis', moduleId: 'rail', title: '轨道交通 / MR 原始 MESH 日志分析', desktopOnly: false } },
      { path: 'rail-transit/online-mr', name: 'online-mr-realtime', component: () => import('../views/rail-transit/OnlineMrRealtimeView.vue'), meta: { navigationId: 'rail.online-mr', featureId: 'web.online_mr_realtime', moduleId: 'rail', title: '轨道交通 / 车载 MR 实时收集', desktopOnly: false } },
      { path: 'rail-transit/online-mr-analysis', name: 'online-mr-analysis', component: () => import('../views/rail-transit/OnlineMrAnalysisView.vue'), meta: { navigationId: 'rail.online-mr-analysis', featureId: 'web.online_mr_analysis', moduleId: 'rail', title: '轨道交通 / 车载 MR 收集分析', desktopOnly: false } },
      { path: 'config-center', name: 'config-collection', component: () => import('../views/config-collection/ConfigCollectionView.vue'), meta: { navigationId: 'config', featureId: 'web.config_collection', moduleId: 'config', title: '配置采集中心', desktopOnly: false } },
      { path: 'file-manager', name: 'file-management', component: () => import('../views/file-management/FileManagementView.vue'), meta: { navigationId: 'files', featureId: 'web.file_management', moduleId: 'files', title: '文件管理', desktopOnly: false } },
      { path: 'network-tools/traffic', name: 'network-tools-traffic', component: () => import('../views/network-tools/TrafficTestView.vue'), meta: { navigationId: 'network.traffic', featureId: 'network_tools.traffic', moduleId: 'network', title: '网络工具 / 流量测试', desktopOnly: false } },
      { path: 'network-tools/toolbox', name: 'network-tools-toolbox', component: () => import('../views/network-tools/NetworkToolsView.vue'), meta: { navigationId: 'network.toolbox', featureId: 'web.network_tools_toolbox', moduleId: 'network', title: '网络工具 / 小工具与连通性检测', desktopOnly: false } },
      { path: 'network-tools/wireless-scan', name: 'network-tools-wireless-scan', component: () => import('../views/network-tools/WirelessScanView.vue'), meta: { navigationId: 'network.wireless-scan', featureId: 'web.network_tools_wireless_scan', moduleId: 'network', title: '网络工具 / 无线扫描', desktopOnly: false } },
      { path: 'network-tools/overview', redirect: { name: 'network-tools-toolbox' }, meta: { moduleId: 'network', title: '网络工具', desktopOnly: false, hiddenRoute: true } },
      { path: 'tasks', name: 'tasks', component: () => import('../views/job-center/JobCenterView.vue'), meta: { navigationId: 'tasks', featureId: 'web.job_center', moduleId: 'tasks', title: '任务中心', desktopOnly: false } },
      { path: 'agents', name: 'agents', component: () => import('../views/agents/AgentListView.vue'), meta: { navigationId: 'agents', featureId: 'web.agent_management', moduleId: 'agents', title: 'Agent 管理', desktopOnly: false } },
      { path: 'settings', name: 'system-settings', component: () => import('../views/settings/SystemSettingsView.vue'), meta: { navigationId: 'settings', featureId: 'web.system_settings', moduleId: 'settings', title: '系统设置', desktopOnly: true } },
      { path: 'command-reference', name: 'command-reference', component: () => import('../views/command-reference/CommandReferenceView.vue'), meta: { navigationId: 'command-reference', featureId: 'web.command_reference', moduleId: 'command-reference', title: '命令说明', desktopOnly: false } },
    ],
  },
]
