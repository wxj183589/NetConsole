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
      ],
    },
  ],
})

export default router
