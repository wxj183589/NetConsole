import { createRouter, createWebHistory } from 'vue-router'

import AppLayout from '../layouts/AppLayout.vue'
import DashboardView from '../views/DashboardView.vue'
import TaskCenterView from '../views/TaskCenterView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        { path: '', name: 'dashboard', component: DashboardView },
        { path: 'tasks', name: 'tasks', component: TaskCenterView },
      ],
    },
  ],
})

export default router
