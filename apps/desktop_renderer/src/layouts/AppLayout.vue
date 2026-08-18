<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Connection,
  DataBoard,
  Briefcase,
  Files,
  Fold,
  Menu as MenuIcon,
  Monitor,
  OfficeBuilding,
  Operation,
  Setting,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { getHealth, getRendererBuildMeta } from '../api/client'
import {
  getEditionRuntimeStatus,
  lockCustomerEdition,
  unlockCustomerEdition,
} from '../api/edition'
import { isFeatureEnabled, isFeatureVisible, loadRendererFeatures } from '../features'
import {
  findNavigation,
  visibleNavigation,
  type NavigationItem,
} from '../navigation/registry'
import DesktopRuntimeStatus from '../components/DesktopRuntimeStatus.vue'
import CurrentSiteIndicator from '../components/CurrentSiteIndicator.vue'
import WorkspaceTabBar from '../components/workspace/WorkspaceTabBar.vue'
import GlobalTaskCenter from '../task-center/components/GlobalTaskCenter.vue'
import { navigationTitle, t } from '../i18n/runtime'
import { visibleVersionIdentity } from '../platform/buildIdentity'
import {
  getPlatformAdapter,
  onPlatformRuntimeStatusChanged,
} from '../platform/runtime'
import {
  startExportSaveCoordinator,
  stopExportSaveCoordinator,
} from '../composables/useUserSelectedExport'
import { useWorkspaceStore } from '../stores/workspace'
import AppRouteView from './AppRouteView.vue'

const COLLAPSED_KEY = 'netconsole.desktop.sidebar.collapsed'
const OPEN_GROUPS_KEY = 'netconsole.desktop.sidebar.open-groups'
const BUILD_MISMATCH_MESSAGE = '当前 Desktop Renderer 资源与后端版本不一致，请重新构建桌面界面资源。'
const BRAND_LOGO_URL = '/branding/netconsole.png'

const route = useRoute()
const workspace = useWorkspaceStore()
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
const editionActionBusy = ref(false)
let removeTraySiteSwitchListener: (() => void) | undefined
let removeRuntimeStatusListener: (() => void) | undefined
let backendHealthGeneration = 0

const iconComponents = {
  dashboard: DataBoard,
  devices: Monitor,
  ac: OfficeBuilding,
  rail: Monitor,
  config: Operation,
  files: Files,
  network: Operation,
  tools: Briefcase,
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
  await workspace.openOrActivateRoute(path)
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

async function openChangelog(): Promise<void> {
  await workspace.openOrActivateRoute('/logs?tab=changelog')
}

async function handleVersionClick(event: MouseEvent): Promise<void> {
  if (!event.shiftKey || editionActionBusy.value) return
  event.preventDefault()
  event.stopPropagation()
  editionActionBusy.value = true
  try {
    const status = await getEditionRuntimeStatus()
    if (status.edition === 'full') {
      ElMessage.info('当前已经是完整版本')
      return
    }
    if (status.edition !== 'customer') {
      ElMessage.info('当前运行版本未配置客户版功能维护')
      return
    }
    if (status.relock_available) {
      await ElMessageBox.confirm(
        '当前客户版已临时开启完整功能。恢复客户模式后，未交付功能将重新隐藏。',
        '恢复客户模式',
        {
          type: 'warning',
          confirmButtonText: '恢复客户模式',
          cancelButtonText: '取消',
        },
      )
      await lockCustomerEdition()
      await loadRendererFeatures(true)
      ElMessage.success('已恢复客户模式')
      window.location.reload()
      return
    }
    if (!status.admin_unlock_available) {
      ElMessage.warning('当前客户版未配置维护密码，无法开启完整功能')
      return
    }
    const { value } = await ElMessageBox.prompt(
      '请输入客户版打包时配置的维护密码。完整功能仅在本次运行中生效，重启后自动恢复客户模式。',
      '开启完整功能',
      {
        confirmButtonText: '验证并开启',
        cancelButtonText: '取消',
        inputType: 'password',
        inputPlaceholder: '维护密码',
        inputValidator: (input) => Boolean(String(input || '').trim()) || '请输入维护密码',
      },
    )
    await unlockCustomerEdition(String(value))
    await loadRendererFeatures(true)
    ElMessage.success('完整功能已临时开启')
    window.location.reload()
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '版本功能维护失败')
  } finally {
    editionActionBusy.value = false
  }
}

function updateViewport(): void {
  viewportWidth.value = window.innerWidth
  if (!mobile.value) drawerOpen.value = false
}

async function refreshBackendHealth(): Promise<void> {
  const generation = ++backendHealthGeneration
  try {
    const health = await getHealth()
    if (generation !== backendHealthGeneration) return
    if (import.meta.env.DEV) {
      version.value = visibleVersionIdentity(health.version, health.build_id)
    }
    backendBuildId.value = health.build_id
    backendOnline.value = health.status === 'ok'
  } catch {
    if (generation === backendHealthGeneration) backendOnline.value = false
  }
}

async function handleTraySiteSwitchRequested(siteId: string): Promise<void> {
  const query = new URLSearchParams({
    section: 'site-storage',
    site_focus: `tray-site-switch-${Date.now()}`,
    tray_site_switch: siteId,
  })
  try {
    await workspace.openOrActivateRoute(`/settings?${query}`)
  } catch {
    getPlatformAdapter().reportSiteSwitchState(false)
    ElMessage.error('无法打开局点切换页面')
  }
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
  startExportSaveCoordinator()
  removeRuntimeStatusListener = onPlatformRuntimeStatusChanged((status) => {
    if (status.state === 'ready') {
      void refreshBackendHealth()
      return
    }
    backendHealthGeneration += 1
    backendOnline.value = false
  })
  removeTraySiteSwitchListener = getPlatformAdapter().onTraySiteSwitchRequested((siteId) => {
    void handleTraySiteSwitchRequested(siteId)
  })
  try {
    await loadRendererFeatures()
  } catch {
    // Feature 快照不可用时保持 fail-closed，仅保留无 Feature Gate 的 Dashboard。
  }
  await refreshBackendHealth()
  if (!import.meta.env.DEV) {
    try {
      const metadata = await getRendererBuildMeta()
      frontendBuildId.value = metadata.build_id
      version.value = visibleVersionIdentity(metadata.app_version, metadata.build_id)
      frontendMetaLoaded.value = true
    } catch {
      frontendMetaLoaded.value = false
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  stopExportSaveCoordinator()
  removeTraySiteSwitchListener?.()
  removeRuntimeStatusListener?.()
})
</script>

<template>
  <el-container class="app-shell">
    <div v-if="mobile && drawerOpen" class="sidebar-overlay" @click="drawerOpen = false"></div>
    <el-aside
      :width="sidebarCollapsed ? 'var(--nc-shell-sidebar-collapsed-width)' : 'var(--nc-shell-sidebar-width)'"
      :class="['app-sidebar', { collapsed: sidebarCollapsed, mobile, open: drawerOpen }]"
    >
      <button
        type="button"
        class="brand"
        :aria-label="t('shell.open_dashboard', '打开 Dashboard')"
        @click="workspace.openOrActivateRoute('/')"
      >
        <img class="brand-logo" :src="BRAND_LOGO_URL" alt="NetConsole" />
        <div v-if="!sidebarCollapsed" class="brand-copy">
          <strong>NetConsole</strong>
          <span>{{ t('shell.console', 'NetConsole') }}</span>
        </div>
      </button>
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
            <div class="header-title">{{ workspace.activeTab?.title || route.meta.title || 'Dashboard' }}</div>
            <div class="header-subtitle">{{ t('shell.subtitle', 'Vue、FastAPI 与 Python ApplicationService 共用同一业务核心') }}</div>
          </div>
        </div>
        <div class="current-site-slot">
          <CurrentSiteIndicator />
        </div>
        <div class="header-status">
          <GlobalTaskCenter />
          <DesktopRuntimeStatus />
          <span :class="['status-dot', backendOnline ? 'online' : 'offline']"></span>
          <span>{{ backendOnline ? t('shell.backend_online', 'Backend Online') : t('shell.backend_offline', 'Backend Offline') }}</span>
          <el-divider direction="vertical" />
          <el-button
            text
            :loading="editionActionBusy"
            title="双击打开版本更新日志；Shift+单击进入版本功能维护"
            @click="handleVersionClick"
            @dblclick="openChangelog"
          >v{{ version || '--' }}</el-button>
        </div>
      </el-header>
      <WorkspaceTabBar />
      <el-main class="app-main">
        <el-alert
          v-if="frontendMismatch"
          class="frontend-build-warning"
          :title="t('shell.build_mismatch', BUILD_MISMATCH_MESSAGE)"
          type="warning"
          show-icon
          :closable="false"
        />
        <AppRouteView />
      </el-main>
    </el-container>
  </el-container>
</template>
