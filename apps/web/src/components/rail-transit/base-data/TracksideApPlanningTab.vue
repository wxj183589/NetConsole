<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { Delete, Download, Plus, UploadFilled } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  exportTracksideApPlan,
  getTracksideApPlan,
  getTracksideApTask,
  previewTracksideApPlan,
  recoverTracksideApTasks,
  tracksideApPlanDownloadRequest,
} from '../../../api/tracksideApBusiness'
import { downloadBackendResource } from '../../../platform/runtime'
import { useConfirm } from '../../feedback/useConfirm'
import NcDataTable from '../../table/NcDataTable.vue'
import type { NcTableColumn } from '../../table/NcTableColumn'
import { isFeatureEnabled } from '../../../features'
import type {
  TracksideApPlanPreview,
  TracksideApPlanPreviewRow,
  TracksideApPlanRow,
  TracksideApTask,
} from '../../../types/tracksideApBusiness'

const props = defineProps<{ locked: boolean; saving: boolean }>()
const emit = defineEmits<{ change: [rows: TracksideApPlanRow[], dirty: boolean] }>()
const storageKey = 'netconsole.trackside-ap-plan.last-task'
const router = useRouter()
const { confirm } = useConfirm()
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

const planColumns: NcTableColumn<TracksideApPlanRow>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 46, fixed: 'left', hideable: false },
  { key: 'station_name', label: '站点', valueType: 'name', fixed: 'left' },
  { key: 'ap_count', label: 'AP 数', valueType: 'number' },
  { key: 'ap_start_address', label: 'AP 起始地址', valueType: 'ip' },
  { key: 'mask_length', label: '掩码', valueType: 'number' },
  { key: 'ap_gateway', label: 'AP 网关', valueType: 'ip' },
  { key: 'ap_management_vlans', label: '管理 VLAN' },
  { key: 'remark', label: '备注', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const previewColumns: NcTableColumn<TracksideApPlanPreviewRow>[] = [
  { key: 'row_number', label: '行', valueType: 'number' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'key', label: '站点', valueType: 'name' },
  { key: 'message', label: '说明', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
// 基础资料页的编辑会话已经由父页面和后端 write guard 授权，规划表不再维护第二个写入开关。
const canPreviewImport = computed(() => !props.saving)
const canApplyImport = computed(() => !props.locked && !props.saving)
const canWrite = canApplyImport
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: TracksideApTask | null): void {
  task.value = value
  if (value) localStorage.setItem(storageKey, value.task_id)
  else localStorage.removeItem(storageKey)
}
function renumber(): void { rows.value.forEach((row, index) => { row.sort_order = index }) }
function copyRows(): TracksideApPlanRow[] { return rows.value.map((row) => ({ ...row })) }
function publishDirty(): void {
  dirty.value = true
  emit('change', copyRows(), true)
}

async function loadPlan(force = false): Promise<boolean> {
  if (dirty.value && !force) {
    const accepted = await confirm({ type: 'WARNING', title: '未保存修改', message: '刷新会丢弃尚未保存的轨旁 AP 规划修改，是否继续？', confirmText: '放弃修改并刷新' })
    if (!accepted) return false
  }
  loading.value = true
  error.value = ''
  try {
    rows.value = (await getTracksideApPlan()).items
    dirty.value = false
    selectedRows.value = []
    emit('change', copyRows(), false)
    return true
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 规划加载失败')
    return false
  } finally { loading.value = false }
}

function addRow(): void {
  if (!canWrite.value) return
  rows.value.push({ station_name: '', ap_count: 0, ap_start_address: '', mask_length: 24, ap_gateway: '', ap_management_vlans: '', remark: '', sort_order: rows.value.length })
  publishDirty()
}
function deleteRows(): void {
  if (!canWrite.value || !selectedRows.value.length) return
  const selected = new Set(selectedRows.value)
  rows.value = rows.value.filter((row) => !selected.has(row))
  selectedRows.value = []
  renumber()
  publishDirty()
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getTracksideApTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '轨旁 AP 规划任务状态读取失败') }
  }, 1000)
}
async function exportPlan(template: boolean): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    rememberTask(await exportTracksideApPlan(template, !template && dirty.value ? copyRows() : undefined))
    poll()
    openTaskWindow()
  } catch (reason) { error.value = failure(reason, template ? '规划模板导出启动失败' : '轨旁 AP 规划导出启动失败') }
  finally { loading.value = false }
}
async function chooseImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !canPreviewImport.value) return
  loading.value = true
  error.value = ''
  try { preview.value = await previewTracksideApPlan(file, duplicateStrategy.value); previewVisible.value = true }
  catch (reason) { error.value = failure(reason, '轨旁 AP 规划导入预览失败') }
  finally { loading.value = false }
}
function applyPreview(): void {
  if (!preview.value?.can_apply || !canApplyImport.value) return
  rows.value = preview.value.result_rows
  renumber()
  previewVisible.value = false
  publishDirty()
  ElMessage.success('导入预览已应用到编辑区，请使用页面右上角“保存”提交')
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}
async function downloadArtifact(): Promise<void> {
  const current = task.value
  if (!current?.available || !current.artifact_id) return
  const result = await downloadBackendResource(
    tracksideApPlanDownloadRequest(current.artifact_id, current.artifact_name || '轨旁AP规划.xlsx'),
  )
  if (result.status === 'saved') ElMessage.success(`已保存 ${current.artifact_name || '轨旁 AP 规划文件'}`)
  else if (result.status === 'started') ElMessage.success('浏览器已开始下载轨旁 AP 规划文件')
  else if (result.status === 'failed') ElMessage.error(result.error || '轨旁 AP 规划文件下载失败')
}
async function recoverTasks(): Promise<void> {
  try {
    const recovered = await recoverTracksideApTasks()
    const saved = localStorage.getItem(storageKey) || ''
    rememberTask(recovered.find((item) => item.task_id === saved)
      || recovered.find((item) => item.action === 'trackside_ap_plan_export' && !terminalStates.has(item.status))
      || recovered.find((item) => item.action === 'trackside_ap_plan_export') || null)
    poll()
  } catch (reason) { error.value = failure(reason, '轨旁 AP 规划任务恢复失败') }
}

defineExpose({ reload: loadPlan })
onMounted(() => { void Promise.all([loadPlan(true), recoverTasks()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="planning-tab">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务状态</el-button></el-alert>
    <div class="toolbar">
      <el-select v-model="duplicateStrategy" aria-label="重复策略" style="width:150px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select>
      <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport">
      <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(true)">下载模板</el-button>
      <el-button :icon="UploadFilled" :disabled="!canPreviewImport || taskRunning" @click="importInput?.click()">导入并预览</el-button>
      <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(false)">导出当前</el-button>
      <el-button :icon="Plus" :disabled="!canWrite || taskRunning" @click="addRow">新增</el-button>
      <el-button :icon="Delete" :disabled="!canWrite || !selectedRows.length || taskRunning" @click="deleteRows">删除</el-button>
      <span class="dirty">{{ dirty ? '有未保存修改' : `已加载 ${rows.length} 行` }}</span>
    </div>
    <NcDataTable v-loading="loading" table-id="rail-base-trackside-ap-planning" route-key="/rail-transit/base-data" :data="rows" :columns="planColumns" border height="calc(100vh - 390px)" empty-text="暂无轨旁 AP 规划，可解锁后新增或导入" @selection-change="(value: TracksideApPlanRow[]) => selectedRows = value">
      <template #cell-station_name="{ row }"><el-input v-if="canWrite" v-model="row.station_name" @input="publishDirty" /><span v-else>{{ row.station_name || '--' }}</span></template>
      <template #cell-ap_count="{ row }"><el-input-number v-if="canWrite" v-model="row.ap_count" :min="0" controls-position="right" @change="publishDirty" /><span v-else>{{ row.ap_count }}</span></template>
      <template #cell-ap_start_address="{ row }"><el-input v-if="canWrite" v-model="row.ap_start_address" @input="publishDirty" /><span v-else>{{ row.ap_start_address || '--' }}</span></template>
      <template #cell-mask_length="{ row }"><el-input-number v-if="canWrite" v-model="row.mask_length" :min="0" :max="32" controls-position="right" @change="publishDirty" /><span v-else>{{ row.mask_length ?? '--' }}</span></template>
      <template #cell-ap_gateway="{ row }"><el-input v-if="canWrite" v-model="row.ap_gateway" @input="publishDirty" /><span v-else>{{ row.ap_gateway || '--' }}</span></template>
      <template #cell-ap_management_vlans="{ row }"><el-input v-if="canWrite" v-model="row.ap_management_vlans" @input="publishDirty" /><span v-else>{{ row.ap_management_vlans || '--' }}</span></template>
      <template #cell-remark="{ row }"><el-input v-if="canWrite" v-model="row.remark" @input="publishDirty" /><span v-else>{{ row.remark || '--' }}</span></template>
    </NcDataTable>
    <el-alert v-if="task" :title="`${task.status} · ${task.message || task.task_id}`" :type="task.error_message ? 'error' : 'info'" :closable="false"><el-button v-if="task.available && task.artifact_id" link type="primary" @click="downloadArtifact">下载文件</el-button><el-button link @click="openTaskWindow">打开任务窗口</el-button></el-alert>
    <el-dialog v-model="previewVisible" title="导入预览" width="900px" destroy-on-close>
      <div v-if="preview" class="preview">
        <el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ preview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ preview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ preview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ preview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ preview.file_sha256.slice(0, 12) }}…</el-descriptions-item></el-descriptions>
        <NcDataTable table-id="rail-base-trackside-ap-plan-import-preview" route-key="/rail-transit/base-data" :data="preview.rows" :columns="previewColumns" border height="360" :show-column-settings="false" />
        <el-alert v-if="!preview.can_apply" title="预览存在阻断错误，请修正文件或更换重复策略后重新导入" type="error" :closable="false" />
      </div>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" :disabled="!preview?.can_apply || !canApplyImport" @click="applyPreview">应用到编辑区</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.planning-tab,.preview{display:flex;flex-direction:column;gap:12px;min-width:0}.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.dirty{margin-left:auto;color:var(--nc-text-secondary)}.hidden{display:none}@media(max-width:900px){.dirty{margin-left:0}}
</style>
