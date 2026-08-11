<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Close, Link, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { isFeatureVisible } from '../../features'
import { visibleNavigation } from '../../navigation/registry'
import { useWorkspaceStore } from '../../stores/workspace'
import type { WorkspaceTab } from '../../workspace/types'
import WorkspaceNewPageMenu from './WorkspaceNewPageMenu.vue'
import WorkspaceOverflowMenu from './WorkspaceOverflowMenu.vue'
import WorkspaceTabContextMenu from './WorkspaceTabContextMenu.vue'

const workspace = useWorkspaceStore()
const scrollHost = ref<HTMLElement>()
const contextVisible = ref(false)
const contextX = ref(0)
const contextY = ref(0)
const contextTab = ref<WorkspaceTab | null>(null)
const navigationItems = computed(() => visibleNavigation(isFeatureVisible))

async function activate(tabId: string): Promise<void> {
  await workspace.activateTab(tabId)
  await nextTick()
  document.querySelector(`[data-workspace-tab="${tabId}"]`)?.scrollIntoView({
    block: 'nearest',
    inline: 'nearest',
  })
}

function openContext(event: MouseEvent, tab: WorkspaceTab): void {
  contextVisible.value = true
  contextX.value = Math.min(event.clientX, window.innerWidth - 220)
  contextY.value = Math.min(event.clientY, window.innerHeight - 260)
  contextTab.value = tab
}

async function runContext(command: string): Promise<void> {
  const tab = contextTab.value
  contextVisible.value = false
  if (!tab) return
  if (command === 'popout') {
    const result = await workspace.popOutTab(tab.id)
    if (!result.success) ElMessage.error(result.error || '新窗口打开失败')
  } else if (command === 'duplicate') {
    const duplicated = await workspace.duplicateTab(tab.id)
    if (!duplicated) ElMessage.warning('该页面不允许复制标签')
  } else if (command === 'toggle-pin') {
    tab.pinned ? workspace.unpinTab(tab.id) : workspace.pinTab(tab.id)
  } else if (command === 'close') {
    await workspace.closeTab(tab.id)
  } else if (command === 'close-others') {
    await workspace.closeOtherTabs(tab.id)
  } else if (command === 'close-right') {
    workspace.closeTabsToRight(tab.id)
  }
}

async function popOutActive(): Promise<void> {
  const result = await workspace.popOutTab()
  if (!result.success) ElMessage.error(result.error || '新窗口打开失败')
}

function handleGlobalPointer(): void {
  contextVisible.value = false
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.defaultPrevented || isEditableTarget(event.target)) return
  const key = event.key.toLowerCase()
  if (event.ctrlKey && !event.shiftKey && key === 'w') {
    event.preventDefault()
    void workspace.closeTab(workspace.activeTabId)
    return
  }
  if (event.ctrlKey && key === 'tab') {
    event.preventDefault()
    const current = workspace.tabs.findIndex((tab) => tab.id === workspace.activeTabId)
    const direction = event.shiftKey ? -1 : 1
    const next = (current + direction + workspace.tabs.length) % workspace.tabs.length
    void activate(workspace.tabs[next].id)
    return
  }
  if (event.ctrlKey && event.shiftKey && key === 'n') {
    event.preventDefault()
    void workspace.createWorkspaceWindow().then((result) => {
      if (!result.success) ElMessage.error(result.error || '新建工作区窗口失败')
    })
    return
  }
  if (event.ctrlKey && event.shiftKey && key === 'd') {
    event.preventDefault()
    void popOutActive()
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target instanceof Element ? target : null
  return Boolean(element?.closest(
    'input, textarea, select, [contenteditable="true"], .monaco-editor, .CodeMirror',
  ))
}

onMounted(() => {
  window.addEventListener('click', handleGlobalPointer)
  window.addEventListener('keydown', handleKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('click', handleGlobalPointer)
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="workspace-tab-bar" role="tablist" aria-label="工作区标签">
    <WorkspaceNewPageMenu :items="navigationItems" @select="workspace.openOrActivateRoute" />
    <div ref="scrollHost" class="workspace-tab-scroll">
      <button
        v-for="tab in workspace.tabs"
        :key="tab.id"
        :data-workspace-tab="tab.id"
        :class="['workspace-tab', { active: tab.id === workspace.activeTabId, pinned: tab.pinned }]"
        type="button"
        role="tab"
        :aria-selected="tab.id === workspace.activeTabId"
        :title="tab.title"
        @click="activate(tab.id)"
        @auxclick.middle="workspace.closeTab(tab.id)"
        @contextmenu.prevent="openContext($event, tab)"
      >
        <el-icon v-if="tab.pinned" class="workspace-tab__pin"><Lock /></el-icon>
        <span class="workspace-tab__title">{{ tab.title }}</span>
        <span
          v-if="!tab.pinned"
          class="workspace-tab__close"
          role="button"
          aria-label="关闭标签"
          @click.stop="workspace.closeTab(tab.id)"
        ><el-icon><Close /></el-icon></span>
      </button>
    </div>
    <el-tooltip content="在新窗口打开" placement="bottom">
      <el-button text circle :icon="Link" aria-label="在新窗口打开" @click="popOutActive" />
    </el-tooltip>
    <WorkspaceOverflowMenu
      :tabs="workspace.tabs"
      :active-tab-id="workspace.activeTabId"
      @activate="activate"
    />
    <WorkspaceTabContextMenu
      :visible="contextVisible"
      :x="contextX"
      :y="contextY"
      :tab="contextTab"
      :allow-duplicate="Boolean(contextTab && workspace.canDuplicateTab(contextTab.id))"
      @command="runContext"
    />
  </div>
</template>
