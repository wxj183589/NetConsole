<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getSystemSettings } from '../api/systemSettings'
import { getPlatformAdapter } from '../platform/runtime'

const currentSite = ref('当前局点')
const backendOnline = ref(false)

onMounted(async () => {
  const runtime = getPlatformAdapter()
  const [backend, settings] = await Promise.allSettled([
    runtime.getBackendStatus(),
    getSystemSettings(),
  ])
  backendOnline.value = backend.status === 'fulfilled' && backend.value.state === 'ready'
  if (settings.status === 'fulfilled' && settings.value.current_site_name) {
    currentSite.value = settings.value.current_site_name
  }
})
</script>

<template>
  <el-container class="task-window-shell">
    <el-header class="task-window-header">
      <div>
        <h1>任务中心</h1>
        <p>{{ currentSite }}</p>
      </div>
      <div class="backend-state">
        <span :class="['status-dot', backendOnline ? 'online' : 'offline']"></span>
        {{ backendOnline ? 'Backend Online' : 'Backend Offline' }}
      </div>
    </el-header>
    <el-main class="task-window-main"><RouterView /></el-main>
  </el-container>
</template>

<style scoped>
.task-window-shell{min-height:100vh;background:var(--nc-bg-page)}
.task-window-header{display:flex;height:64px;align-items:center;justify-content:space-between;padding:0 22px;border-bottom:1px solid var(--nc-border-light);background:var(--nc-bg-card)}
.task-window-header h1{margin:0;color:var(--nc-text-primary);font-size:18px}
.task-window-header p{margin:4px 0 0;color:var(--nc-text-secondary);font-size:12px}
.backend-state{display:flex;align-items:center;gap:8px;color:var(--nc-text-secondary);font-size:12px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--nc-danger)}
.status-dot.online{background:var(--nc-success)}
.task-window-main{min-width:0;padding:18px 22px 22px;overflow:auto}
</style>
