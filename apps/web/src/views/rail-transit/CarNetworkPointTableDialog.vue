<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'

import {
  exportCarNetworkPointTable,
  generateCarNetworkPointTable, getCarNetworkPointTable, getCarNetworkPointTableTask,
  previewCarNetworkPointTable, recoverCarNetworkPointTableTasks, saveCarNetworkPointTable,
  transformCarNetworkPointTable,
} from '../../api/railTransitWeb'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { isFeatureEnabled } from '../../features'
import type { TrainCommunicationRow } from '../../types/trainCommunication'
import type { CarNetworkPointPreview, CarNetworkPointRow, RailTransitTask } from '../../types/railTransitWeb'

type DialogTrain = Pick<TrainCommunicationRow, 'train_id' | 'train_no' | 'train_name' | 'canonical_train_id' | 'display_name' | 'ct_mr_id' | 'ct_mr_name' | 'tc_mr_id' | 'tc_mr_name'>
const props = defineProps<{ modelValue: boolean; train?: DialogTrain | null }>()
const router = useRouter()
const { confirm } = useConfirm()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [{ trainId: string; revision: string; rowCount: number }]
}>()

const storageKey = 'netconsole.car-network-point-table.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const nodeOrder = ['TC1-MR', 'TC1-SW', 'TC1-SRV', 'TC2-MR', 'TC2-SW', 'TC2-SRV']
const roleOptions = [{ label: '车内 IP', value: 'vehicle_ip' }, { label: '落地 IP', value: 'uplink_ip' }, { label: '全部', value: 'all' }, { label: '忽略', value: 'ignore' }]
const sshOptions = [{ label: '主用地址', value: 'primary_address' }, { label: '备用地址', value: 'backup_address' }, { label: '不生成', value: 'empty' }]
const emptyRow = (): CarNetworkPointRow => ({ train_id: currentTrainKey.value || '', train_no: props.train?.train_no || '', display_name: props.train?.display_name || props.train?.train_name || '', tc: '', end: '', node_name: '', node_type: '', device_id: '', device_name: '', device_group: '', station: '', primary_address: '', backup_address: '', ip_vehicle: '', ip_uplink: '', ssh_host: '', vrrp_ip: '', address_mapping_mode: 'global', primary_address_role: '', backup_address_role: '', remark: '' })
const pointTableFields: readonly {
  key: keyof CarNetworkPointRow & string
  label: string
  longText?: boolean
}[] = [
  { key: 'tc', label: 'TC端' },
  { key: 'end', label: '端别' },
  { key: 'node_name', label: '节点名称' },
  { key: 'node_type', label: '节点类型' },
  { key: 'device_id', label: '设备ID' },
  { key: 'device_name', label: '设备名称' },
  { key: 'device_group', label: '设备组' },
  { key: 'station', label: '归属站点/位置' },
  { key: 'primary_address', label: '主用地址' },
  { key: 'backup_address', label: '备用地址' },
  { key: 'ip_vehicle', label: '车内IP' },
  { key: 'ip_uplink', label: '落地IP' },
  { key: 'ssh_host', label: 'SSH地址' },
  { key: 'vrrp_ip', label: 'VRRP地址' },
  { key: 'primary_address_role', label: '主用角色' },
  { key: 'backup_address_role', label: '备用角色' },
  { key: 'remark', label: '备注', longText: true },
]

function editablePointColumn(field: typeof pointTableFields[number]): NcTableColumn<CarNetworkPointRow> {
  return {
    key: field.key,
    label: field.label,
    prop: field.key,
    ...(field.longText ? { valueType: 'description', align: 'left', alignmentReason: 'long-text' } : {}),
  }
}

const pointTableColumns: NcTableColumn<CarNetworkPointRow>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 46, fixed: 'left', hideable: false },
  { key: 'train_id', label: '列车ID', valueType: 'name', fixed: 'left' },
  { key: 'train_no', label: '车号', valueType: 'name' },
  { key: 'display_name', label: '显示名称', valueType: 'name' },
  ...pointTableFields.map(editablePointColumn),
  { key: 'address_mapping_mode', label: '映射模式', valueType: 'status' },
]
const previewColumns: NcTableColumn<CarNetworkPointPreview['rows'][number]>[] = [
  { key: 'row_number', label: '行', valueType: 'number' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'key', label: '节点', valueType: 'name' },
  { key: 'message', label: '说明', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]

const visible = computed({ get: () => props.modelValue, set: (value) => emit('update:modelValue', value) })
const rows = ref<CarNetworkPointRow[]>([])
const globalConfig = ref<Record<string, unknown>>({})
const revision = ref('')
const locked = ref(false)
const selectedRows = ref<CarNetworkPointRow[]>([])
const trainFilter = ref('')
const nodeFilter = ref('')
const loading = ref(false)
const dirty = ref(false)
const error = ref('')
const info = ref('')
const task = ref<RailTransitTask | null>(null)
const importInput = ref<HTMLInputElement | null>(null)
const duplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const exportFormat = ref<'xlsx' | 'csv'>('xlsx')
const preview = ref<CarNetworkPointPreview | null>(null)
const previewVisible = ref(false)
const saveStartRevision = ref('')
let pollTimer: number | undefined

const currentTrainKey = computed(() => props.train?.canonical_train_id || normalizeTrainIdentity(props.train?.train_id, props.train?.train_no, props.train?.train_name))
const canWrite = computed(() => isFeatureEnabled('web.rail_car_network_point_table_write') && isFeatureEnabled('web.rail_task_control'))
const canWriteReason = computed(() => canWrite.value ? '' : '点表写入功能未启用')
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const trainOptions = computed(() => {
  const values = rows.value.map((row) => ({ key: normalizeTrainIdentity(row.train_id, row.train_no, row.display_name), label: row.display_name || row.train_no || row.train_id })).filter((item) => item.key)
  return [...new Map(values.map((item) => [item.key, item])).values()].sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})
const nodeOptions = computed(() => [...new Set(rows.value.map((row) => row.node_type).filter(Boolean))].sort())
const currentTrainRows = computed(() => rows.value.filter((row) => currentTrainKey.value && rowMatchesTrain(row, currentTrainKey.value)))
const missingNodes = computed(() => nodeOrder.filter((name) => !currentTrainRows.value.some((row) => normalizeNodeName(row.node_name) === name)))
const filteredRows = computed(() => rows.value.filter((row) => (!trainFilter.value || rowMatchesTrain(row, trainFilter.value)) && (!nodeFilter.value || row.node_type === nodeFilter.value)))
const showCurrentTrainEmpty = computed(() => Boolean(props.train && !currentTrainRows.value.length && !loading.value))
const showCurrentTrainMissing = computed(() => Boolean(props.train && currentTrainRows.value.length && missingNodes.value.length && !loading.value))
const addressMapping = computed<Record<string, Record<string, unknown>>>(() => {
  const value = globalConfig.value.address_mapping
  if (!value || typeof value !== 'object' || Array.isArray(value)) globalConfig.value.address_mapping = {}
  const mapping = globalConfig.value.address_mapping as Record<string, Record<string, unknown>>
  for (const type of ['MR', '3SW', 'SRV']) {
    const current = mapping[type]
    if (!current || typeof current !== 'object' || Array.isArray(current)) {
      mapping[type] = {}
    }
  }
  return mapping
})
const srvGeneration = computed<Record<string, unknown>>(() => {
  const value = globalConfig.value.srv_generation
  if (!value || typeof value !== 'object' || Array.isArray(value)) globalConfig.value.srv_generation = {}
  return globalConfig.value.srv_generation as Record<string, unknown>
})

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: RailTransitTask | null): void { task.value = value; if (value) localStorage.setItem(storageKey, value.task_id); else localStorage.removeItem(storageKey) }
function markDirty(): void { dirty.value = true; info.value = '' }
function ensureMapping(): void {
  for (const type of ['MR', '3SW', 'SRV']) if (!addressMapping.value[type]) addressMapping.value[type] = {}
}
function normalizeTrainIdentity(...values: unknown[]): string {
  const text = values.map((value) => String(value || '').trim()).find(Boolean) || ''
  const lc = text.match(/LC0*(\d{1,3})/i)
  const train = text.match(/列车0*(\d{1,3})/)
  const car = text.match(/0*(\d{1,3})车/)
  const trainKey = text.match(/^train[:_-]?0*(\d{1,3})$/i)
  const digits = text.match(/^\d{1,3}$/)
  const value = lc?.[1] || train?.[1] || car?.[1] || trainKey?.[1] || digits?.[0] || ''
  return value ? `train:${value.padStart(2, '0')}` : text.toLowerCase()
}
function normalizeNodeName(value: string): string { return value === 'TC1-AP' ? 'TC1-MR' : value === 'TC2-AP' ? 'TC2-MR' : value }
function rowMatchesTrain(row: CarNetworkPointRow, key: string): boolean { return normalizeTrainIdentity(row.train_id, row.train_no, row.display_name) === key }
function generatedText(value: unknown, fallback = ''): string { return typeof value === 'string' ? value : fallback }
function normalizeGeneratedRow(value: unknown): CarNetworkPointRow | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const trainId = generatedText(row.train_id)
  const nodeName = generatedText(row.node_name)
  if (!trainId || !nodeName) return null
  return {
    train_id: trainId, train_no: generatedText(row.train_no), display_name: generatedText(row.display_name),
    tc: generatedText(row.tc), end: generatedText(row.end), node_name: nodeName, node_type: generatedText(row.node_type),
    device_id: generatedText(row.device_id), device_name: generatedText(row.device_name), device_group: generatedText(row.device_group), station: generatedText(row.station),
    primary_address: generatedText(row.primary_address), backup_address: generatedText(row.backup_address), ip_vehicle: generatedText(row.ip_vehicle), ip_uplink: generatedText(row.ip_uplink),
    ssh_host: generatedText(row.ssh_host), vrrp_ip: generatedText(row.vrrp_ip), address_mapping_mode: generatedText(row.address_mapping_mode, 'global'),
    primary_address_role: generatedText(row.primary_address_role), backup_address_role: generatedText(row.backup_address_role), remark: generatedText(row.remark),
  }
}
function applyGeneratedRows(previewRows: CarNetworkPointRow[]): boolean {
  if (!props.train) { rows.value = previewRows; return true }
  const currentRows = previewRows.filter((row) => rowMatchesTrain(row, currentTrainKey.value))
  if (!currentRows.length) return false
  const otherRows = rows.value.filter((row) => !rowMatchesTrain(row, currentTrainKey.value))
  for (const generated of previewRows.filter((row) => !rowMatchesTrain(row, currentTrainKey.value))) {
    const index = otherRows.findIndex((row) => rowMatchesTrain(row, normalizeTrainIdentity(generated.train_id, generated.train_no, generated.display_name)) && normalizeNodeName(row.node_name) === normalizeNodeName(generated.node_name))
    if (index >= 0) otherRows[index] = generated
    else otherRows.push(generated)
  }
  rows.value = [...otherRows, ...currentRows]
  return true
}
function targetTrainPayload(): Record<string, unknown> {
  if (!props.train) return {}
  return {
    canonical_train_id: props.train.canonical_train_id || currentTrainKey.value,
    train_id: props.train.train_id,
    train_no: props.train.train_no,
    train_name: props.train.train_name,
    display_name: props.train.display_name || props.train.train_name,
    ct_mr_id: props.train.ct_mr_id,
    ct_mr_name: props.train.ct_mr_name,
    tc_mr_id: props.train.tc_mr_id,
    tc_mr_name: props.train.tc_mr_name,
  }
}

async function loadPointTable(force = false): Promise<void> {
  if (dirty.value && !force) {
    if (!await confirm({ type: 'WARNING', title: '未保存修改', message: '重新加载会丢弃未保存的点表修改，是否继续？', confirmText: '放弃修改并重新加载' })) return
  }
  loading.value = true; error.value = ''
  try {
    const value = await getCarNetworkPointTable()
    rows.value = value.rows
    globalConfig.value = value.global_config
    revision.value = value.revision
    locked.value = value.locked
    ensureMapping(); dirty.value = false; selectedRows.value = []
    if (props.train) trainFilter.value = currentTrainKey.value
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
async function handleTerminalTask(done: RailTransitTask): Promise<void> {
  if (done.status !== 'COMPLETED') return
  if (done.action === 'car_network_generate_point_table') {
    const rawNodes = done.result_summary.nodes
    if (!Array.isArray(rawNodes)) {
      error.value = String(done.result_summary.nodes_error || '点表生成任务已完成，但未返回生成结果，请查看任务日志或重新生成。')
      return
    }
    if (!rawNodes.length) {
      error.value = '未生成任何点表节点，请检查当前列车身份及设备映射。'
      return
    }
    const previewRows = rawNodes.map(normalizeGeneratedRow)
    if (previewRows.some((row) => row === null)) {
      error.value = '点表生成任务已完成，但返回的节点数据无效，请查看任务日志或重新生成。'
      return
    }
    const normalizedRows = previewRows as CarNetworkPointRow[]
    const expectedCount = Number(done.result_summary.count)
    if (Number.isFinite(expectedCount) && expectedCount !== normalizedRows.length) {
      console.warn('点表生成任务节点计数不一致', { expectedCount, receivedCount: normalizedRows.length })
    }
    const generatedCount = props.train
      ? normalizedRows.filter((row) => rowMatchesTrain(row, currentTrainKey.value)).length
      : normalizedRows.length
    if (!applyGeneratedRows(normalizedRows)) {
      error.value = '未生成当前列车的点表节点，请检查当前列车身份及设备映射。'
      return
    }
    if (props.train) trainFilter.value = currentTrainKey.value
    dirty.value = true
    info.value = `已生成 ${generatedCount} 行点表预览，尚未保存`
  } else if (done.action === 'car_network_save_point_table') {
    await loadPointTable(true)
    const savedRevision = String(done.result_summary.revision || revision.value || '')
    info.value = '当前列车点表保存成功'
    ElMessage.success('当前列车点表保存成功')
    emit('saved', { trainId: currentTrainKey.value || props.train?.train_id || '', revision: savedRevision, rowCount: rows.value.length })
    saveStartRevision.value = ''
  }
}
function poll(): void {
  stopPolling()
  if (!task.value) return
  if (terminalStates.has(task.value.status)) {
    void handleTerminalTask(task.value)
    return
  }
  pollTimer = window.setTimeout(async () => {
    try { rememberTask(await getCarNetworkPointTableTask(task.value!.task_id)); error.value = ''; poll() }
    catch (reason) { error.value = failure(reason, '点表任务状态读取失败') }
  }, 1000)
}
async function startTask(factory: () => Promise<RailTransitTask>, fallback: string): Promise<void> {
  loading.value = true; error.value = ''
  try { rememberTask(await factory()); poll(); openTaskWindow() }
  catch (reason) { error.value = failure(reason, fallback) }
  finally { loading.value = false }
}
async function save(confirmText = `确认保存当前 ${rows.value.length} 行点表与全局规则？`): Promise<void> {
  if (!await confirm({ type: 'DANGER', title: '点表写入确认', message: confirmText, confirmText: '确认写入点表' })) return
  globalConfig.value.point_table_locked = locked.value
  saveStartRevision.value = revision.value
  await startTask(() => saveCarNetworkPointTable(rows.value, globalConfig.value, false, revision.value), '车内通信点表保存启动失败')
}
async function toggleLock(): Promise<void> {
  const next = !locked.value
  if (!await confirm({ type: 'WARNING', title: next ? '锁定点表' : '解锁点表', message: next ? '锁定后须先解锁才能修改点表，确认锁定并保存？' : '确认解锁点表并持久化？', confirmText: next ? '确认锁定并保存' : '确认解锁并保存' })) return
  locked.value = next; globalConfig.value.point_table_locked = next
  await startTask(() => saveCarNetworkPointTable(rows.value, globalConfig.value), '点表锁定状态保存失败')
}
async function generate(): Promise<void> {
  const title = props.train ? '生成当前列车六节点点表' : '从设备生成'
  const message = props.train ? '确认为当前列车生成六节点点表预览？生成结果需要保存后才正式生效。' : '确认从现有设备管理数据重新生成点表预览？当前编辑区不会立即持久化。'
  if (!await confirm({ type: 'WARNING', title, message, confirmText: '确认生成预览' })) return
  await startTask(() => generateCarNetworkPointTable(rows.value, globalConfig.value, targetTrainPayload()), '从设备管理生成点表失败')
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
    const recovered = await recoverCarNetworkPointTableTasks(); const saved = localStorage.getItem(storageKey) || ''
    rememberTask(recovered.find((item) => item.task_id === saved) || recovered.find((item) => !terminalStates.has(item.status)) || recovered[0] || null); poll()
  } catch (reason) { error.value = failure(reason, '点表任务恢复失败') }
}
async function closeDialog(): Promise<void> {
  if (dirty.value) {
    if (!await confirm({ type: 'WARNING', title: '未保存修改', message: '关闭会丢弃未保存的点表修改，是否继续？', confirmText: '放弃修改并关闭' })) return
  }
  visible.value = false
}

watch(() => props.modelValue, (value) => {
  if (value) {
    trainFilter.value = props.train ? currentTrainKey.value : ''
    void Promise.all([loadPointTable(true), recoverTasks()])
  } else {
    stopPolling()
  }
})
watch(() => props.train, (value) => {
  if (props.modelValue && value && !dirty.value) trainFilter.value = currentTrainKey.value
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <el-dialog v-model="visible" title="在线列车车内通信点表" width="96vw" top="2vh" :close-on-click-modal="false" :before-close="closeDialog" destroy-on-close>
    <div class="dialog-body">
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务状态</el-button></el-alert>
      <el-alert v-if="info" :title="info" type="success" show-icon :closable="true" @close="info = ''" />
      <el-descriptions v-if="props.train" :column="3" border size="small" class="train-context">
        <el-descriptions-item label="列车">{{ props.train.display_name || props.train.train_name }}</el-descriptions-item>
        <el-descriptions-item label="车号">{{ props.train.train_no }}</el-descriptions-item>
        <el-descriptions-item label="canonical">{{ currentTrainKey }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="showCurrentTrainEmpty" title="当前列车尚未配置点表" type="warning" show-icon :closable="false">
        <div class="missing-panel"><span>缺少节点：{{ nodeOrder.join('、') }}</span><el-button type="primary" :disabled="locked || !canWrite || taskRunning" @click="generate">为当前列车生成六节点点表</el-button></div>
      </el-alert>
      <el-alert v-else-if="showCurrentTrainMissing" title="当前列车点表不完整" type="warning" show-icon :closable="false">
        <div class="missing-panel"><span>缺少节点：{{ missingNodes.join('、') }}</span><el-button type="primary" :disabled="locked || !canWrite || taskRunning" @click="generate">补齐六节点点表预览</el-button></div>
      </el-alert>
      <div class="filters">
        <el-select v-model="trainFilter" clearable placeholder="全部列车" style="width:180px"><el-option v-for="value in trainOptions" :key="value.key" :label="value.label" :value="value.key" /></el-select>
        <el-select v-model="nodeFilter" clearable placeholder="全部节点类型" style="width:160px"><el-option v-for="value in nodeOptions" :key="value" :label="value" :value="value" /></el-select>
        <el-tag :type="locked ? 'warning' : 'success'">{{ locked ? '点表已锁定' : '点表可编辑' }}</el-tag>
        <el-tooltip :content="canWriteReason || '保存点表锁定状态'"><span><el-button :disabled="!canWrite || taskRunning" @click="toggleLock">{{ locked ? '解锁并保存' : '锁定并保存' }}</el-button></span></el-tooltip>
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
        <el-button :disabled="locked || !canWrite || taskRunning" @click="transform('apply_mapping')">地址映射并应用</el-button><el-button :disabled="locked || !canWrite || taskRunning" @click="generate">{{ props.train ? '生成当前列车六节点' : '从设备管理生成' }}</el-button>
        <el-select v-model="duplicateStrategy" style="width:145px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select>
        <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport"><el-button :disabled="locked || !canWrite || taskRunning" @click="importInput?.click()">导入并预览</el-button>
        <el-select v-model="exportFormat" style="width:95px"><el-option label="XLSX" value="xlsx" /><el-option label="CSV" value="csv" /></el-select><el-button :disabled="!isFeatureEnabled('web.rail_car_network_point_table_export') || taskRunning" @click="exportTable">导出</el-button>
        <el-tooltip :content="canWriteReason || '保存后正式生效并刷新检测页'"><span><el-button type="primary" :disabled="locked || !canWrite || !dirty || taskRunning" @click="save()">保存点表</el-button></span></el-tooltip><el-button @click="closeDialog">取消</el-button>
      </div>
      <NcDataTable v-loading="loading" table-id="car-network-point-table" route-key="/rail-transit/train-communication" :data="filteredRows" :columns="pointTableColumns" border height="42vh" empty-text="暂无点表数据，可从设备管理生成、新增或导入" @selection-change="(value: CarNetworkPointRow[]) => selectedRows = value">
        <template #cell-train_id="{ row }"><el-input v-model="row.train_id" :disabled="locked" @input="markDirty" /></template>
        <template #cell-train_no="{ row }"><el-input v-model="row.train_no" :disabled="locked" @input="markDirty" /></template>
        <template #cell-display_name="{ row }"><el-input v-model="row.display_name" :disabled="locked" @input="markDirty" /></template>
        <template v-for="field in pointTableFields" #[`cell-${field.key}`]="{ row }" :key="field.key"><el-input v-model="row[field.key]" :disabled="locked" @input="markDirty" /></template>
        <template #cell-address_mapping_mode="{ row }"><el-select v-model="row.address_mapping_mode" :disabled="locked" @change="markDirty"><el-option label="全局" value="global" /><el-option label="自定义" value="custom" /></el-select></template>
      </NcDataTable>
      <div v-if="task" class="task-bar"><span>任务已提交，详细进度请查看任务窗口</span><el-tag>{{ task.status }}</el-tag><span>{{ task.error_message || task.message }}</span><el-button @click="openTaskWindow">打开任务窗口</el-button></div>
    </div>
    <el-dialog v-model="previewVisible" title="点表导入预览" width="900px" append-to-body>
      <div v-if="preview" class="preview"><el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ preview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ preview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ preview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ preview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ preview.file_sha256.slice(0, 12) }}...</el-descriptions-item></el-descriptions><NcDataTable table-id="car-network-point-table-import-preview" route-key="/rail-transit/train-communication" :data="preview.rows" :columns="previewColumns" border height="350" :show-column-settings="false" /><el-alert v-if="!preview.can_apply" title="预览存在阻断错误，请修正文件或重复策略后重新导入" type="error" :closable="false" /></div>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" :disabled="!preview?.can_apply" @click="applyPreview">应用到编辑区</el-button></template>
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.dialog-body,.preview{display:flex;flex-direction:column;gap:12px;min-width:0}.filters,.actions,.toolbar,.task-bar,.missing-panel{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.filters span{color:var(--el-text-color-secondary)}.train-context{margin-bottom:2px}.rule-grid{display:grid;grid-template-columns:70px repeat(4,minmax(150px,1fr));gap:8px;align-items:center;margin-bottom:10px}.task-bar{padding:10px 12px;border:1px solid var(--el-border-color-lighter);border-radius:8px}.hidden{display:none}@media(max-width:1000px){.rule-grid{grid-template-columns:70px minmax(150px,1fr)}}
</style>
