<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  exportTracksideApPlan, getTracksideApPlan, getTracksideApTask,
  previewTracksideApPlan, recoverTracksideApTasks, saveTracksideApPlan,
} from '../../api/tracksideApBusiness'
import { isFeatureEnabled } from '../../features'
import type { TracksideApPlanPreview, TracksideApPlanRow, TracksideApTask } from '../../types/tracksideApBusiness'

const storageKey = 'netconsole.trackside-ap-plan.last-task'
const router = useRouter()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const rows = ref<TracksideApPlanRow[]>([])
const selectedRows = ref<TracksideApPlanRow[]>([])
const loading = ref(false)
const error = ref('')
const dirty = ref(false)
const task = ref<TracksideApTask | null>(null)
const importInput = ref<HTMLInputElement | null>(null)
const duplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const preview = ref<TracksideApPlanPreview | null>(null)
const previewVisible = ref(false)
let pollTimer: number | undefined

const canWrite = computed(() => isFeatureEnabled('web.rail_trackside_ap_plan_write') && isFeatureEnabled('web.rail_task_control'))
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: TracksideApTask | null): void {
  task.value = value
  if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey)
}
function renumber(): void { rows.value.forEach((row, index) => { row.sort_order = index }) }
function markDirty(): void { dirty.value = true }

async function loadPlan(force = false): Promise<void> {
  if (dirty.value && !force) {
    try { await ElMessageBox.confirm('刷新会丢弃尚未保存的轨旁 AP 规划修改，是否继续？', '未保存修改', { type: 'warning' }) }
    catch { return }
  }
  loading.value = true; error.value = ''
  try { rows.value = (await getTracksideApPlan()).items; dirty.value = false; selectedRows.value = [] }
  catch (reason) { error.value = failure(reason, '轨旁 AP 规划加载失败') }
  finally { loading.value = false }
}

function addRow(): void {
  rows.value.push({ station_name: '', ap_count: 0, ap_start_address: '', mask_length: 24, ap_gateway: '', ap_management_vlans: '', remark: '', sort_order: rows.value.length })
  markDirty()
}
function deleteRows(): void {
  if (!selectedRows.value.length) return
  const selected = new Set(selectedRows.value)
  rows.value = rows.value.filter((row) => !selected.has(row)); selectedRows.value = []; renumber(); markDirty()
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) {
    if (task.value?.status === 'COMPLETED' && task.value.action === 'trackside_ap_plan_save') void loadPlan(true)
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getTracksideApTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '轨旁 AP 规划任务状态读取失败') }
  }, 1000)
}
async function startTask(factory: () => Promise<TracksideApTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll(); openTaskWindow() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}
async function savePlan(): Promise<void> {
  try { await ElMessageBox.confirm(`确认用当前 ${rows.value.length} 行替换轨旁 AP 规划并持久化？`, '保存确认', { type: 'warning' }) }
  catch { return }
  renumber()
  await startTask(() => saveTracksideApPlan(rows.value), '轨旁 AP 规划保存启动失败')
}
async function chooseImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''
  if (!file) return
  loading.value = true; error.value = ''
  try { preview.value = await previewTracksideApPlan(file, duplicateStrategy.value); previewVisible.value = true }
  catch (reason) { error.value = failure(reason, '轨旁 AP 规划导入预览失败') }
  finally { loading.value = false }
}
function applyPreview(): void {
  if (!preview.value?.can_apply) return
  rows.value = preview.value.result_rows; renumber(); dirty.value = true; previewVisible.value = false
  ElMessage.success('导入预览已应用到编辑区，请确认后保存')
}
async function exportPlan(template: boolean): Promise<void> {
  await startTask(() => exportTracksideApPlan(template), template ? '规划模板导出启动失败' : '轨旁 AP 规划导出启动失败')
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}
async function recoverTasks(): Promise<void> {
  try {
    const recovered = await recoverTracksideApTasks(); const saved = localStorage.getItem(storageKey) || ''
    rememberTask(recovered.find((item) => item.task_id === saved)
      || recovered.find((item) => ['trackside_ap_plan_save', 'trackside_ap_plan_export'].includes(item.action) && !terminalStates.has(item.status))
      || recovered.find((item) => ['trackside_ap_plan_save', 'trackside_ap_plan_export'].includes(item.action)) || null)
    poll()
  } catch (reason) { error.value = failure(reason, '轨旁 AP 规划任务恢复失败') }
}

onMounted(() => { void Promise.all([loadPlan(true), recoverTasks()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="plan-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · TRACKSIDE INFRASTRUCTURE</p><h1>轨旁 AP 规划</h1><p>维护站点 AP 数量、地址池、网关、管理 VLAN 与备注；保存和导出均进入正式任务链。</p></div>
      <div class="actions">
        <el-button :loading="loading" @click="loadPlan()">刷新</el-button>
        <el-button :disabled="!canWrite || taskRunning" @click="addRow">新增</el-button>
        <el-button :disabled="!canWrite || !selectedRows.length || taskRunning" @click="deleteRows">删除</el-button>
        <el-button type="primary" :disabled="!canWrite || !dirty || taskRunning" @click="savePlan">保存</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务状态</el-button></el-alert>
    <div class="content-card">
      <div class="toolbar">
        <el-select v-model="duplicateStrategy" aria-label="重复策略" style="width:150px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select>
        <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport">
        <el-button :disabled="!canWrite || taskRunning" @click="importInput?.click()">导入并预览</el-button>
        <el-button :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(false)">导出规划</el-button>
        <el-button :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(true)">导出模板</el-button>
        <span class="dirty">{{ dirty ? '有未保存修改' : `已加载 ${rows.length} 行` }}</span>
      </div>
      <el-table v-loading="loading" :data="rows" border stripe height="calc(100vh - 340px)" empty-text="暂无轨旁 AP 规划，可新增或导入" @selection-change="(value: TracksideApPlanRow[]) => selectedRows = value">
        <el-table-column type="selection" width="46" fixed="left" />
        <el-table-column label="站点" min-width="150" fixed="left"><template #default="{ row }"><el-input v-model="row.station_name" :disabled="!canWrite" @input="markDirty" /></template></el-table-column>
        <el-table-column label="AP 数" width="110"><template #default="{ row }"><el-input-number v-model="row.ap_count" :disabled="!canWrite" :min="0" controls-position="right" @change="markDirty" /></template></el-table-column>
        <el-table-column label="AP 起始地址" min-width="170"><template #default="{ row }"><el-input v-model="row.ap_start_address" :disabled="!canWrite" @input="markDirty" /></template></el-table-column>
        <el-table-column label="掩码" width="105"><template #default="{ row }"><el-input-number v-model="row.mask_length" :disabled="!canWrite" :min="0" :max="32" controls-position="right" @change="markDirty" /></template></el-table-column>
        <el-table-column label="AP 网关" min-width="160"><template #default="{ row }"><el-input v-model="row.ap_gateway" :disabled="!canWrite" @input="markDirty" /></template></el-table-column>
        <el-table-column label="管理 VLAN" min-width="170"><template #default="{ row }"><el-input v-model="row.ap_management_vlans" :disabled="!canWrite" @input="markDirty" /></template></el-table-column>
        <el-table-column label="备注" min-width="190"><template #default="{ row }"><el-input v-model="row.remark" :disabled="!canWrite" @input="markDirty" /></template></el-table-column>
      </el-table>
    </div>
    <div v-if="task" class="content-card task-card">
      <div class="task-heading"><div><h2>规划任务</h2><p>{{ task.task_id }}</p></div><el-tag>{{ task.status }}</el-tag></div>
      <el-alert v-if="task.error_message" :title="task.error_message" type="error" :closable="false" show-icon />
      <p v-else>{{ task.message || '任务处理中' }}</p>
      <el-alert title="停止、日志、恢复和导出文件保存统一在任务窗口处理" type="info" :closable="false"><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert>
    </div>
    <el-dialog v-model="previewVisible" title="导入预览" width="900px" destroy-on-close>
      <div v-if="preview" class="preview">
        <el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ preview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ preview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ preview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ preview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ preview.file_sha256.slice(0, 12) }}…</el-descriptions-item></el-descriptions>
        <el-table :data="preview.rows" border height="360"><el-table-column prop="row_number" label="行" width="70" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="key" label="站点" min-width="150" /><el-table-column prop="message" label="说明" min-width="260" /></el-table>
        <el-alert v-if="!preview.can_apply" title="预览存在阻断错误，请修正文件或更换重复策略后重新导入" type="error" :closable="false" />
      </div>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" :disabled="!preview?.can_apply" @click="applyPreview">应用到编辑区</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.plan-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.actions,.toolbar,.task-heading{display:flex;align-items:center;gap:12px}.page-heading,.task-heading{justify-content:space-between}.page-heading h1,.task-heading h2{margin:2px 0 6px}.page-heading p,.task-heading p,.task-card p,.dirty{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.actions,.toolbar{flex-wrap:wrap}.content-card{padding:14px 16px;overflow:hidden;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.toolbar{margin-bottom:12px}.dirty{margin-left:auto}.task-card,.preview{display:flex;flex-direction:column;gap:12px}.hidden{display:none}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.dirty{margin-left:0}}
</style>
