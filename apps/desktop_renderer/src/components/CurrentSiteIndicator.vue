<script setup lang="ts">
import { Location } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getActiveSite, type SiteRecord } from '../api/siteStorage'
import { onPlatformRuntimeStatusChanged } from '../platform/runtime'
import { useWorkspaceStore } from '../stores/workspace'
import {
  SITE_CONTEXT_CHANGED_EVENT,
  SITE_SWITCH_METADATA_EVENT,
  type SiteSwitchMetadataDetail,
} from '../workspace/site-switch'

type LoadState = 'loading' | 'switching' | 'ready' | 'error'

const router = useRouter()
const workspace = useWorkspaceStore()
const activeSite = ref<Pick<SiteRecord, 'site_id' | 'display_name'> | null>(null)
const loadState = ref<LoadState>('loading')
let loadSequence = 0
let focusSequence = 0
let unsubscribe: (() => void) | undefined
const handleSiteContextChanged = () => { void loadCurrentSite() }
const handleSiteSwitchMetadata = (event: Event) => {
  const detail = (event as CustomEvent<SiteSwitchMetadataDetail>).detail
  if (!detail || detail.state === 'rollback') {
    void loadCurrentSite()
    return
  }
  ++loadSequence
  activeSite.value = { site_id: detail.siteId, display_name: detail.displayName }
  loadState.value = 'switching'
}

const siteName = computed(() => {
  if (loadState.value === 'loading') return '加载中…'
  if (loadState.value === 'error') return '读取失败'
  const name = activeSite.value?.display_name?.trim() || activeSite.value?.site_id?.trim() || '未选择'
  return loadState.value === 'switching' ? `${name}（加载中…）` : name
})
const fullLabel = computed(() => `当前局点：${siteName.value}`)

async function loadCurrentSite(): Promise<void> {
  const sequence = ++loadSequence
  loadState.value = 'loading'
  activeSite.value = null
  try {
    const site = await getActiveSite()
    if (sequence !== loadSequence) return
    activeSite.value = site
      ? { site_id: String(site.site_id || ''), display_name: String(site.display_name || '') }
      : null
    loadState.value = 'ready'
  } catch {
    if (sequence !== loadSequence) return
    activeSite.value = null
    loadState.value = 'error'
  }
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
    ++loadSequence
    activeSite.value = null
    loadState.value = status.state === 'failed' ? 'error' : 'loading'
  })
  void loadCurrentSite()
})

onBeforeUnmount(() => {
  ++loadSequence
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
    <span class="current-site-indicator__label">当前局点：</span>
    <span class="current-site-name">{{ siteName }}</span>
  </button>
</template>

<style scoped>
.current-site-indicator {
  display: flex;
  align-items: center;
  width: 100%;
  max-width: 280px;
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

.current-site-indicator__label {
  flex: 0 0 auto;
}

.current-site-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
