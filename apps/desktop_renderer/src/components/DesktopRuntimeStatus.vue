<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { BackendStatus } from '../../../desktop_electron/src/shared/bridge'
import { isFeatureEnabled, isFeatureVisible } from '../features'
import {
  getPlatformAdapter,
  getPlatformRuntimeStatus,
  onPlatformRuntimeStatusChanged,
} from '../platform/runtime'

const runtime = getPlatformAdapter()
const visible = computed(() => runtime.hostType === 'electron' && isFeatureVisible('capability.desktop_native_integration'))
const bridgeEnabled = computed(() => isFeatureEnabled('capability.desktop_native_integration'))
const status = ref<BackendStatus>(getPlatformRuntimeStatus())
const lastFile = ref('')
const lastDirectory = ref('')
const lastSavePath = ref('')
let unsubscribe: (() => void) | undefined

const stateText = computed(() => ({
  starting: 'Backend 重新连接中',
  ready: 'Electron 后端已就绪',
  stopped: '后端已停止',
  failed: '后端异常',
})[status.value.state])

const stateType = computed(() => ({
  starting: 'warning',
  ready: 'success',
  stopped: 'info',
  failed: 'danger',
})[status.value.state] as 'warning' | 'success' | 'info' | 'danger')

onMounted(() => {
  if (!visible.value) return
  status.value = getPlatformRuntimeStatus()
  unsubscribe = onPlatformRuntimeStatusChanged((next) => { status.value = next })
})

onBeforeUnmount(() => unsubscribe?.())

async function selectFile(): Promise<void> {
  const result = await runtime.selectFile({
    filters: [{ name: '日志与数据文件', extensions: ['log', 'txt', 'json', 'zip'] }],
  })
  if (result.cancelled || !result.paths[0]) return
  lastFile.value = result.paths[0]
  ElMessage.success(`已选择文件：${displayName(result.paths[0])}`)
}

async function selectDirectory(): Promise<void> {
  const result = await runtime.selectDirectory()
  if (result.cancelled || !result.path) return
  lastDirectory.value = result.path
  ElMessage.success(`已选择目录：${displayName(result.path)}`)
}

async function chooseSavePath(): Promise<void> {
  const result = await runtime.chooseSavePath({
    suggestedName: 'netconsole-report.xlsx',
    filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }],
  })
  if (result.cancelled || !result.path) return
  lastSavePath.value = result.path
  ElMessage.success(`已选择保存位置：${displayName(result.path)}`)
}

function displayName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) || path
}
</script>

<template>
  <el-popover v-if="visible" placement="bottom-end" :width="340" trigger="click">
    <template #reference>
      <el-tag class="desktop-runtime-tag" :type="stateType" effect="plain">{{ stateText }}</el-tag>
    </template>
    <div class="desktop-runtime-panel">
      <strong>Electron Desktop 基础能力</strong>
      <p>Python Core：{{ status.state === 'ready' ? '已连接' : status.error || stateText }}</p>
      <div class="desktop-runtime-actions">
        <el-button size="small" :disabled="!bridgeEnabled" @click="selectFile">选择文件</el-button>
        <el-button size="small" :disabled="!bridgeEnabled" @click="selectDirectory">选择目录</el-button>
        <el-button size="small" :disabled="!bridgeEnabled" @click="chooseSavePath">另存为</el-button>
      </div>
      <p class="desktop-runtime-hint">这里只验证桌面宿主能力；报告内容仍由 Python ApplicationService 生成。</p>
    </div>
  </el-popover>
</template>
