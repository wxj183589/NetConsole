<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Connection, DataBoard, Monitor, OfficeBuilding, Operation } from '@element-plus/icons-vue'

import { getHealth } from '../api/client'
import { isFeatureEnabled, isFeatureVisible, loadWebFeatures } from '../features'

const route = useRoute()
const router = useRouter()
const version = ref('')
const backendOnline = ref(false)
const activeMenu = computed(() => {
  if (route.path.startsWith('/network/devices')) return '/network/devices'
  if (route.path.startsWith('/network-tools/overview')) return '/network-tools/overview'
  if (route.path.startsWith('/network-tools/traffic')) return '/network-tools/traffic'
  if (route.path.startsWith('/config-center')) return '/config-center'
  if (route.path.startsWith('/file-manager')) return '/file-manager'
  if (route.path.startsWith('/rail-transit/online-mr')) return '/rail-transit/online-mr'
  if (route.path.startsWith('/rail-transit/base-data')) return '/rail-transit/base-data'
  if (route.path.startsWith('/rail-transit/wireless-dashboard')) return '/rail-transit/wireless-dashboard'
  if (route.path.startsWith('/rail-transit/train-communication')) return '/rail-transit/train-communication'
  if (route.path.startsWith('/rail-transit/mesh-analysis')) return '/rail-transit/mesh-analysis'
  if (route.path.startsWith('/agents')) return '/agents'
  if (route.path.startsWith('/ac-management/mesh-links')) return '/ac-management/mesh-links'
  if (route.path.startsWith('/ac-management')) return '/ac-management'
  if (route.path.startsWith('/tasks')) return '/tasks'
  return '/'
})

onMounted(async () => {
  try {
    await loadWebFeatures()
  } catch {
    // 后端 Feature Gate 仍会拒绝禁用能力；离线时保留导航用于展示连接状态。
  }
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
        <el-menu-item
          v-if="isFeatureVisible('web.device_management')"
          index="/network/devices"
          :disabled="!isFeatureEnabled('web.device_management')"
        >
          <el-icon><Monitor /></el-icon>
          <span>设备管理</span>
        </el-menu-item>
        <el-menu-item
          v-if="isFeatureVisible('web.config_collection')"
          index="/config-center"
          :disabled="!isFeatureEnabled('web.config_collection')"
        >
          <el-icon><Operation /></el-icon>
          <span>配置采集中心</span>
        </el-menu-item>
        <el-menu-item
          v-if="isFeatureVisible('web.file_management')"
          index="/file-manager"
          :disabled="!isFeatureEnabled('web.file_management')"
        >
          <el-icon><OfficeBuilding /></el-icon>
          <span>文件管理</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><Operation /></el-icon>
          <span>任务中心</span>
        </el-menu-item>
        <el-menu-item index="/agents">
          <el-icon><Connection /></el-icon>
          <span>Agent 管理</span>
        </el-menu-item>
        <el-sub-menu index="/ac-management">
          <template #title>
            <el-icon><OfficeBuilding /></el-icon>
            <span>AC 管理</span>
          </template>
          <el-menu-item index="/ac-management">FIT-AP 资源</el-menu-item>
          <el-menu-item index="/ac-management/mesh-links">Mesh-Link 在线监控</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="/rail-transit">
          <template #title>
            <el-icon><Monitor /></el-icon>
            <span>轨道交通</span>
          </template>
          <el-menu-item index="/rail-transit/base-data">基础资料</el-menu-item>
          <el-menu-item index="/rail-transit/wireless-dashboard">轨道交通无线看板</el-menu-item>
          <el-menu-item index="/rail-transit/train-communication">在线列车通信检测</el-menu-item>
          <el-menu-item index="/rail-transit/mesh-analysis">Mesh 原始日志分析</el-menu-item>
          <el-menu-item index="/rail-transit/online-mr">车载 MR 实时展示</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="/network-tools">
          <template #title>
            <el-icon><Operation /></el-icon>
            <span>网络工具</span>
          </template>
          <el-menu-item
            v-if="isFeatureVisible('web.network_tools')"
            index="/network-tools/overview"
            :disabled="!isFeatureEnabled('web.network_tools')"
          >网络工具总览</el-menu-item>
          <el-menu-item index="/network-tools/traffic">流量测试</el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="sidebar-note">Qt + Web 双形态</div>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div>
          <div class="header-title">{{ route.meta.title || (route.name === 'tasks' ? '任务中心' : 'Dashboard') }}</div>
          <div class="header-subtitle">Qt 与 Web 共用设备、任务、配置、文件、Agent 和 Traffic 业务核心</div>
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
