<script setup lang="ts">
import { Plus } from '@element-plus/icons-vue'

import type { NavigationItem } from '../../navigation/registry'

defineProps<{ items: NavigationItem[] }>()
const emit = defineEmits<{ select: [path: string] }>()
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-start">
    <el-button text circle :icon="Plus" title="新建页面" aria-label="新建页面" />
    <template #dropdown>
      <el-dropdown-menu class="workspace-new-page-menu">
        <template v-for="entry in items" :key="entry.navigation_id">
          <el-dropdown-item v-if="entry.route_path" @click="emit('select', entry.route_path)">{{ entry.title }}</el-dropdown-item>
          <template v-for="child in entry.children" v-else :key="child.navigation_id">
            <el-dropdown-item v-if="child.route_path" @click="emit('select', child.route_path)">{{ child.title }}</el-dropdown-item>
          </template>
        </template>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>
