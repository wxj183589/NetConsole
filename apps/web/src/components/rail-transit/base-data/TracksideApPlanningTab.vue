<script setup lang="ts">
import { ElMessage } from 'element-plus'
import {
  Check,
  Delete,
  Plus,
  Refresh,
  RefreshLeft,
} from '@element-plus/icons-vue'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTracksideApOnlineStatus,
  getTracksideApPlan,
  listTracksideApOnlineExcluded,
  listTracksideApOnlineUnmatched,
  startTracksideApUpdate,
} from '../../../api/tracksideApBusiness'
import { apiErrorDetail, type ApiErrorDetail } from '../../../api/client'
import { useTaskStore } from '../../../stores/tasks'
import type {
  TracksideApOnlineStatus,
  TracksideApOnlineStatusRow,
  TracksideApPlanRow,
  TracksideApScopeExcluded,
  TracksideApUnmatchedOnline,
  TracksideApUnassigned,
} from '../../../types/tracksideApBusiness'
import type { TaskItem } from '../../../types/task'
import { activeTaskStatuses } from '../../../utils/taskStatus'
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
  | 'management_vlan'
  | 'remark'

interface ValidationIssue {
  row: TracksideApPlanRow
  field: EditableField
  message: string
}

interface ValidationIssueRow {
  id: string
  row_number: number
  sequence_no: number
  station_name: string
  field: string
  message: string
  suggestion: string
  source: ValidationIssue
}

const props = withDefaults(
  defineProps<{
    locked: boolean
    saving: boolean
    stations?: StationOption[]
  }>(),
  { stations: () => [] },
)
const emit = defineEmits<{
  change: [rows: TracksideApPlanRow[], dirty: boolean]
  save: []
  'generate-stations': []
}>()

const router = useRouter()
const { confirm } = useConfirm()
const taskStore = useTaskStore()
const activeStates = new Set(activeTaskStatuses)
const planningTaskTypes = new Set(['trackside_ap_optical_update'])
const rows = ref<TracksideApPlanRow[]>([])
const baselineRows = ref<TracksideApPlanRow[]>([])
const selectedRows = ref<TracksideApPlanRow[]>([])
const activeView = ref<'plan' | 'status'>('plan')
const loading = ref(false)
const statusLoading = ref(false)
const error = ref('')
const planningError = ref<ApiErrorDetail | null>(null)
const onlineStatusError = ref<ApiErrorDetail | null>(null)
const dirty = ref(false)
const currentTaskId = ref('')
const onlineStatus = ref<TracksideApOnlineStatus | null>(null)
const unassignedVisible = ref(false)
const excludedVisible = ref(false)
const unmatchedVisible = ref(false)
const excludedItems = ref<TracksideApScopeExcluded[]>([])
const excludedPage = ref(1)
const excludedTotal = ref(0)
const excludedLoading = ref(false)
const unmatchedItems = ref<TracksideApUnmatchedOnline[]>([])
const unmatchedPage = ref(1)
const unmatchedTotal = ref(0)
const unmatchedLoading = ref(false)
const issuesVisible = ref(false)
let editingBaseline:
  | { row: TracksideApPlanRow; field: EditableField; value: unknown }
  | null = null

const planColumns: NcTableColumn<TracksideApPlanRow>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 44, hideable: false },
  { key: 'sequence_no', label: '序号', valueType: 'number', width: 80 },
  { key: 'station_name', label: '车站名称', valueType: 'name', minWidth: 220 },
  { key: 'planned_ap_count', label: 'AP数量', valueType: 'number', width: 120 },
  { key: 'management_vlan', label: 'AP管理VLAN', valueType: 'number', width: 140 },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 240, align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', width: 64, hideable: false },
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
const issueColumns: NcTableColumn<ValidationIssueRow>[] = [
  { key: 'row_number', label: '行号', valueType: 'number', width: 80 },
  { key: 'sequence_no', label: '序号', valueType: 'number', width: 80 },
  { key: 'station_name', label: '车站名称', valueType: 'name', minWidth: 180 },
  { key: 'field', label: '字段', valueType: 'name', width: 120 },
  { key: 'message', label: '问题', valueType: 'description', minWidth: 240, align: 'left', alignmentReason: 'long-text' },
  { key: 'suggestion', label: '建议处理', valueType: 'description', minWidth: 260, align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', width: 90, hideable: false },
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
  { key: 'operation_status', label: '当前工作状态', valueType: 'status', width: 130 },
  { key: 'project_phase', label: '建设批次', valueType: 'status', width: 120 },
  { key: 'reason', label: '排除原因', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
]
const unmatchedColumns: NcTableColumn<TracksideApUnmatchedOnline>[] = [
  { key: 'ap_name', label: 'AP名称', valueType: 'name', minWidth: 170 },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', width: 170 },
  { key: 'ac_status', label: 'AC状态', valueType: 'status', width: 130 },
  { key: 'runtime_station_text', label: '运行态站点', valueType: 'name', minWidth: 170 },
  { key: 'reason', label: '未关联原因', valueType: 'description', minWidth: 280, align: 'left', alignmentReason: 'long-text' },
  { key: 'suggested_action', label: '建议处理', valueType: 'description', minWidth: 300, align: 'left', alignmentReason: 'long-text' },
]

const editableFields: EditableField[] = [
  'sequence_no',
  'station_name',
  'planned_ap_count',
  'management_vlan',
  'remark',
]
const canWrite = computed(() => !props.locked && !props.saving)
const currentTask = computed<TaskItem | null>(() => (
  taskStore.tasks.find((item) => item.id === currentTaskId.value) || null
))
const taskRunning = computed(() => taskStore.tasks.some(
  (item) => planningTaskTypes.has(item.type) && activeStates.has(item.status),
))
const orderedRows = computed(() => [...rows.value].sort(compareRows))
const orderedStations = computed(() => [...props.stations].sort(
  (left, right) => (left.sort_order ?? Number.MAX_SAFE_INTEGER)
    - (right.sort_order ?? Number.MAX_SAFE_INTEGER)
    || left.name.localeCompare(right.name, 'zh-CN'),
))

const validationIssues = computed<ValidationIssue[]>(() => validateRows(rows.value))
const validationCount = computed(() => validationIssues.value.length)
const validationIssueRows = computed<ValidationIssueRow[]>(() => validationIssues.value.map(
  (issue, index) => ({
    id: `${rows.value.indexOf(issue.row)}:${issue.field}:${index}`,
    row_number: rows.value.indexOf(issue.row) + 1,
    sequence_no: issue.row.sequence_no,
    station_name: issue.row.station_name,
    field: fieldLabel(issue.field),
    message: issue.message,
    suggestion: issueSuggestion(issue),
    source: issue,
  }),
))
const countAnomalyRows = computed(
  () => onlineStatus.value?.items.filter((row) => row.count_anomaly) || [],
)
const unassignedItems = computed<TracksideApUnassigned[]>(() => unmatchedItems.value.map((item) => ({
  ap_id: item.item_id,
  ap_name: item.ap_name,
  point_code: '',
  mac: item.mac,
  station_name: item.runtime_station_text,
})))

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
    management_vlan: null,
    remark: '',
    station_match_status: 'unmatched',
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

function canonicalStationName(value: unknown): string {
  return String(value || '')
    .normalize('NFKC')
    .trim()
    .replace(/^[0-9０-９]+(?:[-_.、\s]*)/, '')
    .replace(/\s+/g, '')
    .toLocaleLowerCase()
}

function stationForRow(row: TracksideApPlanRow): StationOption | null {
  const byId = props.stations.find((item) => item.id === row.station_id)
  if (byId) return byId
  const key = canonicalStationName(row.station_name)
  if (!key) return null
  const matches = props.stations.filter((item) => canonicalStationName(item.name) === key)
  return matches.length === 1 ? matches[0] : null
}

function hydrateStation(row: TracksideApPlanRow): void {
  const station = stationForRow(row)
  if (!station) {
    row.station_match_status = 'unmatched'
    return
  }
  row.station_id = station.id
  row.station_name = station.name
  row.station_match_status = 'matched'
}

function mergePlanRows(sourceRows: TracksideApPlanRow[]): TracksideApPlanRow[] {
  return sourceRows.map((source, index) => {
    const row = {
      ...source,
      sequence_no: Number(source.sequence_no) || index + 1,
      station_match_status: source.station_match_status || 'unmatched',
    }
    hydrateStation(row)
    return row
  }).sort(compareRows)
}

async function loadPlan(force = false): Promise<boolean> {
  if (dirty.value && !force) return false
  loading.value = true
  try {
    const plan = await getTracksideApPlan()
    rows.value = mergePlanRows(plan.items)
    baselineRows.value = deepCopy(rows.value)
    dirty.value = false
    selectedRows.value = []
    planningError.value = null
    emit('change', deepCopy(rows.value), false)
    return true
  } catch (reason) {
    planningError.value = apiErrorDetail(
      reason,
      '/api/rail-transit/trackside-ap-business/plan',
    )
    return false
  } finally {
    loading.value = false
  }
}

async function loadOnlineStatus(): Promise<void> {
  statusLoading.value = true
  try {
    const previousRevision = onlineStatus.value?.revision || ''
    const result = await getTracksideApOnlineStatus()
    onlineStatus.value = result
    if (previousRevision && previousRevision !== result.revision) {
      excludedItems.value = []
      excludedPage.value = 1
      excludedTotal.value = 0
      unmatchedItems.value = []
      unmatchedPage.value = 1
      unmatchedTotal.value = 0
    }
    onlineStatusError.value = null
  } catch (reason) {
    onlineStatusError.value = apiErrorDetail(
      reason,
      '/api/rail-transit/trackside-ap-business/plan/online-status',
    )
  } finally {
    statusLoading.value = false
  }
}

async function loadExcludedDetails(page = 1): Promise<void> {
  excludedLoading.value = true
  try {
    const result = await listTracksideApOnlineExcluded(page)
    excludedItems.value = result.items
    excludedPage.value = result.page
    excludedTotal.value = result.total
  } catch (reason) {
    ElMessage.error(apiErrorDetail(
      reason,
      '/api/rail-transit/trackside-ap-business/plan/online-status/excluded',
    ).message)
  } finally {
    excludedLoading.value = false
  }
}

async function loadUnmatchedDetails(page = 1): Promise<void> {
  unmatchedLoading.value = true
  try {
    const result = await listTracksideApOnlineUnmatched(page)
    unmatchedItems.value = result.items
    unmatchedPage.value = result.page
    unmatchedTotal.value = result.total
  } catch (reason) {
    ElMessage.error(apiErrorDetail(
      reason,
      '/api/rail-transit/trackside-ap-business/plan/online-status/unmatched',
    ).message)
  } finally {
    unmatchedLoading.value = false
  }
}

function openExcludedDetails(): void {
  excludedVisible.value = true
  void loadExcludedDetails(1)
}

function openUnmatchedDetails(): void {
  unmatchedVisible.value = true
  void loadUnmatchedDetails(1)
}

function openUnassignedDetails(): void {
  unassignedVisible.value = true
  void loadUnmatchedDetails(1)
}

async function reload(force = false): Promise<boolean> {
  const [planLoaded] = await Promise.all([
    loadPlan(force),
    loadOnlineStatus(),
  ])
  return planLoaded
}

async function reloadPlan(force = false): Promise<boolean> {
  return loadPlan(force)
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

function stationOptionDisabled(station: StationOption, current: TracksideApPlanRow): boolean {
  return rows.value.some((row) => row !== current && row.station_id === station.id)
}

function fieldLabel(field: EditableField): string {
  return {
    sequence_no: '序号',
    station_name: '车站名称',
    planned_ap_count: 'AP数量',
    management_vlan: 'AP管理VLAN',
    remark: '备注',
  }[field]
}

function issueSuggestion(issue: ValidationIssue): string {
  if (issue.field === 'sequence_no') return '填写不重复的正整数序号；序号可不连续。'
  if (issue.field === 'station_name') return '从当前基础资料站点中重新选择，或删除该规划行。'
  if (issue.field === 'planned_ap_count') return '填写大于或等于 0 的整数。'
  if (issue.field === 'management_vlan') return 'AP 数量大于 0 时填写 1～4094 的整数。'
  return '修正当前字段后重新校验。'
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
    if (!row.station_id) {
      issues.push({ row, field: 'station_name', message: '请选择当前基础资料中的站点' })
    } else if (row.station_match_status === 'unmatched' || !props.stations.some((station) => station.id === row.station_id)) {
      issues.push({ row, field: 'station_name', message: '未匹配当前站点，请重新选择有效站点或删除该行' })
    } else {
      stationIds.set(row.station_id, (stationIds.get(row.station_id) || 0) + 1)
    }
    const plannedApCount = Number(row.planned_ap_count)
    if (!Number.isInteger(plannedApCount) || plannedApCount < 0) {
      issues.push({ row, field: 'planned_ap_count', message: 'AP数量必须是非负整数' })
    }
    const vlanMissing = row.management_vlan === null
      || row.management_vlan === undefined
    if (vlanMissing && plannedApCount > 0) {
      issues.push({ row, field: 'management_vlan', message: 'AP数量大于 0 时必须填写 VLAN' })
    } else if (!vlanMissing && (
      !Number.isInteger(Number(row.management_vlan))
      || Number(row.management_vlan) < 1
      || Number(row.management_vlan) > 4094
    )) {
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
  } else {
    ;(row[field] as string) = value
  }
}

async function refreshOnlineStatus(): Promise<void> {
  if (taskRunning.value) return
  statusLoading.value = true
  error.value = ''
  try {
    const started = await startTracksideApUpdate({})
    currentTaskId.value = started.task_id
    await taskStore.refresh()
    if (!currentTask.value || !activeStates.has(currentTask.value.status)) {
      statusLoading.value = false
    }
  } catch (reason) {
    error.value = failure(reason, '上线状态刷新启动失败')
    statusLoading.value = false
  }
}

function focusIssue(issue: ValidationIssue): void {
  issuesVisible.value = false
  activeView.value = 'plan'
  void nextTick(() => focusCell(issue.row, issue.field))
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
  if (!dirty.value) {
    const merged = mergePlanRows(rows.value)
    rows.value = merged
    baselineRows.value = deepCopy(merged)
    dirty.value = false
    emit('change', deepCopy(rows.value), false)
    return
  }
  let changed = false
  for (const row of rows.value) {
    const previous = `${row.station_id}\u0000${row.station_name}\u0000${row.station_match_status}`
    hydrateStation(row)
    changed = changed
      || previous !== `${row.station_id}\u0000${row.station_name}\u0000${row.station_match_status}`
  }
  if (changed) publishDirty()
}, { deep: true })

watch(
  () => currentTask.value?.status,
  (status, previousStatus) => {
    if (currentTask.value?.type !== 'trackside_ap_optical_update' || !status) return
    if (!activeStates.has(status)) statusLoading.value = false
    if (status === 'COMPLETED' && previousStatus !== 'COMPLETED') void loadOnlineStatus()
  },
)

defineExpose({ reload, reloadPlan })
onMounted(() => {
  void Promise.all([
    reload(true),
    taskStore.refresh().then(() => {
      currentTaskId.value = taskStore.tasks.find(
        (item) => planningTaskTypes.has(item.type) && activeStates.has(item.status),
      )?.id || ''
    }),
  ])
})
</script>

<template>
  <section class="planning-tab">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

    <el-tabs v-model="activeView" class="plan-tabs">
      <el-tab-pane label="AP 规划维护" name="plan">
        <el-alert
          v-if="planningError"
          title="轨旁 AP 规划刷新失败，已保留最后成功数据。"
          type="error"
          show-icon
          :closable="false"
          class="local-request-error"
        >
          <details>
            <summary>查看错误详情</summary>
            <span>错误码：{{ planningError.code }}</span>
            <span v-if="planningError.status > 0">HTTP {{ planningError.status }}</span>
            <span v-if="planningError.requestId">request_id：{{ planningError.requestId }}</span>
            <small>{{ planningError.path }}</small>
            <small>{{ planningError.originalMessage }}</small>
          </details>
        </el-alert>
        <div class="toolbar">
          <el-button :icon="Plus" :disabled="!canWrite" @click="addRow">新增站点</el-button>
          <el-button :icon="Delete" :disabled="!canWrite || !selectedRows.length" @click="removeSelected">删除所选</el-button>
          <el-button type="primary" :icon="Check" :loading="props.saving" :disabled="!canWrite || !dirty || validationCount > 0" @click="requestSave">保存</el-button>
          <el-button :icon="RefreshLeft" :disabled="!canWrite || !dirty" @click="undoChanges">撤销修改</el-button>
          <el-button :icon="Refresh" :disabled="props.saving || taskRunning" @click="emit('generate-stations')">从设备管理生成站点</el-button>
          <el-button v-if="validationCount" type="danger" plain @click="issuesVisible = true">有 {{ validationCount }} 项需要修正</el-button>
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
            :empty-text="props.stations.length ? '暂无 AP 规划' : '暂无站点资料，请先在‘站点与区间’中维护站点。'"
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
                  default-first-option
                  :class="{ 'field-error': cellError(row, 'station_name') }"
                  @focus="beginCellEdit(row, 'station_name')"
                  @change="stationChanged(row)"
                  @paste="pasteGrid($event, row, 'station_name')"
                  @keydown.enter.prevent="focusNextRow(row, 'station_name')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'station_name')"
                >
                <el-option
                  v-for="station in orderedStations"
                  :key="station.id"
                  :label="station.name"
                  :value="station.name"
                  :disabled="stationOptionDisabled(station, row)"
                />
                </el-select>
                <span v-else>{{ row.station_name }}</span>
                <el-tag v-if="row.station_match_status === 'unmatched'" type="danger" size="small">未匹配当前站点</el-tag>
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
            <template #cell-remark="{ row }">
              <div :data-plan-cell="cellId(row, 'remark')" :title="cellError(row, 'remark')">
                <el-input
                  v-if="canWrite"
                  v-model="row.remark"
                  :class="{ 'field-error': cellError(row, 'remark') }"
                  @focus="beginCellEdit(row, 'remark')"
                  @input="publishDirty()"
                  @paste="pasteGrid($event, row, 'remark')"
                  @keydown.enter.prevent="focusNextRow(row, 'remark')"
                  @keydown.esc.prevent="cancelCellEdit(row, 'remark')"
                />
                <span v-else>{{ row.remark || '--' }}</span>
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
        <el-alert
          v-if="onlineStatusError"
          title="AP 上线状态刷新失败，已保留最后成功数据。"
          type="warning"
          show-icon
          :closable="false"
          class="local-request-error"
        >
          <details>
            <summary>查看错误详情</summary>
            <span>错误码：{{ onlineStatusError.code }}</span>
            <span v-if="onlineStatusError.status > 0">HTTP {{ onlineStatusError.status }}</span>
            <span v-if="onlineStatusError.requestId">request_id：{{ onlineStatusError.requestId }}</span>
            <small>{{ onlineStatusError.path }}</small>
            <small>{{ onlineStatusError.originalMessage }}</small>
          </details>
        </el-alert>
        <div class="status-toolbar">
          <el-button type="primary" :icon="Refresh" :loading="statusLoading" :disabled="taskRunning" @click="refreshOnlineStatus">刷新上线状态</el-button>
          <span>状态更新时间：{{ onlineStatus?.updated_at || '--' }}（数据采集时间）</span>
          <span>本次查询：{{ onlineStatus?.generated_at || '--' }}</span>
          <span class="status-definition">规划 AP 总数量由用户维护；实际上线数量来自最新 AC/FIT-AP 状态。</span>
        </div>
        <div v-if="onlineStatus" class="scope-summary">
          <strong>统计范围：{{ onlineStatus.scope_description || '当前项目 · 当前工作范围轨旁 AP' }}</strong>
          <span>纳入站点 {{ onlineStatus.scope_station_count || 0 }}</span>
          <span>纳入 AP 资料 {{ onlineStatus.scope_ap_reference_count ?? onlineStatus.scope_device_count ?? 0 }}</span>
          <span>排除设备 {{ onlineStatus.excluded_device_count || 0 }}</span>
          <el-button v-if="onlineStatus.fit_ap_unmatched_online_count" link type="warning" @click="openUnmatchedDetails">待关联在线 AP {{ onlineStatus.fit_ap_unmatched_online_count }}</el-button>
          <el-button
            v-if="onlineStatus.excluded_device_count"
            link
            type="warning"
            @click="openExcludedDetails"
          >查看排除项</el-button>
        </div>
        <el-alert
          v-if="onlineStatus?.warning"
          :title="onlineStatus.warning"
          type="warning"
          :closable="false"
          show-icon
        >
          <el-button v-if="onlineStatus?.fit_ap_unmatched_online_count" link type="warning" @click="openUnmatchedDetails">待关联在线 AP {{ onlineStatus.fit_ap_unmatched_online_count }}</el-button>
          <el-button v-if="onlineStatus?.unassigned_count" link type="warning" @click="openUnassignedDetails">查看未分配 AP</el-button>
          <el-button v-if="onlineStatus?.excluded_device_count" link type="warning" @click="openExcludedDetails">查看排除项</el-button>
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

    <el-dialog v-model="issuesVisible" title="规划问题明细" width="min(1180px, 94vw)">
      <NcDataTable
        table-id="rail-base-trackside-ap-plan-issues"
        route-key="/rail-transit/base-data"
        :data="validationIssueRows"
        :columns="issueColumns"
        border
        height="460"
        empty-text="当前没有规划问题"
      >
        <template #cell-actions="{ row }">
          <el-button link type="primary" @click="focusIssue(row.source)">定位</el-button>
        </template>
      </NcDataTable>
    </el-dialog>

    <el-dialog v-model="unassignedVisible" title="未分配站点 AP" width="min(900px, 92vw)">
      <NcDataTable
        v-loading="unmatchedLoading"
        table-id="rail-base-trackside-ap-unassigned"
        route-key="/rail-transit/base-data"
        :data="unassignedItems"
        :columns="unassignedColumns"
        border
        height="420"
        empty-text="没有未分配 AP"
      />
      <el-pagination
        v-if="unmatchedTotal > 50"
        :current-page="unmatchedPage"
        :page-size="50"
        :total="unmatchedTotal"
        layout="total, prev, pager, next"
        @current-change="loadUnmatchedDetails"
      />
    </el-dialog>

    <el-dialog v-model="excludedVisible" title="当前统计范围排除项" width="min(1040px, 94vw)">
      <NcDataTable
        v-loading="excludedLoading"
        table-id="rail-base-trackside-ap-scope-excluded"
        route-key="/rail-transit/base-data"
        :data="excludedItems"
        :columns="excludedColumns"
        border
        height="460"
        empty-text="没有排除项"
      />
      <el-pagination
        v-if="excludedTotal > 50"
        :current-page="excludedPage"
        :page-size="50"
        :total="excludedTotal"
        layout="total, prev, pager, next"
        @current-change="loadExcludedDetails"
      />
    </el-dialog>
    <el-dialog v-model="unmatchedVisible" title="待关联在线 AP" width="min(1280px, 96vw)">
      <NcDataTable
        v-loading="unmatchedLoading"
        table-id="rail-base-trackside-ap-unmatched-online"
        route-key="/rail-transit/base-data"
        :data="unmatchedItems"
        :columns="unmatchedColumns"
        border
        height="460"
        empty-text="没有待关联在线 AP"
      />
      <el-pagination
        v-if="unmatchedTotal > 50"
        :current-page="unmatchedPage"
        :page-size="50"
        :total="unmatchedTotal"
        layout="total, prev, pager, next"
        @current-change="loadUnmatchedDetails"
      />
    </el-dialog>
  </section>
</template>

<style scoped>
.planning-tab {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.plan-tabs {
  min-width: 0;
}

.local-request-error {
  margin-bottom: 12px;
}

.local-request-error details {
  display: grid;
  gap: 4px 12px;
  margin-top: 6px;
}

.local-request-error summary {
  cursor: pointer;
}

.local-request-error small {
  display: block;
  overflow-wrap: anywhere;
  color: var(--nc-text-secondary);
}

.toolbar,
.status-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
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

.table-shell {
  width: 100%;
  min-width: 0;
  overflow-x: auto;
}

.table-shell :deep(.nc-data-table) {
  width: 100%;
  min-width: 0;
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
