<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, DataBoard, Operation } from '@element-plus/icons-vue'

import { getHealth } from '../api/client'

const route = useRoute()
const router = useRouter()
const version = ref('')
const backendOnline = ref(false)
const activeMenu = computed(() => (route.path.startsWith('/agents') ? '/agents' : route.path.startsWith('/tasks') ? '/tasks' : '/'))

onMounted(async () => {
  try {
    const health = await getHealth()
    version.value = health.version
    backendOnline.value = health.status === 'ok'
  } catch {
    backendOnline.value = false
  }
})
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="224px" class="app-sidebar">
      <div class="brand">
        <div class="brand-mark">NC</div>
        <div>
          <strong>NetConsole</strong>
          <span>Web Console</span>
        </div>
      </div>
      <el-menu :default-active="activeMenu" class="app-menu" @select="router.push">
        <el-menu-item index="/">
          <el-icon><DataBoard /></el-icon>
          <span>Dashboard</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><Operation /></el-icon>
          <span>任务中心</span>
        </el-menu-item>
        <el-menu-item index="/agents">
          <el-icon><Connection /></el-icon>
          <span>Agent 管理</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-note">阶段 3 · Agent 控制面</div>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div>
          <div class="header-title">{{ route.meta.title || (route.name === 'tasks' ? '任务中心' : 'Dashboard') }}</div>
          <div class="header-subtitle">任务与 Agent 状态均以 Python 后端为控制入口</div>
        </div>
        <div class="header-status">
          <span :class="['status-dot', backendOnline ? 'online' : 'offline']"></span>
          <span>{{ backendOnline ? 'Backend Online' : 'Backend Offline' }}</span>
          <el-divider direction="vertical" />
          <span>v{{ version || '--' }}</span>
        </div>
      </el-header>
      <el-main class="app-main">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>
