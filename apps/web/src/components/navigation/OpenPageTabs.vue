<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { Close, MoreFilled } from '@element-plus/icons-vue'

import { t } from '../../i18n/runtime'
import {
  useOpenPageTabsStore,
  type OpenPageTab,
} from '../../stores/openPageTabs'

type TabCommand = 'close-current' | 'close-others' | 'close-right' | 'close-all'

const router = useRouter()
const store = useOpenPageTabsStore()
const { tabs, activeRouteName } = storeToRefs(store)
const scrollHost = ref<HTMLElement | null>(null)

function scrollActiveTabIntoView(): void {
  void nextTick(() => {
    const host = scrollHost.value
    const active = host?.querySelector<HTMLElement>('.open-page-tab.is-active')
    active?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
  })
}

function handleWheel(event: WheelEvent): void {
  const host = scrollHost.value
  if (!host || host.scrollWidth <= host.clientWidth) return
  const delta = event.deltaY || event.deltaX
  if (!delta) return
  host.scrollLeft += delta
  event.preventDefault()
}

async function activateTab(tab: OpenPageTab): Promise<void> {
  store.setActiveRoute(tab.routeName)
  await router.push(tab.path)
}

async function closeTab(routeName: string): Promise<void> {
  const tab = tabs.value.find((item) => item.routeName === routeName)
  if (!tab?.closable) return
  if (String(router.currentRoute.value.name || '') === routeName) {
    const target = store.fallbackFor(routeName)
    await router.push(target.path)
    store.setActiveRoute(target.routeName)
  }
  store.removeTabs([routeName])
}

async function closeCurrent(): Promise<void> {
  if (!activeRouteName.value) return
  await closeTab(activeRouteName.value)
}

function closeOthers(): void {
  const active = activeRouteName.value
  store.removeTabs(tabs.value.flatMap((item) => (
    item.closable && item.routeName !== active ? [item.routeName] : []
  )))
}

function closeRight(): void {
  const activeIndex = tabs.value.findIndex((item) => item.routeName === activeRouteName.value)
  if (activeIndex < 0) return
  store.removeTabs(tabs.value.slice(activeIndex + 1).map((item) => item.routeName))
}

async function closeAll(): Promise<void> {
  if (activeRouteName.value && activeRouteName.value !== 'dashboard') {
    await router.push('/')
    store.setActiveRoute('dashboard')
  }
  store.removeTabs(tabs.value.filter((item) => item.closable).map((item) => item.routeName))
}

async function handleCommand(command: TabCommand): Promise<void> {
  if (command === 'close-current') await closeCurrent()
  else if (command === 'close-others') closeOthers()
  else if (command === 'close-right') closeRight()
  else await closeAll()
}

watch(activeRouteName, scrollActiveTabIntoView, { immediate: true })
</script>

<template>
  <nav class="open-page-tabs" :aria-label="t('shell.open_pages', '已打开页面')">
    <div ref="scrollHost" class="open-page-tabs__scroll" @wheel="handleWheel">
      <div
        v-for="tab in tabs"
        :key="tab.routeName"
        :class="['open-page-tab', { 'is-active': tab.routeName === activeRouteName }]"
        :title="tab.fullTitle"
        :aria-current="tab.routeName === activeRouteName ? 'page' : undefined"
        role="button"
        tabindex="0"
        @click="activateTab(tab)"
        @keydown.enter="activateTab(tab)"
        @keydown.space.prevent="activateTab(tab)"
      >
        <span class="open-page-tab__title">{{ tab.title }}</span>
        <button
          v-if="tab.closable"
          type="button"
          class="open-page-tab__close"
          :aria-label="t('shell.close_page', '关闭页面')"
          @click.stop="closeTab(tab.routeName)"
        >
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>
    <el-dropdown trigger="click" placement="bottom-end" @command="handleCommand">
      <el-button
        class="open-page-tabs__actions"
        text
        :icon="MoreFilled"
        :title="t('shell.page_tab_actions', '页面标签操作')"
        :aria-label="t('shell.page_tab_actions', '页面标签操作')"
      />
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="close-current" :disabled="activeRouteName === 'dashboard'">
            {{ t('shell.close_current_page', '关闭当前') }}
          </el-dropdown-item>
          <el-dropdown-item command="close-others">
            {{ t('shell.close_other_pages', '关闭其他') }}
          </el-dropdown-item>
          <el-dropdown-item command="close-right">
            {{ t('shell.close_right_pages', '关闭右侧') }}
          </el-dropdown-item>
          <el-dropdown-item command="close-all" divided>
            {{ t('shell.close_all_pages', '关闭全部可关闭标签') }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </nav>
</template>

<style scoped>
.open-page-tabs {
  display: flex;
  flex: 0 0 36px;
  min-width: 0;
  height: 36px;
  align-items: stretch;
  background: var(--nc-bg-header);
  border-bottom: 1px solid var(--nc-divider);
}

.open-page-tabs__scroll {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: stretch;
  padding-left: var(--nc-content-padding);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  white-space: nowrap;
}

.open-page-tabs__scroll::-webkit-scrollbar {
  display: none;
}

.open-page-tab {
  position: relative;
  display: inline-flex;
  min-width: 96px;
  max-width: 260px;
  height: 36px;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  color: var(--nc-text-secondary);
  background: transparent;
  border: 0;
  border-right: 1px solid var(--nc-divider);
  border-radius: 0;
  cursor: pointer;
  font: inherit;
  letter-spacing: 0;
}

.open-page-tab:hover {
  color: var(--nc-text-primary);
  background: var(--nc-bg-hover);
}

.open-page-tab:focus-visible {
  outline: 2px solid var(--nc-primary);
  outline-offset: -2px;
}

.open-page-tab.is-active {
  color: var(--nc-text-active);
  background: var(--nc-bg-app);
}

.open-page-tab.is-active::after {
  position: absolute;
  right: 8px;
  bottom: 0;
  left: 8px;
  height: 2px;
  background: var(--nc-primary);
  content: '';
}

.open-page-tab__title {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.open-page-tab__close {
  display: inline-flex;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
}

.open-page-tab__close:hover,
.open-page-tab__close:focus-visible {
  color: var(--nc-text-primary);
  background: var(--nc-bg-hover);
  outline: none;
}

.open-page-tabs__actions {
  width: 36px;
  height: 35px;
  flex: 0 0 36px;
  border-left: 1px solid var(--nc-divider);
  border-radius: 0;
}

@media (max-width: 850px) {
  .open-page-tabs__scroll {
    padding-left: 0;
  }

  .open-page-tab {
    max-width: 210px;
  }
}
</style>
