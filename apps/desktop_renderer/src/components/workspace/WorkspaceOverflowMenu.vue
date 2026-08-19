<script setup lang="ts">
import { ArrowDown } from '@element-plus/icons-vue'

import type { WorkspaceTab } from '../../workspace/types'

defineProps<{ tabs: WorkspaceTab[]; activeTabId: string }>()
const emit = defineEmits<{ activate: [tabId: string] }>()
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-end">
    <el-button text circle :icon="ArrowDown" title="全部标签" aria-label="全部标签" />
    <template #dropdown>
      <el-dropdown-menu class="workspace-overflow-menu">
        <el-dropdown-item
          v-for="tab in tabs"
          :key="tab.id"
          :class="{ active: tab.id === activeTabId }"
          @click="emit('activate', tab.id)"
        >{{ tab.title }}</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>
