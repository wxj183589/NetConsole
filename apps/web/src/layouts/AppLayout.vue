<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Connection,
  DataBoard,
  Files,
  Fold,
  Menu as MenuIcon,
  Monitor,
  OfficeBuilding,
  Operation,
  Setting,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getHealth, getWebBuildMeta } from '../api/client'
import { isFeatureEnabled, isFeatureVisible, loadWebFeatures } from '../features'
import {
  findNavigation,
  visibleNavigation,
  type NavigationItem,
} from '../navigation/registry'
import DesktopRuntimeStatus from '../components/DesktopRuntimeStatus.vue'
import { navigationTitle, t } from '../i18n/runtime'

const COLLAPSED_KEY = 'netconsole.web.sidebar.collapsed'
const OPEN_GROUPS_KEY = 'netconsole.web.sidebar.open-groups'
const BUILD_MISMATCH_MESSAGE = '当前 Web 前端资源与后端版本不一致，请重新构建 Web 资源。'

const route = useRoute()
const router = useRouter()
const version = ref('')
const backendBuildId = ref('')
const frontendBuildId = ref('')
const frontendMetaLoaded = ref(false)
const backendOnline = ref(false)
const serverBuildWarningPresent = ref(Boolean(document.querySelector('[data-netconsole-build-warning]')))
const viewportWidth = ref(window.innerWidth)
const manualCollapsed = ref(sessionStorage.getItem(COLLAPSED_KEY) === '1')
const drawerOpen = ref(false)
const openGroups = ref<string[]>(loadOpenGroups())

const iconComponents = {
  dashboard: DataBoard,
  devices: Monitor,
  ac: OfficeBuilding,
  rail: Monitor,
  config: Operation,
  files: Files,
  network: Operation,
  tasks: Operation,
  agent: Connection,
  system: Setting,
}

const mobile = computed(() => viewportWidth.value < 850)
const sidebarCollapsed = computed(() => !mobile.value && (viewportWidth.value < 1100 || manualCollapsed.value))
const navigationItems = computed(() => visibleNavigation(isFeatureVisible))
const activeNavigation = computed(() => findNavigation(String(route.meta.navigationId || 'dashboard')))
const activeMenu = computed(() => activeNavigation.value?.route_path || '/')
const frontendMismatch = computed(() => (
  !import.meta.env.DEV
  && backendOnline.value
  && !serverBuildWarningPresent.value
  && (!frontendMetaLoaded.value || !frontendBuildId.value || frontendBuildId.value !== backendBuildId.value)
))

function loadOpenGroups(): string[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(OPEN_GROUPS_KEY) || '[]')
    return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
  } catch {
    return []
  }
}

function persistOpenGroups(): void {
  sessionStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify(openGroups.value))
}

function iconFor(entry: NavigationItem) {
  return iconComponents[entry.icon]
}

function toggleSidebar(): void {
  if (mobile.value) {
    drawerOpen.value = !drawerOpen.value
    return
  }
  manualCollapsed.value = !manualCollapsed.value
  sessionStorage.setItem(COLLAPSED_KEY, manualCollapsed.value ? '1' : '0')
}

async function selectNavigation(path: string): Promise<void> {
  if (path === '/tasks' && window.netconsoleDesktop && route.query.task_window !== '1') {
    try {
      const result = await window.netconsoleDesktop.openTaskWindow({})
      if (result.success) return
      ElMessage.error(result.error || '任务中心加载失败')
    } catch {
      ElMessage.error('任务中心加载失败')
    }
    await router.push(path)
    return
  }
  await router.push(path)
  if (mobile.value) drawerOpen.value = false
}

function openGroup(groupId: string): void {
  if (!openGroups.value.includes(groupId)) openGroups.value.push(groupId)
  persistOpenGroups()
}

function closeGroup(groupId: string): void {
  openGroups.value = openGroups.value.filter((item) => item !== groupId)
  persistOpenGroups()
}

function updateViewport(): void {
  viewportWidth.value = window.innerWidth
  if (!mobile.value) drawerOpen.value = false
}

watch(
  () => route.meta.navigationId,
  () => {
    const parentId = activeNavigation.value?.parent_id
    if (parentId) openGroup(parentId)
    if (mobile.value) drawerOpen.value = false
  },
  { immediate: true },
)

onMounted(async () => {
  window.addEventListener('resize', updateViewport)
  try {
    await loadWebFeatures()
  } catch {
    // 后端 Feature Gate 仍会拒绝禁用能力；离线时保留导航用于展示连接状态。
  }
  try {
    const health = await getHealth()
    version.value = health.version
    backendBuildId.value = health.build_id
    backendOnline.value = health.status === 'ok'
  } catch {
    backendOnline.value = false
  }
  if (!import.meta.env.DEV) {
    try {
      const metadata = await getWebBuildMeta()
      frontendBuildId.value = metadata.build_id
      frontendMetaLoaded.value = true
    } catch {
      frontendMetaLoaded.value = false
    }
  }
})

onBeforeUnmount(() => window.removeEventListener('resize', updateViewport))
</script>

<template>
  <el-container class="app-shell">
    <div v-if="mobile && drawerOpen" class="sidebar-overlay" @click="drawerOpen = false"></div>
    <el-aside
      :width="sidebarCollapsed ? 'var(--nc-shell-sidebar-collapsed-width)' : 'var(--nc-shell-sidebar-width)'"
      :class="['app-sidebar', { collapsed: sidebarCollapsed, mobile, open: drawerOpen }]"
    >
      <div class="brand">
        <div class="brand-mark">NC</div>
        <div v-if="!sidebarCollapsed" class="brand-copy">
          <strong>NetConsole</strong>
          <span>{{ t('shell.console', 'Web Console') }}</span>
        </div>
      </div>
      <el-menu
        :default-active="activeMenu"
        :default-openeds="openGroups"
        :collapse="sidebarCollapsed"
        :collapse-transition="false"
        class="app-menu"
        @select="selectNavigation"
        @open="openGroup"
        @close="closeGroup"
      >
        <template v-for="entry in navigationItems" :key="entry.navigation_id">
          <el-sub-menu v-if="entry.children.length" :index="entry.navigation_id">
            <template #title>
              <el-icon><component :is="iconFor(entry)" /></el-icon>
              <span>{{ navigationTitle(entry.navigation_id, entry.title) }}</span>
            </template>
            <el-menu-item
              v-for="child in entry.children"
              :key="child.navigation_id"
              :index="child.route_path"
              :disabled="Boolean(child.feature_id && !isFeatureEnabled(child.feature_id))"
            >{{ navigationTitle(child.navigation_id, child.title) }}</el-menu-item>
          </el-sub-menu>
          <el-menu-item
            v-else
            :index="entry.route_path"
            :disabled="Boolean(entry.feature_id && !isFeatureEnabled(entry.feature_id))"
          >
            <el-icon><component :is="iconFor(entry)" /></el-icon>
            <span>{{ navigationTitle(entry.navigation_id, entry.title) }}</span>
          </el-menu-item>
        </template>
      </el-menu>
      <div v-if="!sidebarCollapsed" class="sidebar-note">{{ t('shell.local_console', '本地网络运维控制台') }}</div>
    </el-aside>
    <el-container class="app-workspace">
      <el-header class="app-header">
        <div class="header-leading">
          <el-button class="sidebar-toggle" text :icon="mobile ? MenuIcon : Fold" :aria-label="t('shell.toggle_navigation', '切换导航')" @click="toggleSidebar" />
          <div>
            <div class="header-title">{{ route.meta.title || 'Dashboard' }}</div>
            <div class="header-subtitle">{{ t('shell.subtitle', 'Vue、FastAPI 与 Python ApplicationService 共用同一业务核心') }}</div>
          </div>
        </div>
        <div class="header-status">
          <DesktopRuntimeStatus />
          <span :class="['status-dot', backendOnline ? 'online' : 'offline']"></span>
          <span>{{ backendOnline ? t('shell.backend_online', 'Backend Online') : t('shell.backend_offline', 'Backend Offline') }}</span>
          <el-divider direction="vertical" />
          <span>v{{ version || '--' }}</span>
        </div>
      </el-header>
      <el-main class="app-main">
        <el-alert
          v-if="frontendMismatch"
          class="frontend-build-warning"
          :title="t('shell.build_mismatch', BUILD_MISMATCH_MESSAGE)"
          type="warning"
          show-icon
          :closable="false"
        />
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>
