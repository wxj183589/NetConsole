<script setup lang="ts">
import { ElMessage } from 'element-plus'
import {
  Check,
  Delete,
  Download,
  Plus,
  Refresh,
  RefreshLeft,
  UploadFilled,
  View,
} from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  exportTracksideApPlan,
  getTracksideApOnlineStatus,
  getTracksideApPlan,
  getTracksideApTask,
  previewTracksideApPlan,
  recoverTracksideApTasks,
  startTracksideApUpdate,
  tracksideApPlanDownloadRequest,
} from '../../../api/tracksideApBusiness'
import { useUserSelectedExport } from '../../../composables/useUserSelectedExport'
import { isFeatureEnabled } from '../../../features'
import { downloadBackendResource } from '../../../platform/runtime'
import type {
  TracksideApOnlineStatus,
  TracksideApOnlineStatusRow,
  TracksideApPlanPreview,
  TracksideApPlanRow,
  TracksideApScopeExcluded,
  TracksideApTask,
  TracksideApUnassigned,
} from '../../../types/tracksideApBusiness'
import { useConfirm } from '../../feedback/useConfirm'
import NcDataTable from '../../table/NcDataTable.vue'
import type { NcTableColumn } from '../../table/NcTableColumn'

interface StationOption {
  id: string
  name: string
  sort_order: number | null
}

type EditableField =
  | 'sequence_no'
  | 'station_name'
  | 'planned_ap_count'
  | 'ap_start_address'
  | 'subnet_mask'
  | 'ap_gateway'
  | 'management_vlan'
  | 'remark'

interface ValidationIssue {
  row: TracksideApPlanRow
  field: EditableField
  message: string
}

const props = withDefaults(
  defineProps<{
    locked: boolean
    saving: boolean
    stations?: StationOption[]
    lineName?: string
  }>(),
  { stations: () => [], lineName: '' },
)
const emit = defineEmits<{
  change: [rows: TracksideApPlanRow[], dirty: boolean]
  save: []
}>()

const router = useRouter()
const { confirm } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const storageKey = 'netconsole.trackside-ap-plan.last-task'
const rows = ref<TracksideApPlanRow[]>([])
const baselineRows = ref<TracksideApPlanRow[]>([])
const selectedRows = ref<TracksideApPlanRow[]>([])
const activeView = ref<'plan' | 'status'>('plan')
const loading = ref(false)
const statusLoading = ref(false)
const error = ref('')
const dirty = ref(false)
const task = ref<TracksideApTask | null>(null)
const importInput = ref<HTMLInputElement | null>(null)
const duplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const importPreview = ref<TracksideApPlanPreview | null>(null)
const importRows = ref<TracksideApPlanRow[]>([])
const importPreviewVisible = ref(false)
const onlineStatus = ref<TracksideApOnlineStatus | null>(null)
const unassignedVisible = ref(false)
const excludedVisible = ref(false)
const downloadingArtifact = ref(false)
let pollTimer: number | undefined
let editingBaseline:
  | { row: TracksideApPlanRow; field: EditableField; value: unknown }
  | null = null

const planColumns: NcTableColumn<TracksideApPlanRow>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 46, fixed: 'left', hideable: false },
  { key: 'sequence_no', label: '序号', valueType: 'number', width: 88, fixed: 'left' },
  { key: 'station_name', label: '车站名称', valueType: 'name', width: 190 },
  { key: 'planned_ap_count', label: '规划AP总数量', valueType: 'number', width: 135 },
  { key: 'ap_start_address', label: 'AP起始地址', valueType: 'ip', width: 165 },
  { key: 'subnet_mask', label: '掩码', valueType: 'name', width: 135 },
  { key: 'ap_gateway', label: 'AP网关', valueType: 'ip', width: 165 },
  { key: 'management_vlan', label: 'AP管理VLAN', valueType: 'number', width: 130 },
  { key: 'remark', label: '备注', valueType: 'description', width: 240, align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', width: 72, fixed: 'right', hideable: false },
]

const statusColumns: NcTableColumn<TracksideApOnlineStatusRow>[] = [
  { key: 'station_name', label: '归属站点', valueType: 'name', minWidth: 170, fixed: 'left' },
  { key: 'planned_ap_count', label: '规划AP总数量', valueType: 'number', width: 135 },
  { key: 'actual_online_count', label: '实际上线', valueType: 'number', width: 110 },
  { key: 'offline_count', label: '未上线', valueType: 'number', width: 100 },
  { key: 'online_rate', label: '上线率', valueType: 'number', width: 105 },
  { key: 'status', label: '状态', valueType: 'status', width: 140 },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 260, align: 'left', alignmentReason: 'long-text' },
]

const unassignedColumns: NcTableColumn<TracksideApUnassigned>[] = [
  { key: 'ap_name', label: 'AP名称', valueType: 'name', minWidth: 170 },
  { key: 'point_code', label: '点位编号', valueType: 'name', width: 130 },
  { key: 'mac', label: 'MAC', valueType: 'mac', width: 170 },
  { key: 'station_name', label: '原归属文本', valueType: 'name', minWidth: 160 },
]

const excludedColumns: NcTableColumn<TracksideApScopeExcluded>[] = [
  { key: 'device_name', label: '设备名称', valueType: 'name', minWidth: 170 },
  { key: 'station_name', label: '归属站点', valueType: 'name', minWidth: 150 },
  { key: 'operation_status', label: '投运状态', valueType: 'status', width: 120 },
  { key: 'project_phase', label: '建设批次', valueType: 'status', width: 120 },
  { key: 'reason', label: '排除原因', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
]

const editableFields: EditableField[] = [
  'sequence_no',
  'station_name',
  'planned_ap_count',
  'ap_start_address',
  'subnet_mask',
  'ap_gateway',
  'management_vlan',
  'remark',
]
const canWrite = computed(() => !props.locked && !props.saving)
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const orderedRows = computed(() => [...rows.value].sort(compareRows))
const orderedStations = computed(() => [...props.stations].sort(
  (left, right) => (left.sort_order ?? Number.MAX_SAFE_INTEGER)
    - (right.sort_order ?? Number.MAX_SAFE_INTEGER)
    || left.name.localeCompare(right.name, 'zh-CN'),
))

const validationIssues = computed<ValidationIssue[]>(() => validateRows(rows.value))
const validationCount = computed(() => validationIssues.value.length)
const countAnomalyRows = computed(
  () => onlineStatus.value?.items.filter((row) => row.count_anomaly) || [],
)

function deepCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function failure(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}

function compareRows(left: TracksideApPlanRow, right: TracksideApPlanRow): number {
  return left.sequence_no - right.sequence_no
    || left.station_name.localeCompare(right.station_name, 'zh-CN')
}

function blankRow(sequenceNo = nextSequence()): TracksideApPlanRow {
  return {
    station_id: '',
    sequence_no: sequenceNo,
    station_name: '',
    planned_ap_count: 0,
    ap_start_address: '',
    subnet_mask: '',
    mask_length: null,
    ap_gateway: '',
    management_vlan: null,
    ap_management_vlans: '',
    remark: '',
    sort_order: sequenceNo - 1,
  }
}

function nextSequence(): number {
  return Math.max(0, ...rows.value.map((row) => Number(row.sequence_no) || 0)) + 1
}

function publishDirty(sort = false): void {
  if (sort) rows.value.sort(compareRows)
  dirty.value = JSON.stringify(rows.value) !== JSON.stringify(baselineRows.value)
  emit('change', deepCopy(rows.value), dirty.value)
}

function hydrateStation(row: TracksideApPlanRow): void {
  const station = props.stations.find((item) => item.id === row.station_id)
    || props.stations.find((item) => item.name === row.station_name)
  if (!station) {
    row.station_id = ''
    return
  }
  row.station_id = station.id
  row.station_name = station.name
}

async function loadPlan(force = false): Promise<boolean> {
  if (dirty.value && !force) return false
  loading.value = true
  error.value = ''
  try {
    const plan = await getTracksideApPlan()
    const loaded = plan.items.map((row, index) => ({
      ...row,
      sequence_no: row.sequence_no || index + 1,
      subnet_mask: row.subnet_mask || (row.mask_length == null ? '' : String(row.mask_length)),
      management_vlan: row.management_vlan
        ?? (row.ap_management_vlans ? Number(row.ap_management_vlans) : null),
    }))
    for (const row of loaded) hydrateStation(row)
    rows.value = loaded.sort(compareRows)
    baselineRows.value = deepCopy(rows.value)
    dirty.value = false
    selectedRows.value = []
    emit('change', deepCopy(rows.value), false)
    await loadOnlineStatus()
    return true
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 规划加载失败')
    return false
  } finally {
    loading.value = false
  }
}

async function loadOnlineStatus(): Promise<void> {
  statusLoading.value = true
  try {
    onlineStatus.value = await getTracksideApOnlineStatus()
  } catch (reason) {
    error.value = failure(reason, 'AP 上线情况加载失败')
  } finally {
    statusLoading.value = false
  }
}

function addRow(): void {
  if (!canWrite.value) return
  rows.value.push(blankRow())
  publishDirty(true)
  void nextTick(() => focusCell(rows.value.at(-1), 'station_name'))
}

function removeRow(row: TracksideApPlanRow): void {
  if (!canWrite.value) return
  rows.value = rows.value.filter((item) => item !== row)
  selectedRows.value = selectedRows.value.filter((item) => item !== row)
  publishDirty()
}

function removeSelected(): void {
  if (!canWrite.value || !selectedRows.value.length) return
  const selected = new Set(selectedRows.value)
  rows.value = rows.value.filter((row) => !selected.has(row))
  selectedRows.value = []
  publishDirty()
}

async function undoChanges(): Promise<void> {
  if (!canWrite.value || !dirty.value) return
  const accepted = await confirm({
    type: 'WARNING',
    title: '放弃规划修改',
    message: '确定放弃当前未保存的修改吗？',
    confirmText: '放弃修改',
  })
  if (!accepted) return
  rows.value = deepCopy(baselineRows.value)
  selectedRows.value = []
  dirty.value = false
  emit('change', deepCopy(rows.value), false)
}

function requestSave(): void {
  if (!canWrite.value || !dirty.value) return
  if (validationIssues.value.length) {
    focusFirstError()
    return
  }
  emit('save')
}

function stationChanged(row: TracksideApPlanRow): void {
  hydrateStation(row)
  publishDirty()
}

function cellError(row: TracksideApPlanRow, field: EditableField): string {
  return validationIssues.value.find(
    (issue) => issue.row === row && issue.field === field,
  )?.message || ''
}

function validateRows(source: TracksideApPlanRow[]): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const sequences = new Map<number, number>()
  const names = new Map<string, number>()
  const stationIds = new Map<string, number>()
  for (const row of source) {
    if (!Number.isInteger(Number(row.sequence_no)) || Number(row.sequence_no) <= 0) {
      issues.push({ row, field: 'sequence_no', message: '序号必须是正整数' })
    } else {
      sequences.set(row.sequence_no, (sequences.get(row.sequence_no) || 0) + 1)
    }
    const name = row.station_name.trim()
    if (!name) issues.push({ row, field: 'station_name', message: '车站名称不能为空' })
    else names.set(name.toLocaleLowerCase(), (names.get(name.toLocaleLowerCase()) || 0) + 1)
    if (row.station_id) stationIds.set(row.station_id, (stationIds.get(row.station_id) || 0) + 1)
    if (!Number.isInteger(Number(row.planned_ap_count)) || Number(row.planned_ap_count) < 0) {
      issues.push({ row, field: 'planned_ap_count', message: '规划AP总数量必须是非负整数' })
    }
    if (row.ap_start_address && !validStartAddress(row.ap_start_address)) {
      issues.push({ row, field: 'ap_start_address', message: '应为 IPv4 或末段 X 占位符' })
    }
    if (row.subnet_mask && !validMask(row.subnet_mask)) {
      issues.push({ row, field: 'subnet_mask', message: '支持 24、/24 或点分掩码' })
    }
    if (row.ap_gateway && !validIpv4(row.ap_gateway)) {
      issues.push({ row, field: 'ap_gateway', message: 'IPv4 格式无效' })
    }
    if (!Number.isInteger(Number(row.management_vlan))
      || Number(row.management_vlan) < 1
      || Number(row.management_vlan) > 4094) {
      issues.push({ row, field: 'management_vlan', message: 'VLAN 必须在 1～4094 范围内' })
    }
  }
  for (const row of source) {
    if ((sequences.get(row.sequence_no) || 0) > 1) {
      issues.push({ row, field: 'sequence_no', message: '序号不能重复' })
    }
    if ((names.get(row.station_name.trim().toLocaleLowerCase()) || 0) > 1) {
      issues.push({ row, field: 'station_name', message: '车站名称不能重复' })
    }
    if (row.station_id && (stationIds.get(row.station_id) || 0) > 1) {
      issues.push({ row, field: 'station_name', message: '同一正式站点只能规划一次' })
    }
  }
  return issues
}

function validStartAddress(value: string): boolean {
  const text = value.trim()
  if (/^(?:\d{1,3}\.){3}[xX]$/.test(text)) {
    return validIpv4(text.replace(/[xX]$/, '1'))
  }
  return validIpv4(text)
}

function validIpv4(value: string): boolean {
  const parts = value.trim().split('.')
  return parts.length === 4 && parts.every(
    (part) => /^\d{1,3}$/.test(part) && Number(part) >= 0 && Number(part) <= 255,
  )
}

function validMask(value: string): boolean {
  const text = value.trim().replace(/^\//, '')
  if (/^\d{1,2}$/.test(text)) return Number(text) >= 0 && Number(text) <= 32
  if (!validIpv4(text)) return false
  const bits = text.split('.').map((part) => Number(part).toString(2).padStart(8, '0')).join('')
  return /^1*0*$/.test(bits)
}

function beginCellEdit(row: TracksideApPlanRow, field: EditableField): void {
  editingBaseline = { row, field, value: row[field] }
}

function cancelCellEdit(row: TracksideApPlanRow, field: EditableField): void {
  if (editingBaseline?.row === row && editingBaseline.field === field) {
    ;(row[field] as unknown) = editingBaseline.value
  }
  editingBaseline = null
  publishDirty()
  const element = document.activeElement
  if (element instanceof HTMLElement) element.blur()
}

function focusCell(row: TracksideApPlanRow | undefined, field: EditableField): void {
  if (!row) return
  const selector = `[data-plan-cell="${cellId(row, field)}"] input`
  document.querySelector<HTMLInputElement>(selector)?.focus()
}

function focusNextRow(row: TracksideApPlanRow, field: EditableField): void {
  const ordered = orderedRows.value
  const index = ordered.indexOf(row)
  const next = ordered[index + 1]
  if (next) void nextTick(() => focusCell(next, field))
}

function cellId(row: TracksideApPlanRow, field: EditableField): string {
  return `${rows.value.indexOf(row)}-${field}`
}

function focusFirstError(): void {
  const issue = validationIssues.value[0]
  if (!issue) return
  activeView.value = 'plan'
  void nextTick(() => focusCell(issue.row, issue.field))
}

function pasteGrid(
  event: ClipboardEvent,
  startRow: TracksideApPlanRow,
  startField: EditableField,
): void {
  if (!canWrite.value) return
  const text = event.clipboardData?.getData('text/plain') || ''
  if (!text) return
  event.preventDefault()
  const grid = text.replace(/\r/g, '').split('\n').filter(
    (line, index, all) => line.length > 0 || index < all.length - 1,
  ).map((line) => line.split('\t'))
  const visible = orderedRows.value
  const rowIndex = Math.max(visible.indexOf(startRow), 0)
  const columnIndex = editableFields.indexOf(startField)
  for (let y = 0; y < grid.length; y += 1) {
    let target = visible[rowIndex + y]
    if (!target) {
      target = blankRow()
      rows.value.push(target)
      visible.push(target)
    }
    for (let x = 0; x < grid[y].length; x += 1) {
      const field = editableFields[columnIndex + x]
      if (!field) break
      assignPastedValue(target, field, grid[y][x])
    }
    hydrateStation(target)
  }
  publishDirty(true)
}

function assignPastedValue(
  row: TracksideApPlanRow,
  field: EditableField,
  value: string,
): void {
  const text = value.trim()
  if (field === 'sequence_no' || field === 'planned_ap_count') {
    ;(row[field] as number) = Number(text)
  } else if (field === 'management_vlan') {
    row.management_vlan = text ? Number(text) : null
    row.ap_management_vlans = text
  } else {
    ;(row[field] as string) = value
  }
}

async function chooseImport(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || props.saving) return
  loading.value = true
  error.value = ''
  try {
    importPreview.value = await previewTracksideApPlan(file, duplicateStrategy.value)
    importRows.value = deepCopy(importPreview.value.result_rows)
    importPreviewVisible.value = true
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 规划导入预览失败')
  } finally {
    loading.value = false
  }
}

function applyImportPreview(): void {
  if (!importPreview.value?.can_apply || !canWrite.value) return
  const issues = validateRows(importRows.value)
  if (issues.length) {
    ElMessage.error(issues[0].message)
    return
  }
  rows.value = deepCopy(importRows.value).sort(compareRows)
  importPreviewVisible.value = false
  publishDirty()
  ElMessage.success('导入预览已应用到编辑区')
}

async function exportPlan(template: boolean): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const suggestedName = template
      ? '轨旁AP逐站规划模板.xlsx'
      : `${safeFileNamePart(props.lineName || '当前线路')}_轨旁AP规划及上线概览_${exportDate()}.xlsx`
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: template ? 'rail.trackside_plan_template' : 'rail.trackside_plan_current',
      suggestedName,
      context: { template },
      submit: () => exportTracksideApPlan(template),
    })
    if (result.status === 'cancelled') return
    await handleTaskUpdate(result.task)
    poll()
  } catch (reason) {
    error.value = failure(reason, template ? '规划模板导出启动失败' : '轨旁 AP 规划导出启动失败')
  } finally {
    loading.value = false
  }
}

async function refreshOnlineStatus(): Promise<void> {
  if (taskRunning.value) return
  statusLoading.value = true
  error.value = ''
  try {
    const started = await startTracksideApUpdate({})
    await handleTaskUpdate(started)
    poll()
  } catch (reason) {
    error.value = failure(reason, '上线状态刷新启动失败')
    statusLoading.value = false
  }
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      const latest = await getTracksideApTask(task.value!.task_id)
      await handleTaskUpdate(latest)
      poll()
    } catch (reason) {
      error.value = failure(reason, '轨旁 AP 任务状态读取失败')
      statusLoading.value = false
    }
  }, 1000)
}

function rememberTask(value: TracksideApTask | null): void {
  task.value = value
  if (value) localStorage.setItem(storageKey, value.task_id)
  else localStorage.removeItem(storageKey)
}

async function handleTaskUpdate(value: TracksideApTask): Promise<void> {
  rememberTask(value)
  if (!terminalStates.has(value.status)) return
  if (value.status === 'COMPLETED' && value.action === 'trackside_ap_optical_update') {
    await loadOnlineStatus()
  } else if (value.status === 'FAILED') {
    error.value = value.error_message || '轨旁 AP 任务失败'
  } else if (value.status === 'CANCELLED') {
    error.value = '轨旁 AP 任务已取消'
  }
  statusLoading.value = false
}

async function recoverTasks(): Promise<void> {
  try {
    const recovered = await recoverTracksideApTasks()
    const saved = localStorage.getItem(storageKey) || ''
    rememberTask(
      recovered.find((item) => item.task_id === saved)
      || recovered.find((item) => !terminalStates.has(item.status))
      || null,
    )
    poll()
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 任务恢复失败')
  }
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
  if (!current || current.status !== 'COMPLETED' || !current.available || !current.artifact_id) return
  const suggestedName = current.artifact_name || '轨旁AP规划及上线概览.xlsx'
  downloadingArtifact.value = true
  try {
    const result = await downloadBackendResource(
      tracksideApPlanDownloadRequest(current.artifact_id, suggestedName),
    )
    if (result.status === 'saved') ElMessage.success(`已保存 ${suggestedName}`)
    else if (result.status === 'started') ElMessage.info(`浏览器已开始下载 ${suggestedName}`)
    else if (result.status === 'failed') ElMessage.error(result.error || '轨旁 AP 规划文件下载失败')
  } catch (reason) {
    ElMessage.error(failure(reason, '轨旁 AP 规划文件下载失败'))
  } finally {
    downloadingArtifact.value = false
  }
}

function exportDate(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}`
}

function safeFileNamePart(value: string): string {
  return value.replace(/[\u0000-\u001f<>:"/\\|?*]/g, '_').trim() || '当前线路'
}

function displayRate(value: number | null): string {
  return value == null ? '—' : `${value.toFixed(1)}%`
}

function statusLabel(row: TracksideApOnlineStatusRow): string {
  if (row.status === 'planning_missing') return '缺少规划资料'
  if (row.status === 'unplanned_online') return '未纳入规划'
  if (row.status === 'over_planned') return '超规划'
  return '正常'
}

function statusTagType(row: TracksideApOnlineStatusRow): 'success' | 'warning' | 'danger' {
  if (row.status === 'over_planned' || row.status === 'unplanned_online') return 'danger'
  if (row.status === 'planning_missing') return 'warning'
  return 'success'
}

function openApReferences(): void {
  void router.replace({ query: { ...router.currentRoute.value.query, tab: 'trackside-ap' } })
}

watch(() => props.stations, () => {
  let changed = false
  for (const row of rows.value) {
    const station = props.stations.find((item) => item.id === row.station_id)
    if (station && station.name !== row.station_name) {
      row.station_name = station.name
      changed = true
    }
  }
  if (changed && canWrite.value) publishDirty()
}, { deep: true })

defineExpose({ reload: loadPlan })
onMounted(() => {
  void Promise.all([loadPlan(true), recoverTasks()])
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="planning-tab">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-tabs v-model="activeView" class="plan-tabs">
      <el-tab-pane label="AP 规划维护" name="plan">
        <div class="toolbar">
          <el-button :icon="Plus" :disabled="!canWrite" @click="addRow">新增站点</el-button>
          <el-button :icon="Delete" :disabled="!canWrite || !selectedRows.length" @click="removeSelected">删除所选</el-button>
          <el-button type="primary" :icon="Check" :loading="props.saving" :disabled="!canWrite || !dirty || validationCount > 0" @click="requestSave">保存</el-button>
          <el-button :icon="RefreshLeft" :disabled="!canWrite || !dirty" @click="undoChanges">撤销修改</el-button>
          <el-select v-model="duplicateStrategy" aria-label="重复策略" class="strategy-select">
            <el-option label="覆盖更新" value="replace" />
            <el-option label="跳过已有" value="skip" />
            <el-option label="重复时报错" value="error" />
          </el-select>
          <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport">
          <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(true)">下载模板</el-button>
          <el-button :icon="UploadFilled" :disabled="props.saving || taskRunning" @click="importInput?.click()">导入并预览</el-button>
          <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(false)">导出当前</el-button>
          <el-button :icon="View" @click="openApReferences">查看 AP 参考信息</el-button>
          <el-button v-if="validationCount" type="danger" plain @click="focusFirstError">有 {{ validationCount }} 项需要修正</el-button>
          <span class="dirty-state">{{ dirty ? '有未保存修改' : `已加载 ${rows.length} 行` }}</span>
        </div>

        <div class="table-shell">
          <NcDataTable
            v-loading="loading"
            table-id="rail-base-trackside-ap-plan"
            route-key="/rail-transit/base-data"
            :data="orderedRows"
            :columns="planColumns"
            border
            height="calc(100vh - 430px)"
            empty-text="暂无 AP 规划"
            @selection-change="(value: TracksideApPlanRow[]) => selectedRows = value"
          >
            <template #cell-sequence_no="{ row }">
              <div :data-plan-cell="cellId(row, 'sequence_no')" :title="cellError(row, 'sequence_no')">
                <el-input-number
                  v-if="canWrite"
                  v-model="row.sequence_no"
                  :min="1"
                  :controls="false"
                  :class="{ 'field-error': cellError(row, 'sequence_no') }"
                  @focus="beginCellEdit(row, 'sequence_no')"
                  @change="publishDirty(true)"
                  @paste="pasteGrid($event, row, 'sequence_no')"
                  @keydown.enter.prevent="focusNextRow(row, 'sequence_no')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'sequence_no')"
                />
                <span v-else>{{ row.sequence_no }}</span>
              </div>
            </template>
            <template #cell-station_name="{ row }">
              <div :data-plan-cell="cellId(row, 'station_name')" :title="cellError(row, 'station_name')">
                <el-select
                  v-if="canWrite"
                  v-model="row.station_name"
                  filterable
                  allow-create
                  default-first-option
                  :class="{ 'field-error': cellError(row, 'station_name') }"
                  @focus="beginCellEdit(row, 'station_name')"
                  @change="stationChanged(row)"
                  @paste="pasteGrid($event, row, 'station_name')"
                  @keydown.enter.prevent="focusNextRow(row, 'station_name')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'station_name')"
                >
                  <el-option v-for="station in orderedStations" :key="station.id" :label="station.name" :value="station.name" />
                </el-select>
                <span v-else>{{ row.station_name }}</span>
              </div>
            </template>
            <template #cell-planned_ap_count="{ row }">
              <div :data-plan-cell="cellId(row, 'planned_ap_count')" :title="cellError(row, 'planned_ap_count')">
                <el-input-number
                  v-if="canWrite"
                  v-model="row.planned_ap_count"
                  :min="0"
                  :controls="false"
                  :class="{ 'field-error': cellError(row, 'planned_ap_count') }"
                  @focus="beginCellEdit(row, 'planned_ap_count')"
                  @change="publishDirty()"
                  @paste="pasteGrid($event, row, 'planned_ap_count')"
                  @keydown.enter.prevent="focusNextRow(row, 'planned_ap_count')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'planned_ap_count')"
                />
                <span v-else>{{ row.planned_ap_count }}</span>
              </div>
            </template>
            <template v-for="field in (['ap_start_address', 'subnet_mask', 'ap_gateway', 'remark'] as EditableField[])" #[`cell-${field}`]="{ row }" :key="field">
              <div :data-plan-cell="cellId(row, field)" :title="cellError(row, field)">
                <el-input
                  v-if="canWrite"
                  v-model="row[field]"
                  :class="{ 'field-error': cellError(row, field) }"
                  @focus="beginCellEdit(row, field)"
                  @input="publishDirty()"
                  @paste="pasteGrid($event, row, field)"
                  @keydown.enter.prevent="focusNextRow(row, field)"
                  @keydown.esc.prevent="cancelCellEdit(row, field)"
                />
                <span v-else>{{ row[field] || '--' }}</span>
              </div>
            </template>
            <template #cell-management_vlan="{ row }">
              <div :data-plan-cell="cellId(row, 'management_vlan')" :title="cellError(row, 'management_vlan')">
                <el-input-number
                  v-if="canWrite"
                  v-model="row.management_vlan"
                  :min="1"
                  :max="4094"
                  :controls="false"
                  :class="{ 'field-error': cellError(row, 'management_vlan') }"
                  @focus="beginCellEdit(row, 'management_vlan')"
                  @change="publishDirty()"
                  @paste="pasteGrid($event, row, 'management_vlan')"
                  @keydown.enter.prevent="focusNextRow(row, 'management_vlan')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'management_vlan')"
                />
                <span v-else>{{ row.management_vlan ?? '--' }}</span>
              </div>
            </template>
            <template #cell-actions="{ row }">
              <el-button link type="danger" :icon="Delete" :disabled="!canWrite" title="删除" @click="removeRow(row)" />
            </template>
          </NcDataTable>
        </div>
      </el-tab-pane>

      <el-tab-pane label="AP 上线情况概览" name="status">
        <div class="status-toolbar">
          <el-button type="primary" :icon="Refresh" :loading="statusLoading" :disabled="taskRunning" @click="refreshOnlineStatus">刷新上线状态</el-button>
          <span>状态更新时间：{{ onlineStatus?.updated_at || '--' }}</span>
          <span class="status-definition">规划 AP 总数量由用户维护；实际上线数量来自最新 AC/FIT-AP 状态。</span>
        </div>
        <div v-if="onlineStatus" class="scope-summary">
          <strong>统计范围：{{ onlineStatus.scope_description || '当前项目 · 在用轨旁 AP' }}</strong>
          <span>纳入站点 {{ onlineStatus.scope_station_count || 0 }}</span>
          <span>纳入设备 {{ onlineStatus.scope_device_count || 0 }}</span>
          <span>排除设备 {{ onlineStatus.excluded_device_count || 0 }}</span>
          <el-button
            v-if="onlineStatus.excluded_device_count"
            link
            type="warning"
            @click="excludedVisible = true"
          >查看排除项</el-button>
        </div>
        <el-alert
          v-if="onlineStatus?.warning"
          :title="onlineStatus.warning"
          type="warning"
          :closable="false"
          show-icon
        >
          <el-button v-if="onlineStatus?.unassigned_count" link type="warning" @click="unassignedVisible = true">查看未分配 AP</el-button>
          <el-button v-if="onlineStatus?.excluded_device_count" link type="warning" @click="excludedVisible = true">查看排除项</el-button>
        </el-alert>
        <el-alert
          v-if="countAnomalyRows.length"
          title="存在未纳入规划或超规划的在线 AP，请检查规划资料和 AP 归属关系。"
          type="warning"
          :closable="false"
          show-icon
        >
          <el-button link type="warning" @click="openApReferences">查看异常 AP 资料</el-button>
        </el-alert>
        <div class="table-shell">
          <NcDataTable
            v-loading="statusLoading"
            table-id="rail-base-trackside-ap-online-status"
            route-key="/rail-transit/base-data"
            :data="onlineStatus?.items || []"
            :columns="statusColumns"
            border
            height="calc(100vh - 460px)"
            empty-text="暂无 AP 上线情况"
          >
            <template #cell-station_name="{ row }">
              <span>{{ row.station_name }}</span>
            </template>
            <template #cell-planned_ap_count="{ row }">{{ row.planning_missing ? '未填写' : row.planned_ap_count }}</template>
            <template #cell-online_rate="{ row }">{{ displayRate(row.online_rate) }}</template>
            <template #cell-status="{ row }">
              <el-tag :type="statusTagType(row)" size="small" :title="row.warning">{{ statusLabel(row) }}</el-tag>
            </template>
            <template #cell-remark="{ row }">{{ row.remark || '--' }}</template>
          </NcDataTable>
          <div v-if="onlineStatus" class="status-total">
            <strong>合计</strong>
            <span>规划总数 {{ onlineStatus.planned_ap_count }}</span>
            <span>实际上线 {{ onlineStatus.actual_online_count }}</span>
            <span>未上线 {{ onlineStatus.offline_count }}</span>
            <span>总上线率 {{ displayRate(onlineStatus.online_rate) }}</span>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-alert
      v-if="task"
      :title="`${task.status} · ${task.message || task.task_id}`"
      :type="task.error_message ? 'error' : 'info'"
      :closable="false"
    >
      <el-button v-if="task.available && task.artifact_id" link type="primary" :loading="downloadingArtifact" @click="downloadArtifact">下载文件</el-button>
      <el-button link @click="openTaskWindow">打开任务中心</el-button>
    </el-alert>

    <el-dialog v-model="importPreviewVisible" title="导入预览" width="min(1180px, 94vw)" destroy-on-close>
      <div v-if="importPreview" class="preview">
        <el-alert v-if="importPreview.legacy_schema" :title="importPreview.message" type="warning" :closable="false" show-icon />
        <el-descriptions :column="4" border>
          <el-descriptions-item label="总行数">{{ importPreview.total_count }}</el-descriptions-item>
          <el-descriptions-item label="有效">{{ importPreview.valid_count }}</el-descriptions-item>
          <el-descriptions-item label="重复">{{ importPreview.duplicate_count }}</el-descriptions-item>
          <el-descriptions-item label="错误">{{ importPreview.error_count }}</el-descriptions-item>
        </el-descriptions>
        <NcDataTable
          table-id="rail-base-trackside-ap-plan-import-preview"
          route-key="/rail-transit/base-data"
          :data="importRows"
          :columns="planColumns.filter((column) => !['selection', 'actions'].includes(String(column.key)))"
          border
          height="390"
          :show-column-settings="false"
        >
          <template #cell-sequence_no="{ row }"><el-input-number v-model="row.sequence_no" :min="1" :controls="false" /></template>
          <template #cell-station_name="{ row }"><el-input v-model="row.station_name" /></template>
          <template #cell-planned_ap_count="{ row }"><el-input-number v-model="row.planned_ap_count" :min="0" :controls="false" /></template>
          <template #cell-ap_start_address="{ row }"><el-input v-model="row.ap_start_address" /></template>
          <template #cell-subnet_mask="{ row }"><el-input v-model="row.subnet_mask" /></template>
          <template #cell-ap_gateway="{ row }"><el-input v-model="row.ap_gateway" /></template>
          <template #cell-management_vlan="{ row }"><el-input-number v-model="row.management_vlan" :min="1" :max="4094" :controls="false" /></template>
          <template #cell-remark="{ row }"><el-input v-model="row.remark" /></template>
        </NcDataTable>
        <el-alert v-if="!importPreview.can_apply" title="预览存在错误" type="error" :closable="false" />
      </div>
      <template #footer>
        <el-button @click="importPreviewVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!importPreview?.can_apply || !canWrite" @click="applyImportPreview">应用到编辑区</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="unassignedVisible" title="未分配站点 AP" width="min(900px, 92vw)">
      <NcDataTable
        table-id="rail-base-trackside-ap-unassigned"
        route-key="/rail-transit/base-data"
        :data="onlineStatus?.unassigned_items || []"
        :columns="unassignedColumns"
        border
        height="420"
        empty-text="没有未分配 AP"
      />
    </el-dialog>

    <el-dialog v-model="excludedVisible" title="当前统计范围排除项" width="min(1040px, 94vw)">
      <NcDataTable
        table-id="rail-base-trackside-ap-scope-excluded"
        route-key="/rail-transit/base-data"
        :data="onlineStatus?.excluded_items || []"
        :columns="excludedColumns"
        border
        height="460"
        empty-text="没有排除项"
      />
    </el-dialog>
  </section>
</template>

<style scoped>
.planning-tab,
.preview {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.plan-tabs {
  min-width: 0;
}

.toolbar,
.status-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.strategy-select {
  width: 128px;
}

.status-definition {
  color: var(--nc-text-secondary);
}

.scope-summary {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  padding: 0 0 12px;
  color: var(--nc-text-secondary);
}

.scope-summary strong {
  color: var(--nc-text-primary);
}

.dirty-state {
  margin-left: auto;
  color: var(--nc-text-secondary);
}

.hidden {
  display: none;
}

.table-shell {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.table-shell :deep(.nc-data-table) {
  width: 100%;
  min-width: 1120px;
}

.field-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}

.status-total {
  display: grid;
  grid-template-columns: minmax(170px, 1fr) repeat(4, minmax(120px, auto));
  align-items: center;
  min-width: 900px;
  padding: 10px 16px;
  border: 1px solid var(--nc-border-color);
  border-top: 0;
  background: var(--nc-surface-muted);
}

@media (max-width: 900px) {
  .dirty-state {
    width: 100%;
    margin-left: 0;
  }
}
</style>
