<script setup lang="ts">
import {
  Close,
  CopyDocument,
  Files,
  Link,
  Lock,
  Unlock,
} from '@element-plus/icons-vue'

import type { WorkspaceTab } from '../../workspace/types'

defineProps<{
  visible: boolean
  x: number
  y: number
  tab: WorkspaceTab | null
  allowDuplicate: boolean
}>()

const emit = defineEmits<{
  command: [command: 'popout' | 'duplicate' | 'toggle-pin' | 'close' | 'close-others' | 'close-right']
}>()
</script>

<template>
  <div
    v-if="visible && tab"
    class="workspace-tab-context"
    :style="{ left: `${x}px`, top: `${y}px` }"
    role="menu"
    @click.stop
  >
    <button type="button" role="menuitem" @click="emit('command', 'popout')"><el-icon><Link /></el-icon>在新窗口打开</button>
    <button type="button" role="menuitem" :disabled="!allowDuplicate" @click="emit('command', 'duplicate')"><el-icon><CopyDocument /></el-icon>复制标签</button>
    <button type="button" role="menuitem" @click="emit('command', 'toggle-pin')">
      <el-icon><component :is="tab.pinned ? Unlock : Lock" /></el-icon>{{ tab.pinned ? '取消固定' : '固定标签' }}
    </button>
    <span class="workspace-tab-context__divider"></span>
    <button type="button" role="menuitem" :disabled="tab.pinned" @click="emit('command', 'close')"><el-icon><Close /></el-icon>关闭</button>
    <button type="button" role="menuitem" @click="emit('command', 'close-others')"><el-icon><Files /></el-icon>关闭其他标签</button>
    <button type="button" role="menuitem" @click="emit('command', 'close-right')"><el-icon><Close /></el-icon>关闭右侧标签</button>
  </div>
</template>
