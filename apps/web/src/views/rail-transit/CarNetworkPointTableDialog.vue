<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  cancelCarNetworkPointTableTask, carNetworkPointTableDownloadRequest, exportCarNetworkPointTable,
  generateCarNetworkPointTable, getCarNetworkPointTable, getCarNetworkPointTableTask,
  previewCarNetworkPointTable, recoverCarNetworkPointTableTasks, saveCarNetworkPointTable,
  transformCarNetworkPointTable,
} from '../../api/railTransitWeb'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource } from '../../platform/runtime'
import type { CarNetworkPointPreview, CarNetworkPointRow, RailTransitTask } from '../../types/railTransitWeb'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const storageKey = 'netconsole.car-network-point-table.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const roleOptions = [{ label: '车内 IP', value: 'vehicle_ip' }, { label: '落地 IP', value: 'uplink_ip' }, { label: '全部', value: 'all' }, { label: '忽略', value: 'ignore' }]
const sshOptions = [{ label: '主用地址', value: 'primary_address' }, { label: '备用地址', value: 'backup_address' }, { label: '不生成', value: 'empty' }]
const emptyRow = (): CarNetworkPointRow => ({ train_id: '', train_no: '', display_name: '', tc: '', end: '', node_name: '', node_type: '', device_id: '', device_name: '', device_group: '', station: '', primary_address: '', backup_address: '', ip_vehicle: '', ip_uplink: '', ssh_host: '', vrrp_ip: '', address_mapping_mode: 'global', primary_address_role: '', backup_address_role: '', remark: '' })

const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const rows = ref<CarNetworkPointRow[]>([])
const globalConfig = ref<Record<string, unknown>>({})
const locked = ref(false)
const selectedRows = ref<CarNetworkPointRow[]>([])
const trainFilter = ref('')
const nodeFilter = ref('')
const loading = ref(false)
const dirty = ref(false)
const error = ref('')
const task = ref<RailTransitTask | null>(null)
const importInput = ref<HTMLInputElement | null>(null)
const duplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const exportFormat = ref<'xlsx' | 'csv'>('xlsx')
const preview = ref<CarNetworkPointPreview | null>(null)
const previewVisible = ref(false)
let pollTimer: number | undefined

const canWrite = computed(() => isFeatureEnabled('web.rail_car_network_point_table_write') && isFeatureEnabled('web.rail_task_control'))
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const trainOptions = computed(() => [...new Set(rows.value.map((row) => row.train_no || row.train_id).filter(Boolean))].sort())
const nodeOptions = computed(() => [...new Set(rows.value.map((row) => row.node_type).filter(Boolean))].sort())
const filteredRows = computed(() => rows.value.filter((row) => (!trainFilter.value || (row.train_no || row.train_id) === trainFilter.value) && (!nodeFilter.value || row.node_type === nodeFilter.value)))
const addressMapping = computed<Record<string, Record<string, unknown>>>(() => {
  const value = globalConfig.value.address_mapping
  if (!value || typeof value !== 'object' || Array.isArray(value)) globalConfig.value.address_mapping = {}
  return globalConfig.value.address_mapping as Record<string, Record<string, unknown>>
})
const srvGeneration = computed<Record<string, unknown>>(() => {
  const value = globalConfig.value.srv_generation
  if (!value || typeof value !== 'object' || Array.isArray(value)) globalConfig.value.srv_generation = {}
  return globalConfig.value.srv_generation as Record<string, unknown>
})

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function markDirty(): void { dirty.value = true }
function ensureMapping(): void {
  for (const type of ['MR', '3SW', 'SRV']) if (!addressMapping.value[type]) addressMapping.value[type] = {}
}

async function loadPointTable(force = false): Promise<void> {
  if (dirty.value && !force) {
    try { await ElMessageBox.confirm('重新加载会丢弃未保存的点表修改，是否继续？', '未保存修改', { type: 'warning' }) }
    catch { return }
  }
  loading.value = true; error.value = ''
  try {
    const value = await getCarNetworkPointTable(); rows.value = value.rows; globalConfig.value = value.global_config; locked.value = value.locked
    ensureMapping(); dirty.value = false; selectedRows.value = []
  } catch (reason) { error.value = failure(reason, '车内通信点表加载失败') }
  finally { loading.value = false }
}
function addRow(): void { rows.value.push(emptyRow()); dirty.value = true }
function deleteRows(): void {
  if (!selectedRows.value.length) return
  const selected = new Set(selectedRows.value); rows.value = rows.value.filter((row) => !selected.has(row)); selectedRows.value = []; dirty.value = true
}
async function transform(operation: 'apply_mapping' | 'apply_global' | 'apply_global_override' | 'restore_defaults'): Promise<void> {
  loading.value = true; error.value = ''
  try {
    const value = await transformCarNetworkPointTable(operation, rows.value, globalConfig.value)
    rows.value = value.rows; globalConfig.value = value.global_config; locked.value = value.locked; ensureMapping(); dirty.value = true
  } catch (reason) { error.value = failure(reason, '点表规则应用失败') }
  finally { loading.value = false }
}
function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) {
    if (task.value?.status === 'COMPLETED') {
      if (task.value.action === 'car_network_generate_point_table' && Array.isArray(task.value.result_summary.nodes)) {
        rows.value = task.value.result_summary.nodes as unknown as CarNetworkPointRow[]; dirty.value = true
      } else if (task.value.action === 'car_network_save_point_table') void loadPointTable(true)
    }
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getCarNetworkPointTableTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '点表任务状态读取失败') }
  }, 1000)
}
async function startTask(factory: () => Promise<RailTransitTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}
async function save(confirmText = `确认保存当前 ${rows.value.length} 行点表与全局规则？`): Promise<void> {
  try { await ElMessageBox.confirm(confirmText, '点表写入确认', { type: 'warning' }) }
  catch { return }
  globalConfig.value.point_table_locked = locked.value
  await startTask(() => saveCarNetworkPointTable(rows.value, globalConfig.value), '车内通信点表保存启动失败')
}
async function toggleLock(): Promise<void> {
  const next = !locked.value
  try { await ElMessageBox.confirm(next ? '锁定后须先解锁才能修改点表，确认锁定并保存？' : '确认解锁点表并持久化？', next ? '锁定点表' : '解锁点表', { type: 'warning' }) }
  catch { return }
  locked.value = next; globalConfig.value.point_table_locked = next
  await startTask(() => saveCarNetworkPointTable(rows.value, globalConfig.value), '点表锁定状态保存失败')
}
async function generate(): Promise<void> {
  try { await ElMessageBox.confirm('确认从现有设备管理数据重新生成点表预览？当前编辑区不会立即持久化。', '从设备生成', { type: 'warning' }) }
  catch { return }
  await startTask(() => generateCarNetworkPointTable(rows.value, globalConfig.value), '从设备管理生成点表失败')
}
async function chooseImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''
  if (!file) return
  loading.value = true; error.value = ''
  try { preview.value = await previewCarNetworkPointTable(file, duplicateStrategy.value); previewVisible.value = true }
  catch (reason) { error.value = failure(reason, '车内通信点表导入预览失败') }
  finally { loading.value = false }
}
function applyPreview(): void {
  if (!preview.value?.can_apply) return
  rows.value = preview.value.result_rows; dirty.value = true; previewVisible.value = false
  ElMessage.success('导入结果已应用到编辑区，请确认后保存')
}
async function exportTable(): Promise<void> { await startTask(() => exportCarNetworkPointTable(exportFormat.value), '车内通信点表导出启动失败') }
async function downloadTaskArtifact(): Promise<void> {
  if (!task.value?.available || !task.value.artifact_id) return
  try {
    const result = await downloadBackendResource(carNetworkPointTableDownloadRequest(task.value.artifact_id, exportFormat.value))
    if (result.status === 'failed') throw new Error(result.error || '车内通信点表下载失败')
    if (result.status === 'saved') ElMessage.success('车内通信点表已保存')
  } catch (reason) { error.value = failure(reason, '车内通信点表下载失败') }
}
async function cancelTask(): Promise<void> {
  if (!task.value || terminalStates.has(task.value.status)) return
  await startTask(() => cancelCarNetworkPointTableTask(task.value!.task_id), '点表任务取消失败')
}
async function recoverTasks(): Promise<void> {
  try {
    const recovered = await recoverCarNetworkPointTableTasks(); const saved = localStorage.getItem(storageKey) || ''
    rememberTask(recovered.find((item) => item.task_id === saved) || recovered.find((item) => !terminalStates.has(item.status)) || recovered[0] || null); poll()
  } catch (reason) { error.value = failure(reason, '点表任务恢复失败') }
}
async function closeDialog(): Promise<void> {
  if (dirty.value) {
    try { await ElMessageBox.confirm('关闭会丢弃未保存的点表修改，是否继续？', '未保存修改', { type: 'warning' }) }
    catch { return }
  }
  visible.value = false
}

watch(() => props.modelValue, (value) => { if (value) void Promise.all([loadPointTable(true), recoverTasks()]); else stopPolling() })
onBeforeUnmount(stopPolling)
</script>

<template>
  <el-dialog v-model="visible" title="车内通信点表" width="96vw" top="2vh" :close-on-click-modal="false" :before-close="closeDialog" destroy-on-close>
    <div class="dialog-body">
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务状态</el-button></el-alert>
      <div class="filters">
        <el-select v-model="trainFilter" clearable placeholder="全部列车" style="width:150px"><el-option v-for="value in trainOptions" :key="value" :label="value" :value="value" /></el-select>
        <el-select v-model="nodeFilter" clearable placeholder="全部节点类型" style="width:160px"><el-option v-for="value in nodeOptions" :key="value" :label="value" :value="value" /></el-select>
        <el-tag :type="locked ? 'warning' : 'success'">{{ locked ? '点表已锁定' : '点表可编辑' }}</el-tag>
        <el-button :disabled="!canWrite || taskRunning" @click="toggleLock">{{ locked ? '解锁并保存' : '锁定并保存' }}</el-button>
        <span>{{ dirty ? '有未保存修改' : `共 ${rows.length} 行` }}</span>
      </div>
      <el-collapse model-value="rules"><el-collapse-item name="rules" title="全局地址映射与 SRV 生成规则">
        <div class="rule-grid">
          <template v-for="type in ['MR', '3SW', 'SRV']" :key="type">
            <strong>{{ type }}</strong>
            <el-select v-model="addressMapping[type].primary_address_role" :disabled="locked" @change="markDirty"><el-option v-for="item in roleOptions" :key="item.value" :label="`主用：${item.label}`" :value="item.value" /></el-select>
            <el-select v-model="addressMapping[type].backup_address_role" :disabled="locked" @change="markDirty"><el-option v-for="item in roleOptions" :key="item.value" :label="`备用：${item.label}`" :value="item.value" /></el-select>
            <el-select v-model="addressMapping[type].ssh_source" :disabled="locked" @change="markDirty"><el-option v-for="item in sshOptions" :key="item.value" :label="`SSH：${item.label}`" :value="item.value" /></el-select>
          </template>
          <strong>SRV</strong><el-checkbox v-model="srvGeneration.enabled" :disabled="locked" @change="markDirty">自动生成</el-checkbox>
          <el-input-number v-model="srvGeneration.tc1_host" :disabled="locked" :min="1" :max="254" @change="markDirty" /><el-input-number v-model="srvGeneration.tc2_host" :disabled="locked" :min="1" :max="254" @change="markDirty" /><el-input-number v-model="srvGeneration.vrrp_host" :disabled="locked" :min="1" :max="254" @change="markDirty" />
        </div>
        <div class="actions"><el-button :disabled="locked || taskRunning" @click="save('确认仅保存当前全局规则与点表内容？')">保存全局规则</el-button><el-button :disabled="locked" @click="transform('apply_global')">应用全局规则</el-button><el-button :disabled="locked" @click="transform('apply_global_override')">应用并覆盖自定义行</el-button><el-button :disabled="locked" @click="transform('restore_defaults')">恢复默认映射</el-button></div>
      </el-collapse-item></el-collapse>
      <div class="toolbar">
        <el-button :disabled="locked || !canWrite || taskRunning" @click="addRow">新增行</el-button><el-button :disabled="locked || !canWrite || !selectedRows.length || taskRunning" @click="deleteRows">删除行</el-button>
        <el-button :disabled="locked || !canWrite || taskRunning" @click="transform('apply_mapping')">地址映射并应用</el-button><el-button :disabled="locked || !canWrite || taskRunning" @click="generate">从设备管理生成</el-button>
        <el-select v-model="duplicateStrategy" style="width:145px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select>
        <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport"><el-button :disabled="locked || !canWrite || taskRunning" @click="importInput?.click()">导入并预览</el-button>
        <el-select v-model="exportFormat" style="width:95px"><el-option label="XLSX" value="xlsx" /><el-option label="CSV" value="csv" /></el-select><el-button :disabled="!isFeatureEnabled('web.rail_car_network_point_table_export') || taskRunning" @click="exportTable">导出</el-button>
        <el-button type="primary" :disabled="locked || !canWrite || !dirty || taskRunning" @click="save()">保存点表</el-button><el-button @click="closeDialog">取消</el-button>
      </div>
      <el-table v-loading="loading" :data="filteredRows" border stripe height="42vh" empty-text="暂无点表数据，可从设备管理生成、新增或导入" @selection-change="(value: CarNetworkPointRow[]) => selectedRows = value">
        <el-table-column type="selection" width="46" fixed="left" /><el-table-column label="列车ID" width="120" fixed="left"><template #default="{ row }"><el-input v-model="row.train_id" :disabled="locked" @input="markDirty" /></template></el-table-column><el-table-column label="车号" width="90"><template #default="{ row }"><el-input v-model="row.train_no" :disabled="locked" @input="markDirty" /></template></el-table-column><el-table-column label="显示名" width="130"><template #default="{ row }"><el-input v-model="row.display_name" :disabled="locked" @input="markDirty" /></template></el-table-column>
        <el-table-column v-for="field in [{k:'tc',l:'TC'},{k:'end',l:'端位'},{k:'node_name',l:'节点名称'},{k:'node_type',l:'节点类型'},{k:'device_id',l:'设备ID'},{k:'device_name',l:'设备名称'},{k:'device_group',l:'设备组'},{k:'station',l:'站点'},{k:'primary_address',l:'主用地址'},{k:'backup_address',l:'备用地址'},{k:'ip_vehicle',l:'车内IP'},{k:'ip_uplink',l:'落地IP'},{k:'ssh_host',l:'SSH地址'},{k:'vrrp_ip',l:'VRRP IP'},{k:'primary_address_role',l:'主用角色'},{k:'backup_address_role',l:'备用角色'},{k:'remark',l:'备注'}]" :key="field.k" :label="field.l" width="140"><template #default="{ row }"><el-input v-model="row[field.k]" :disabled="locked" @input="markDirty" /></template></el-table-column>
        <el-table-column label="映射模式" width="120"><template #default="{ row }"><el-select v-model="row.address_mapping_mode" :disabled="locked" @change="markDirty"><el-option label="全局" value="global" /><el-option label="自定义" value="custom" /></el-select></template></el-table-column>
      </el-table>
      <div v-if="task" class="task-bar"><span>任务 {{ task.task_id }}</span><el-tag>{{ task.status }}</el-tag><span>{{ task.error_message || task.message }}</span><el-button :disabled="!taskRunning" @click="cancelTask">取消任务</el-button><el-button type="primary" :disabled="!task.available" @click="downloadTaskArtifact">受控下载</el-button></div>
    </div>
    <el-dialog v-model="previewVisible" title="点表导入预览" width="900px" append-to-body>
      <div v-if="preview" class="preview"><el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ preview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ preview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ preview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ preview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ preview.file_sha256.slice(0, 12) }}…</el-descriptions-item></el-descriptions><el-table :data="preview.rows" border height="350"><el-table-column prop="row_number" label="行" width="70" /><el-table-column prop="status" label="状态" width="100" /><el-table-column prop="key" label="节点" min-width="180" /><el-table-column prop="message" label="说明" min-width="260" /></el-table><el-alert v-if="!preview.can_apply" title="预览存在阻断错误，请修正文件或重复策略后重新导入" type="error" :closable="false" /></div>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" :disabled="!preview?.can_apply" @click="applyPreview">应用到编辑区</el-button></template>
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.dialog-body,.preview{display:flex;flex-direction:column;gap:12px;min-width:0}.filters,.actions,.toolbar,.task-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.filters span{color:var(--el-text-color-secondary)}.rule-grid{display:grid;grid-template-columns:70px repeat(4,minmax(150px,1fr));gap:8px;align-items:center;margin-bottom:10px}.task-bar{padding:10px 12px;border:1px solid var(--el-border-color-lighter);border-radius:8px}.hidden{display:none}@media(max-width:1000px){.rule-grid{grid-template-columns:70px minmax(150px,1fr)}}
</style>
