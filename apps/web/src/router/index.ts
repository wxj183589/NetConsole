import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '../layouts/AppLayout.vue'
import { isFeatureEnabled, loadWebFeatures } from '../features'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'network/devices', name: 'device-management', component: () => import('../views/devices/DeviceManagementView.vue'), meta: { title: '设备管理', featureId: 'web.device_management' } },
        { path: 'config-center', name: 'config-collection', component: () => import('../views/config-collection/ConfigCollectionView.vue'), meta: { title: '配置采集中心', featureId: 'web.config_collection' } },
        { path: 'file-manager', name: 'file-management', component: () => import('../views/file-management/FileManagementView.vue'), meta: { title: '文件管理', featureId: 'web.file_management' } },
        { path: 'tasks', name: 'tasks', component: () => import('../views/job-center/JobCenterView.vue'), meta: { title: '任务中心' } },
        { path: 'agents', name: 'agents', component: () => import('../views/agents/AgentListView.vue'), meta: { title: 'Agent 管理' } },
        { path: 'ac-management', name: 'ac-management', component: () => import('../views/ac-management/AcManagementView.vue'), meta: { title: 'AC 管理 / 只读' } },
        { path: 'ac-management/mesh-links', name: 'ac-mesh-links', component: () => import('../views/ac-management/AcMeshLinkView.vue'), meta: { title: 'AC 管理 / Mesh-Link 在线监控' } },
        { path: 'rail-transit/online-mr', name: 'online-mr-realtime', component: () => import('../views/rail-transit/OnlineMrRealtimeView.vue'), meta: { title: '轨道交通 / 车载 MR 实时展示' } },
        { path: 'rail-transit/base-data', name: 'rail-transit-base-data', component: () => import('../views/rail-transit/RailTransitBaseDataView.vue'), meta: { title: '轨道交通 / 基础资料' } },
        { path: 'rail-transit/wireless-dashboard', name: 'rail-transit-wireless-dashboard', component: () => import('../views/rail-transit/RailTransitWirelessDashboardView.vue'), meta: { title: '轨道交通 / 无线综合看板' } },
        { path: 'rail-transit/train-communication', name: 'train-communication', component: () => import('../views/rail-transit/TrainCommunicationView.vue'), meta: { title: '轨道交通 / 在线列车通信检测' } },
        { path: 'rail-transit/mesh-analysis', name: 'mesh-analysis', component: () => import('../views/rail-transit/MeshAnalysisView.vue'), meta: { title: '轨道交通 / Mesh 原始日志分析' } },
        { path: 'network-tools/traffic', name: 'network-tools-traffic', component: () => import('../views/network-tools/TrafficTestView.vue'), meta: { title: '网络工具 / 流量测试' } },
        { path: 'network-tools/overview', name: 'network-tools-overview', component: () => import('../views/network-tools/NetworkToolsView.vue'), meta: { title: '网络工具', featureId: 'web.network_tools' } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const featureId = typeof to.meta.featureId === 'string' ? to.meta.featureId : ''
  if (!featureId) return true
  try {
    await loadWebFeatures()
  } catch {
    return true
  }
  return isFeatureEnabled(featureId) ? true : { name: 'dashboard' }
})

export default router
