import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '../layouts/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'tasks', name: 'tasks', component: () => import('../views/TaskCenterView.vue') },
        { path: 'agents', name: 'agents', component: () => import('../views/agents/AgentListView.vue'), meta: { title: 'Agent 管理' } },
        { path: 'rail-transit/online-mr', name: 'online-mr-realtime', component: () => import('../views/rail-transit/OnlineMrRealtimeView.vue'), meta: { title: '轨道交通 / 车载 MR 实时展示' } },
        { path: 'network-tools/traffic', name: 'network-tools-traffic', component: () => import('../views/network-tools/TrafficTestView.vue'), meta: { title: '网络工具 / 流量测试' } },
      ],
    },
  ],
})

export default router
