<script setup lang="ts">
import { Location } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { onPlatformRuntimeStatusChanged } from '../platform/runtime'
import {
  activeSiteContext,
  clearSiteContext,
  markSiteContextRollback,
  markSiteContextSwitching,
  refreshSiteContext,
  siteContextState,
} from '../stores/siteContext'
import { useWorkspaceStore } from '../stores/workspace'
import {
  SITE_CONTEXT_CHANGED_EVENT,
  SITE_SWITCH_METADATA_EVENT,
  type SiteSwitchMetadataDetail,
} from '../workspace/site-switch'

type LoadState = 'loading' | 'switching' | 'ready' | 'error'

const router = useRouter()
const workspace = useWorkspaceStore()
const activeSite = activeSiteContext
const loadState = siteContextState
let focusSequence = 0
let unsubscribe: (() => void) | undefined
const handleSiteContextChanged = (event: Event) => {
  const detail = (event as CustomEvent<unknown>).detail
  if (detail && typeof detail === 'object') return
  void loadCurrentSite()
}
const handleSiteSwitchMetadata = (event: Event) => {
  const detail = (event as CustomEvent<SiteSwitchMetadataDetail>).detail
  if (!detail || detail.state === 'rollback') {
    markSiteContextRollback()
    return
  }
  markSiteContextSwitching()
}

const siteName = computed(() => {
  if (loadState.value === 'loading') return '加载中…'
  if (loadState.value === 'error') return '读取失败'
  const name = activeSite.value?.displayName?.trim() || activeSite.value?.siteId?.trim() || '未选择'
  return loadState.value === 'switching' ? `${name}（切换中…）` : name
})
const fullLabel = computed(() => `当前局点：${siteName.value}`)

async function loadCurrentSite(): Promise<void> {
  await refreshSiteContext().catch(() => undefined)
}

async function openSiteStorage(): Promise<void> {
  try {
    const settingsRoute = router.getRoutes().find((record) => record.meta.navigationId === 'settings')
    if (!settingsRoute?.name) throw new Error('system settings route is unavailable')
    const target = router.resolve({
      name: settingsRoute.name,
      query: {
        section: 'site-storage',
        site_focus: `${Date.now()}-${++focusSequence}`,
      },
    }).fullPath
    await workspace.openOrActivateRoute(target)
  } catch {
    ElMessage.warning('系统设置页面暂不可用')
  }
}

onMounted(() => {
  window.addEventListener(SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  window.addEventListener(SITE_SWITCH_METADATA_EVENT, handleSiteSwitchMetadata)
  unsubscribe = onPlatformRuntimeStatusChanged((status) => {
    if (status.state === 'ready') {
      void loadCurrentSite()
      return
    }
    clearSiteContext(status.state === 'failed' ? 'error' : 'loading')
  })
  void loadCurrentSite()
})

onBeforeUnmount(() => {
  window.removeEventListener(SITE_CONTEXT_CHANGED_EVENT, handleSiteContextChanged)
  window.removeEventListener(SITE_SWITCH_METADATA_EVENT, handleSiteSwitchMetadata)
  unsubscribe?.()
})
</script>

<template>
  <button
    class="current-site-indicator"
    :class="{ 'is-error': loadState === 'error', 'is-switching': loadState === 'switching' }"
    type="button"
    :title="fullLabel"
    :aria-label="`${fullLabel}，进入局点与数据管理`"
    data-testid="current-site-indicator"
    @click="openSiteStorage"
  >
    <el-icon class="current-site-indicator__icon"><Location /></el-icon>
    <span class="current-site-context">
      <span class="current-site-context__site" :title="`当前局点：${siteName}`">
        当前局点：<span class="current-site-name">{{ siteName }}</span>
      </span>
    </span>
  </button>
</template>

<style scoped>
.current-site-indicator {
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 260px;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  color: var(--nc-text-secondary);
  font: inherit;
  background: var(--nc-bg-header);
  border: 1px solid color-mix(in srgb, var(--nc-primary), transparent 35%);
  border-radius: 6px;
  cursor: pointer;
  transition: background-color .16s ease, border-color .16s ease, color .16s ease;
}

.current-site-indicator:hover,
.current-site-indicator:focus-visible {
  color: var(--nc-text-primary);
  background: var(--nc-bg-hover);
  border-color: var(--nc-primary);
  outline: none;
}

.current-site-indicator.is-error {
  border-color: var(--el-color-warning-light-3);
}

.current-site-indicator.is-switching {
  border-color: var(--el-color-primary-light-3);
}

.current-site-indicator__icon {
  flex: 0 0 auto;
  margin-right: 6px;
  color: var(--nc-primary);
}

.current-site-context {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  min-width: 0;
  gap: 6px;
  overflow: hidden;
  white-space: nowrap;
}

.current-site-context__site {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.current-site-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
