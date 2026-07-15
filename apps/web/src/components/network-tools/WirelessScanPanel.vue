<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  createWirelessProject,
  exportWirelessScan,
  getNetworkTask,
  listWirelessAdapters,
  listWirelessProjects,
  listWirelessResults,
  listWirelessRuns,
  startWirelessScan,
} from '../../api/networkTools'
import type { NetworkToolTask, WirelessAdapter, WirelessProject, WirelessScanRun } from '../../types/networkTools'

const adapters = ref<WirelessAdapter[]>([])
const projects = ref<WirelessProject[]>([])
const runs = ref<WirelessScanRun[]>([])
const results = ref<Record<string, unknown>[]>([])
const selectedRun = ref<WirelessScanRun | null>(null)
const task = ref<NetworkToolTask | null>(null)
const loading = ref(false)
const form = reactive({ adapter_guid: '', project_id: '', project_name: '', project_description: '' })
let timer: number | null = null

const rowKeys = computed(() => {
  const keys: string[] = []
  for (const row of results.value) for (const key of Object.keys(row)) if (!keys.includes(key)) keys.push(key)
  return keys
})
const running = computed(() => task.value && ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(task.value.status))

onMounted(() => {
  void refresh()
})

onBeforeUnmount(() => stopPolling())

async function refresh(): Promise<void> {
  loading.value = true
  try {
    ;[adapters.value, projects.value, runs.value] = await Promise.all([listWirelessAdapters(), listWirelessProjects(), listWirelessRuns()])
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描数据加载失败')
  } finally {
    loading.value = false
  }
}

async function createProject(): Promise<void> {
  if (!form.project_name.trim()) return
  try {
    const project = await createWirelessProject(form.project_name.trim(), form.project_description.trim())
    projects.value.unshift(project)
    form.project_id = project.project_id
    form.project_name = ''
    form.project_description = ''
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描项目创建失败')
  }
}

async function startScan(): Promise<void> {
  try {
    const adapter = adapters.value.find((item) => item.guid === form.adapter_guid)
    const response = await startWirelessScan({ adapter_name: adapter?.name || '', adapter_guid: form.adapter_guid, project_id: form.project_id })
    task.value = response.task
    startPolling()
    ElMessage.success(`无线扫描已提交：${response.task.id}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描启动失败')
  }
}

function startPolling(): void {
  if (timer !== null) return
  timer = window.setInterval(async () => {
    if (!task.value) return
    try {
      task.value = await getNetworkTask(task.value.id)
      if (!running.value) {
        stopPolling()
        await refresh()
      }
    } catch {
      stopPolling()
    }
  }, 1000)
}

function stopPolling(): void {
  if (timer !== null) window.clearInterval(timer)
  timer = null
}

async function selectRun(run: WirelessScanRun): Promise<void> {
  selectedRun.value = run
  try {
    results.value = await listWirelessResults(run.scan_id)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描结果加载失败')
  }
}

async function exportRun(format: 'csv' | 'xlsx'): Promise<void> {
  const run = selectedRun.value || runs.value[0]
  if (!run) return
  try {
    const artifact = await exportWirelessScan(run.scan_id, format)
    ElMessage.success(`无线扫描导出完成，SHA-256：${artifact.sha256}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无线扫描导出失败')
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header><div class="header"><div><h2>无线扫描</h2><p>独立于无线勘测，使用 Fake Adapter 可做 Web 闭环验收。</p></div><el-button :loading="loading" @click="refresh">刷新</el-button></div></template>
    <div class="toolbar">
      <el-select v-model="form.adapter_guid" clearable placeholder="选择无线网卡"><el-option v-for="adapter in adapters" :key="adapter.guid || adapter.name" :label="adapter.display_name" :value="adapter.guid" /></el-select>
      <el-select v-model="form.project_id" clearable placeholder="扫描项目"><el-option v-for="project in projects" :key="project.project_id" :label="project.name" :value="project.project_id" /></el-select>
      <el-button type="primary" :loading="!!running" @click="startScan">开始扫描</el-button>
    </div>
    <el-collapse>
      <el-collapse-item title="新建扫描项目" name="project"><div class="project-form"><el-input v-model="form.project_name" placeholder="项目名称" /><el-input v-model="form.project_description" placeholder="说明（可选）" /><el-button @click="createProject">创建</el-button></div></el-collapse-item>
    </el-collapse>
    <el-alert v-if="task" :title="`${task.name}：${task.status} ${task.message}`" :type="running ? 'info' : task.status === 'COMPLETED' ? 'success' : 'warning'" show-icon :closable="false" />
    <el-divider />
    <el-table :data="runs" empty-text="暂无无线扫描记录" stripe @row-click="selectRun">
      <el-table-column prop="scan_id" label="扫描 ID" min-width="230" /><el-table-column prop="adapter_name" label="无线网卡" min-width="160" /><el-table-column prop="network_count" label="结果数" width="90" /><el-table-column prop="status" label="状态" width="100" />
    </el-table>
    <div class="actions"><el-button v-if="runs.length" link type="primary" @click="exportRun('csv')">导出 CSV</el-button><el-button v-if="runs.length" link type="primary" @click="exportRun('xlsx')">导出 XLSX</el-button></div>
    <el-table v-if="results.length" :data="results" stripe max-height="420"><el-table-column v-for="key in rowKeys" :key="key" :prop="key" :label="key" min-width="140" /></el-table>
  </el-card>
</template>

<style scoped>
.header { align-items: center; display: flex; justify-content: space-between; gap: 16px; }
.header h2 { margin: 0 0 4px; }
.header p { color: var(--el-text-color-secondary); margin: 0; }
.toolbar, .project-form, .actions { display: flex; gap: 10px; flex-wrap: wrap; }
.toolbar { margin-bottom: 14px; }
.actions { margin-top: 12px; }
</style>
