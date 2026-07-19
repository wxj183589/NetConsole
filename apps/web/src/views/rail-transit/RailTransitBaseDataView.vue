<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, UploadFilled } from '@element-plus/icons-vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'

import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import TracksideApPlanningTab from '../../components/rail-transit/base-data/TracksideApPlanningTab.vue'
import { useRailTransitBaseDataStore } from '../../stores/railTransitBaseData'
import type {
  DataQualityEntityGroup,
  DataQualityIssue,
  BaseDataChange,
  BaseDataValidationIssue,
  ImportChange,
  ImportOperation,
  MergeFieldDecision,
  MergeFieldDiff,
  MergePlanItem,
  Relation,
  Section,
  Station,
  TracksideAp,
  Train,
  VehicleMr,
} from '../../types/railTransitBaseData'
import type { TracksideApPlanRow } from '../../types/tracksideApBusiness'

const store = useRailTransitBaseDataStore()
const route = useRoute()
const router = useRouter()
const { confirm, confirmChoice } = useConfirm()
type BaseDataEditState = 'LOCKED' | 'UNLOCKED_CLEAN' | 'UNLOCKED_DIRTY' | 'VALIDATING' | 'SAVING' | 'SAVE_FAILED'
const editState = ref<BaseDataEditState>('LOCKED')
const pendingChanges = ref<Record<string, BaseDataChange>>({})
const baselines = new Map<string, Record<string, unknown>>()
const planningRows = ref<TracksideApPlanRow[]>([])
const planningDirty = ref(false)
const saveIssues = ref<BaseDataValidationIssue[]>([])
const planningTab = ref<{ reload: (force?: boolean) => Promise<boolean> } | null>(null)
const allowedTabs = new Set(['overview', 'stations', 'trackside-ap', 'trackside-ap-planning', 'trains', 'quality', 'import-preview', 'import-audit', 'relations'])
const activeTab = computed({
  get: () => allowedTabs.has(String(route.query.tab || '')) ? String(route.query.tab) : 'overview',
  set: (value: string) => { void router.replace({ query: { ...route.query, tab: value } }) },
})
const locked = computed(() => editState.value === 'LOCKED')
const saving = computed(() => editState.value === 'VALIDATING' || editState.value === 'SAVING')
const dirty = computed(() => Object.keys(pendingChanges.value).length > 0 || planningDirty.value)
const canUnlock = computed(() => Boolean(store.editSession?.can_write))
const locationTab = ref('stations')
const vehicleTab = ref('trains')
const previewFilter = ref('all')
const applyConfirmed = ref(false)
const decisionSelections = ref<Record<string, MergeFieldDecision['action'] | ''>>({})
const mergeRows = computed(() => {
  const rows = store.importPreview?.merge_plan?.items || []
  return previewFilter.value === 'all' ? rows : rows.filter((row) => row.result === previewFilter.value)
})
const previewBlocked = computed(() => {
  const summary = store.importPreview?.merge_plan?.summary
  return Boolean(summary && (summary.blocking_count > 0 || summary.conflict_count > 0))
})
const issueCodeStats = computed(() => Object.entries(store.issueCodeCounts).sort((left, right) => right[1] - left[1]))
const summaryCards = computed(() => [
  ['站点', store.summary?.station_count || 0, 'normal'],
  ['区间', store.summary?.section_count || 0, 'normal'],
  ['轨旁 AP', store.summary?.ap_count || 0, 'normal'],
  ['列车', store.summary?.train_count || 0, 'normal'],
  ['车载 MR', store.summary?.mr_count || 0, 'normal'],
  ['缺失位置 AP', store.summary?.missing_location_ap_count || 0, 'warning'],
  ['无效里程', store.summary?.invalid_mileage_count || 0, 'danger'],
  ['重复 AP MAC', store.summary?.duplicate_ap_mac_count || 0, 'danger'],
  ['重复静态 IP', store.summary?.duplicate_static_ip_count || 0, 'danger'],
  ['未关联列车 MR', store.summary?.unbound_mr_count || 0, 'warning'],
])

const stationColumns: NcTableColumn<Station>[] = [
  { key: 'sort_order', label: '顺序', valueType: 'number', width: 80 },
  { key: 'name', label: '站点名称', valueType: 'name', minWidth: 180 },
  { key: 'code', label: '站点编码', minWidth: 120, displayValue: (row) => display(row.code) },
  { key: 'line_name', label: '线路', minWidth: 130, displayValue: (row) => display(row.line_name) },
  { key: 'ap_count', label: 'AP 数量', valueType: 'number', width: 110 },
  { key: 'section_count', label: '关联区间', valueType: 'number', width: 110 },
  { key: 'mileage_range', label: '里程范围', valueType: 'mileage', minWidth: 160, displayValue: (row) => mileageRange(row.mileage_min, row.mileage_max) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, displayValue: (row) => display(row.remark), alignmentReason: 'long-text' },
]
const sectionColumns: NcTableColumn<Section>[] = [
  { key: 'name', label: '区间名称', valueType: 'name', minWidth: 200 },
  { key: 'start_station', label: '起始站', minWidth: 140, displayValue: (row) => display(row.start_station) },
  { key: 'end_station', label: '终点站', minWidth: 140, displayValue: (row) => display(row.end_station) },
  { key: 'line_side', label: '线路方向', minWidth: 120, displayValue: (row) => display(row.line_side) },
  { key: 'ap_count', label: 'AP 数量', valueType: 'number', width: 110 },
  { key: 'mileage_range', label: '里程范围', valueType: 'mileage', minWidth: 160, displayValue: (row) => mileageRange(row.mileage_min, row.mileage_max) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, displayValue: (row) => display(row.remark), alignmentReason: 'long-text' },
]
const apColumns: NcTableColumn<TracksideAp>[] = [
  { key: 'name', label: 'AP 名称 / 点位', valueType: 'name', minWidth: 170, fixed: 'left', displayValue: (row) => row.name || row.point_code || '--' },
  { key: 'point_code', label: '点位编号', minWidth: 120, displayValue: (row) => display(row.point_code) },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', minWidth: 150 },
  { key: 'management_ip', label: '管理 IP', valueType: 'ip', minWidth: 125, displayValue: (row) => display(row.management_ip) },
  { key: 'station', label: '站点', minWidth: 130, displayValue: (row) => display(row.station) },
  { key: 'section', label: '区间', minWidth: 170, displayValue: (row) => display(row.section) },
  { key: 'mileage', label: '里程', valueType: 'mileage', minWidth: 120, displayValue: (row) => row.mileage.normalized || row.mileage.raw || '--' },
  { key: 'line_side', label: '线路方向', width: 110, displayValue: (row) => display(row.line_side) },
  { key: 'direction', label: '行车方向', width: 110, displayValue: (row) => display(row.direction) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, alignmentReason: 'long-text', displayValue: (row) => display(row.remark) },
  { key: 'fit_ap_status', label: 'FIT-AP 状态', valueType: 'status', width: 120 },
  { key: 'mesh_related_name', label: '关联 MR', minWidth: 150 },
  { key: 'optical_status', label: '光衰', valueType: 'status', width: 105 },
  { key: 'source_file', label: '数据来源', align: 'left', alignmentReason: 'path', minWidth: 150, showOverflowTooltip: true },
  { key: 'issues', label: '问题', valueType: 'status', width: 90 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 240, fixed: 'right', hideable: false },
]
const trainColumns: NcTableColumn<Train>[] = [
  { key: 'train_no', label: '列车编号', minWidth: 120 },
  { key: 'name', label: '列车名称', valueType: 'name', minWidth: 150 },
  { key: 'mr_count', label: 'MR 数量', valueType: 'number', width: 100 },
  { key: 'roles', label: 'MR 角色', minWidth: 130, displayValue: (row) => row.roles.join(' / ') || '--' },
  { key: 'latest_mesh_status', label: '最近 Mesh-Link', valueType: 'status', width: 140 },
  { key: 'latest_session_id', label: '最近 Online MR', minWidth: 210, displayValue: (row) => display(row.latest_session_id) },
  { key: 'issues', label: '问题', valueType: 'number', width: 90, displayValue: (row) => row.issue_count || '--' },
]
const mrColumns: NcTableColumn<VehicleMr>[] = [
  { key: 'name', label: 'MR 名称', valueType: 'name', minWidth: 170 },
  { key: 'device_id', label: '设备 ID', valueType: 'number', width: 100 },
  { key: 'train_id', label: '所属列车', minWidth: 120 },
  { key: 'role', label: '角色', width: 80 },
  { key: 'management_ip', label: '管理 IP', valueType: 'ip', minWidth: 125 },
  { key: 'mac', label: 'MAC', valueType: 'mac', minWidth: 150, displayValue: (row) => display(row.mac) },
  { key: 'connection', label: '协议 / 端口', minWidth: 120, displayValue: (row) => `${display(row.protocol)} / ${display(row.port)}` },
  { key: 'mesh_status', label: 'Mesh-Link', valueType: 'status', width: 120 },
  { key: 'mesh_related_name', label: '当前轨旁 AP', minWidth: 160, displayValue: (row) => display(row.runtime.mesh_related_name) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, alignmentReason: 'long-text', displayValue: (row) => display(row.remark) },
  { key: 'actions', label: '跳转', valueType: 'actions', width: 190, hideable: false },
]
const issueGroupColumns: NcTableColumn<DataQualityEntityGroup>[] = [
  { key: 'expand', label: '', type: 'expand', width: 48, hideable: false },
  { key: 'status', label: '状态', valueType: 'status', width: 110 },
  { key: 'entity_type', label: '实体类型', width: 110 },
  { key: 'display_name', label: '实体', valueType: 'name', minWidth: 180 },
  { key: 'issue_count', label: '问题数', valueType: 'number', width: 90 },
  { key: 'counts', label: '错误 / 警告 / 提示', width: 160, displayValue: (row) => `${row.error_count} / ${row.warning_count} / ${row.info_count}` },
  { key: 'suggested_action', label: '建议处理', valueType: 'description', minWidth: 300, alignmentReason: 'long-text', showOverflowTooltip: true },
]
const issueColumns: NcTableColumn<DataQualityIssue>[] = [
  { key: 'field_name', label: '字段', minWidth: 150 },
  { key: 'message', label: '字段问题', valueType: 'error', minWidth: 260, alignmentReason: 'long-text' },
  { key: 'suggested_action', label: '建议处理', valueType: 'description', minWidth: 260, alignmentReason: 'long-text' },
]
const mergeColumns: NcTableColumn<MergePlanItem>[] = [
  { key: 'expand', label: '', type: 'expand', width: 48, hideable: false },
  { key: 'row_number', label: '行号', valueType: 'number', width: 80 },
  { key: 'result', label: '处理结果', valueType: 'status', width: 150 },
  { key: 'source_identity', label: '来源身份', minWidth: 210, displayValue: (row) => `${display(row.source_identity.ap_name)} / ${display(row.source_identity.ap_mac)}` },
  { key: 'matched_entity_name', label: '正式实体', valueType: 'name', minWidth: 170, displayValue: (row) => display(row.matched_entity_name) },
  { key: 'match_method', label: '匹配方式', width: 140 },
  { key: 'field_diffs', label: '字段差异', valueType: 'description', minWidth: 320, alignmentReason: 'long-text', displayValue: (row) => diffSummary(row.field_diffs), showOverflowTooltip: true },
  { key: 'conflict_summary', label: '冲突', valueType: 'error', minWidth: 240, alignmentReason: 'long-text', displayValue: (row) => display(row.conflict_summary) },
]
const mergeFieldColumns: NcTableColumn<MergeFieldDiff>[] = [
  { key: 'field_name', label: '字段', minWidth: 160 },
  { key: 'current_value', label: '当前值', align: 'left', alignmentReason: 'long-text', minWidth: 160, displayValue: (row) => display(row.current_value) },
  { key: 'proposed_value', label: '导入值', align: 'left', alignmentReason: 'long-text', minWidth: 160, displayValue: (row) => display(row.proposed_value) },
  { key: 'decision', label: '处置', valueType: 'actions', minWidth: 200, hideable: false },
]
const operationColumns: NcTableColumn<ImportOperation>[] = [
  { key: 'started_at', label: '开始时间', valueType: 'datetime', minWidth: 180 },
  { key: 'source_file_name', label: '来源文件', align: 'left', alignmentReason: 'path', minWidth: 180, showOverflowTooltip: true },
  { key: 'status', label: '状态', valueType: 'status', width: 120 },
  { key: 'counts', label: '新增 / 更新 / 跳过', width: 160, displayValue: (row) => `${row.created_count} / ${row.updated_count} / ${row.skipped_count}` },
  { key: 'owner', label: '操作者', width: 110 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 180, hideable: false },
]
const changeColumns: NcTableColumn<ImportChange>[] = [
  { key: 'entity_id', label: '实体', valueType: 'name', minWidth: 180 },
  { key: 'action', label: '动作', width: 100 },
  { key: 'field_name', label: '字段', width: 150 },
  { key: 'old_value', label: '原值', align: 'left', alignmentReason: 'long-text', minWidth: 160, displayValue: (row) => display(row.old_value) },
  { key: 'new_value', label: '新值', align: 'left', alignmentReason: 'long-text', minWidth: 160, displayValue: (row) => display(row.new_value) },
  { key: 'confirmation_method', label: '确认方式', width: 140 },
]
const relationColumns: NcTableColumn<Relation>[] = [
  { key: 'train_no', label: '列车', width: 100 },
  { key: 'mr_name', label: '车载 MR', valueType: 'name', minWidth: 170 },
  { key: 'ap_name', label: '当前轨旁 AP', valueType: 'name', minWidth: 180 },
  { key: 'station', label: '站点', minWidth: 140, displayValue: (row) => display(row.station) },
  { key: 'section', label: '区间', minWidth: 180, displayValue: (row) => display(row.section) },
  { key: 'status', label: '状态', valueType: 'status', width: 110 },
  { key: 'updated_at', label: '最近更新', valueType: 'datetime', minWidth: 180 },
]

const stationEditColumns: NcTableColumn<Station>[] = [
  ...stationColumns,
  { key: 'edit_actions', label: '操作', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]
const sectionEditColumns: NcTableColumn<Section>[] = [
  ...sectionColumns,
  { key: 'edit_actions', label: '操作', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]
const mrEditColumns: NcTableColumn<VehicleMr>[] = [
  ...mrColumns,
  { key: 'edit_actions', label: '维护', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  window.addEventListener('beforeunload', beforeUnload)
  store.startPolling()
  void store.refreshImportGovernance().catch(() => undefined)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  window.removeEventListener('beforeunload', beforeUnload)
  store.stopPolling()
})
onBeforeRouteLeave(async () => !dirty.value || confirmUnsavedChanges())

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else if (locked.value) store.startPolling()
}

function beforeUnload(event: BeforeUnloadEvent): void {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function toggleLock(): Promise<void> {
  if (locked.value) {
    try {
      const session = await loadConsistentEditSnapshot()
      if (!session.can_write) {
        store.startPolling()
        ElMessage.warning('当前局点基础资料写入未授权')
        return
      }
      captureBaselines()
      editState.value = 'UNLOCKED_CLEAN'
    } catch (cause) {
      editState.value = 'LOCKED'
      store.startPolling()
      ElMessage.error(message(cause, '基础资料编辑会话加载失败'))
    }
    return
  }
  if (dirty.value) await confirmUnsavedChanges()
  else lockClean()
}

async function loadConsistentEditSnapshot() {
  store.stopPolling()
  let before = await store.refreshEditSession()
  if (!before.can_write) return before
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await Promise.all([store.manualRefresh(), planningTab.value?.reload(true)])
    const after = await store.refreshEditSession()
    if (before.base_revision === after.base_revision) return after
    before = after
  }
  throw new Error('基础资料在加载期间持续变化，请稍后重试')
}

function lockClean(): void {
  editState.value = 'LOCKED'
  baselines.clear()
  store.startPolling()
}

async function confirmUnsavedChanges(): Promise<boolean> {
  const choice = await confirmChoice({
    type: 'WARNING',
    title: '存在未保存的修改',
    message: '当前基础资料存在尚未保存的修改。锁定或离开前请选择如何处理。',
    confirmText: '保存并锁定',
    secondaryText: '放弃修改并锁定',
    cancelText: '取消',
  })
  if (choice === 'cancel') return false
  if (choice === 'confirm') return saveAllChanges()
  await discardChanges()
  return true
}

async function discardChanges(): Promise<void> {
  pendingChanges.value = {}
  planningDirty.value = false
  saveIssues.value = []
  editState.value = 'LOCKED'
  baselines.clear()
  await Promise.all([
    store.manualRefresh(),
    store.refreshEditSession(),
    planningTab.value?.reload(true),
  ])
  store.startPolling()
}

async function refreshPage(): Promise<void> {
  if (dirty.value && !(await confirmUnsavedChanges())) return
  try {
    await Promise.all([
      store.manualRefresh(),
      store.refreshEditSession(),
      planningTab.value?.reload(true),
    ])
  } catch (cause) { ElMessage.error(message(cause, '基础资料刷新失败')) }
}

async function beforeTabLeave(next: string, current: string): Promise<boolean> {
  return next === current || !saving.value
}

async function saveAllChanges(): Promise<boolean> {
  if (!store.editSession || saving.value || !dirty.value) return !dirty.value
  const changes = Object.values(pendingChanges.value)
  if (planningDirty.value) {
    changes.push({ entity_type: 'trackside_ap_plan', action: 'replace', values: { rows: planningRows.value } })
  }
  editState.value = 'VALIDATING'
  saveIssues.value = []
  try {
    const validation = await store.validateChanges(changes)
    if (!validation.valid) {
      saveIssues.value = validation.issues
      editState.value = 'SAVE_FAILED'
      ElMessage.error(validation.issues[0]?.message || '基础资料校验失败')
      return false
    }
    editState.value = 'SAVING'
    const result = await store.saveChanges(changes)
    pendingChanges.value = {}
    planningDirty.value = false
    saveIssues.value = []
    baselines.clear()
    await Promise.all([store.manualRefresh(), planningTab.value?.reload(true)])
    editState.value = 'LOCKED'
    store.startPolling()
    ElMessage.success(`基础资料已保存：新增 ${result.created_count}，更新 ${result.updated_count}，删除 ${result.deleted_count}`)
    return true
  } catch (cause) {
    editState.value = 'SAVE_FAILED'
    ElMessage.error(message(cause, '基础资料保存失败，修改已保留'))
    return false
  }
}

function captureBaselines(): void {
  baselines.clear()
  for (const row of store.stations) baselines.set(changeKey('station', row.id), stationValues(row))
  for (const row of store.sections) baselines.set(changeKey('section', row.id), sectionValues(row))
  for (const row of store.aps) baselines.set(changeKey('trackside_ap', row.id), apValues(row))
  for (const row of store.mrs) baselines.set(changeKey('vehicle_mr', row.id), mrValues(row))
}

function handlePlanningChange(rows: TracksideApPlanRow[], changed: boolean): void {
  planningRows.value = rows
  planningDirty.value = changed
  updateEditState()
}

function markStation(row: Station): void { recordChange('station', row.id, stationValues(row)) }
function markSection(row: Section): void { recordChange('section', row.id, sectionValues(row)) }
function markAp(row: TracksideAp): void { recordChange('trackside_ap', row.id, apValues(row)) }
function markMr(row: VehicleMr): void { recordChange('vehicle_mr', row.id, mrValues(row)) }

function recordChange(entityType: BaseDataChange['entity_type'], entityId: string, values: Record<string, unknown>): void {
  if (locked.value) return
  const key = changeKey(entityType, entityId)
  const baseline = baselines.get(key)
  if (!baseline) {
    baselines.set(key, structuredClone(values))
    if (!entityId.startsWith('new:')) return
  }
  const action = entityId.startsWith('new:') ? 'create' : 'update'
  const payload = action === 'update' ? withOriginalIdentity(entityType, values, baselines.get(key) || {}) : values
  if (action === 'update' && JSON.stringify(values) === JSON.stringify(baselines.get(key))) delete pendingChanges.value[key]
  else pendingChanges.value[key] = { entity_type: entityType, action, entity_id: entityId, values: payload }
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

async function deleteEntity(entityType: BaseDataChange['entity_type'], row: Station | Section | TracksideAp | VehicleMr): Promise<void> {
  if (locked.value) return
  const accepted = await confirm({ type: 'DANGER', title: '标记删除', message: '该数据将在点击“保存”后删除；存在业务引用时后端会拒绝。是否继续？', confirmText: '标记删除' })
  if (!accepted) return
  const key = changeKey(entityType, row.id)
  if (row.id.startsWith('new:')) {
    delete pendingChanges.value[key]
  } else {
    const baseline = baselines.get(key) || valuesFor(entityType, row)
    pendingChanges.value[key] = { entity_type: entityType, action: 'delete', entity_id: row.id, values: withOriginalIdentity(entityType, baseline, baseline) }
  }
  if (entityType === 'station') store.stations = store.stations.filter((item) => item.id !== row.id)
  else if (entityType === 'section') store.sections = store.sections.filter((item) => item.id !== row.id)
  else if (entityType === 'trackside_ap') store.aps = store.aps.filter((item) => item.id !== row.id)
  else store.mrs = store.mrs.filter((item) => item.id !== row.id)
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function addStation(): void {
  const row: Station = { id: temporaryId(), name: '', code: '', line_name: store.summary?.line_name || '', sort_order: store.stations.length + 1, ap_count: 0, section_count: 0, mileage_min: null, mileage_max: null, remark: '' }
  store.stations.push(row); markStation(row)
}
function addSection(): void {
  const row: Section = { id: temporaryId(), name: '', start_station: '', end_station: '', line_side: '', ap_count: 0, mileage_min: null, mileage_max: null, remark: '' }
  store.sections.push(row); markSection(row)
}
function addAp(): void {
  const row: TracksideAp = { id: temporaryId(), site_id: store.editSession?.site_id || '', line_name: store.summary?.line_name || '', name: '', point_code: '', mac: '', management_ip: '', model: '', station: '', section: '', section_start_station: '', section_end_station: '', mileage: { raw: '', normalized: '', meters: null, line_type: '', valid: false, error: '' }, line_side: '', direction: '', radios: [], remark: '', source_file: '', source_sheet: '', source_row: null, updated_at: '', runtime: emptyRuntime(), issue_count: 0, highest_issue_severity: '', record_kind: 'manual', base_metadata: {} }
  store.aps.push(row); markAp(row)
}
function addMr(): void {
  const row: VehicleMr = { id: temporaryId(), device_id: null, name: '', train_id: '', train_no: '', role: '', management_ip: '', station: '', mac: '', protocol: 'SSH', port: 22, remark: '', runtime: emptyRuntime(), issue_count: 0, highest_issue_severity: '' }
  store.mrs.push(row); markMr(row)
}

function updateEditState(): void {
  if (!locked.value && !saving.value) editState.value = dirty.value ? 'UNLOCKED_DIRTY' : 'UNLOCKED_CLEAN'
}
function changeKey(type: string, id: string): string { return `${type}:${id}` }
function temporaryId(): string { return `new:${Date.now()}:${Math.random().toString(16).slice(2)}` }
function stationValues(row: Station): Record<string, unknown> { return { name: row.name, code: row.code, line_name: row.line_name, sort_order: row.sort_order, remark: row.remark } }
function sectionValues(row: Section): Record<string, unknown> { return { name: row.name, start_station: row.start_station, end_station: row.end_station, line_side: row.line_side, remark: row.remark } }
function apValues(row: TracksideAp): Record<string, unknown> { return { line_name: row.line_name, name: row.name, point_code: row.point_code, mac: row.mac, station: row.station, section: row.section, section_start_station: row.section_start_station, section_end_station: row.section_end_station, mileage: row.mileage.raw, line_side: row.line_side, direction: row.direction, remark: row.remark } }
function mrValues(row: VehicleMr): Record<string, unknown> { return { name: row.name, station: row.station, management_ip: row.management_ip, mac: row.mac, protocol: row.protocol, port: row.port, remark: row.remark } }
function valuesFor(type: BaseDataChange['entity_type'], row: Station | Section | TracksideAp | VehicleMr): Record<string, unknown> {
  if (type === 'station') return stationValues(row as Station)
  if (type === 'section') return sectionValues(row as Section)
  if (type === 'trackside_ap') return apValues(row as TracksideAp)
  return mrValues(row as VehicleMr)
}
function withOriginalIdentity(type: BaseDataChange['entity_type'], values: Record<string, unknown>, baseline: Record<string, unknown>): Record<string, unknown> {
  if (type === 'station') return { ...values, old_name: baseline.name }
  if (type === 'section') return { ...values, old_name: baseline.name, old_start_station: baseline.start_station, old_end_station: baseline.end_station, old_line_side: baseline.line_side }
  return values
}
function emptyRuntime() { return { fit_ap_status: 'unknown', optical_status: 'no_data', mesh_status: 'unknown', mesh_related_name: '', latest_session_id: '', latest_session_status: '', updated_at: '' } }
function message(cause: unknown, fallback: string): string { return cause instanceof Error && cause.message ? cause.message : fallback }

async function handleFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    await store.previewImport(file)
    applyConfirmed.value = false
    decisionSelections.value = {}
    ElMessage.success('导入预览解析完成，未写入数据库')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '导入预览失败')
  } finally {
    input.value = ''
  }
}

function decisionKey(rowNumber: number, fieldName: string): string { return `${rowNumber}:${fieldName}` }
function manualDecisions(): MergeFieldDecision[] {
  const result: MergeFieldDecision[] = []
  for (const item of store.importPreview?.merge_plan?.items || []) {
    for (const diff of item.field_diffs) {
      if (diff.action !== 'manual_review') continue
      const action = decisionSelections.value[decisionKey(item.row_number, diff.field_name)]
      if (!action) throw new Error(`第 ${item.row_number} 行字段 ${diff.field_name} 尚未确认`)
      result.push({ row_number: item.row_number, field_name: diff.field_name, action })
    }
  }
  return result
}

async function handleApply(): Promise<void> {
  if (!applyConfirmed.value || locked.value) return
  try {
    const operationId = await store.applyImport(manualDecisions())
    applyConfirmed.value = false
    await store.manualRefresh()
    ElMessage.success(`基础资料已应用，操作号：${operationId}`)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '基础资料应用失败')
  }
}

async function handleRollback(operationId: string): Promise<void> {
  try {
    if (!await confirm({ type: 'DESTRUCTIVE', title: '回滚确认', message: '仅当数据库未发生后续变化时才能回滚。确认回滚该次导入？', confirmText: '确认回滚' })) return
    await store.rollbackImport(operationId)
    await store.manualRefresh()
    ElMessage.success('导入操作已回滚')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '回滚失败')
  }
}

function openApAc(ap: TracksideAp): void {
  router.push({ path: '/ac-management', query: { ap: ap.runtime.fit_ap_status !== 'unknown' ? ap.name : undefined } })
}
function openApMesh(ap: TracksideAp): void {
  router.push({ path: '/rail-transit/train-online', query: { query: ap.name } })
}
function openMrMesh(mr: VehicleMr): void {
  router.push({ path: '/rail-transit/train-online', query: { query: mr.name } })
}
function openMrSession(mr: VehicleMr): void {
  router.push({ path: '/rail-transit/online-mr', query: { session_id: mr.runtime.latest_session_id || undefined, device_id: mr.id } })
}
function issueType(value: string): 'danger' | 'warning' | 'info' {
  return value === 'error' ? 'danger' : value === 'warning' ? 'warning' : 'info'
}
function mergeType(value: string): 'success' | 'danger' | 'warning' | 'info' {
  if (value === 'CREATE' || value === 'UPDATE') return 'success'
  if (value === 'CONFLICT') return 'danger'
  if (value === 'NEEDS_CONFIRMATION') return 'warning'
  return 'info'
}
function diffSummary(diffs: Array<{ field_name: string; action: string }>): string {
  return diffs.map((item) => `${item.field_name}: ${item.action}`).join('；') || '--'
}
function stateType(value: string): 'success' | 'danger' | 'warning' | 'info' {
  if (['online', 'normal', 'fresh'].includes(value)) return 'success'
  if (['offline', 'critical', 'error'].includes(value)) return 'danger'
  if (['stale', 'warning', 'unauthenticated'].includes(value)) return 'warning'
  return 'info'
}
function display(value: unknown): string { return value === null || value === undefined || value === '' ? '--' : String(value) }
function mileageRange(minimum: number | null, maximum: number | null): string {
  if (minimum === null && maximum === null) return '--'
  if (minimum === maximum || maximum === null) return `${minimum} m`
  return `${minimum}–${maximum} m`
}
function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}
</script>

<template>
  <section class="rail-base-data" v-loading="store.loading">
    <el-alert
      title="轨道交通基础资料"
      :description="locked ? '当前处于锁定状态，数据仅可查看。点击“解锁”后可编辑。' : '当前处于编辑状态。修改不会自动生效，请点击“保存”提交。'"
      :type="locked ? 'info' : 'warning'"
      :closable="false"
      show-icon
    />

    <div class="page-toolbar">
      <div>
        <h2>轨道交通基础资料</h2>
        <p>统一维护站点、区间、轨旁 AP、AP 规划、列车和车载 MR 等基础数据。</p>
        <p>{{ store.summary?.site_name || '当前局点' }} · {{ store.summary?.line_name || '线路未填写' }} · {{ store.summary?.project_type || '项目类型未填写' }}</p>
      </div>
      <div class="toolbar-actions">
        <el-tag v-if="dirty" type="warning">未保存修改</el-tag>
        <el-button :icon="Refresh" :loading="store.loading" :disabled="saving" @click="refreshPage">刷新</el-button>
        <el-button :type="locked ? 'primary' : 'warning'" :disabled="saving || (locked && !canUnlock)" @click="toggleLock">{{ locked ? '解锁' : '锁定' }}</el-button>
        <el-button type="primary" :loading="saving" :disabled="locked || !dirty" @click="saveAllChanges">保存</el-button>
      </div>
    </div>
    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />
    <el-alert v-if="saveIssues.length" title="基础资料校验失败" type="error" :closable="false" show-icon class="page-error">
      <ul class="validation-list"><li v-for="issue in saveIssues" :key="`${issue.change_index}:${issue.code}:${issue.field_name}`">{{ issue.message }}</li></ul>
    </el-alert>

    <div class="content-card">
      <el-tabs v-model="activeTab" :before-leave="beforeTabLeave">
        <el-tab-pane label="基础资料总览" name="overview">
          <div class="summary-grid">
            <article v-for="card in summaryCards" :key="String(card[0])" :class="String(card[2])">
              <span>{{ card[0] }}</span><strong>{{ card[1] }}</strong>
            </article>
          </div>
          <el-descriptions :column="3" border class="meta-block">
            <el-descriptions-item label="局点 ID">{{ store.summary?.site_id || '--' }}</el-descriptions-item>
            <el-descriptions-item label="网络类型">{{ store.summary?.network_type || '--' }}</el-descriptions-item>
            <el-descriptions-item label="数据更新时间">{{ store.summary?.updated_at || '--' }}</el-descriptions-item>
            <el-descriptions-item label="说明" :span="3">{{ store.summary?.message || '--' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <el-tab-pane label="站点与区间" name="stations">
          <el-tabs v-model="locationTab" type="card">
            <el-tab-pane label="站点" name="stations">
              <div class="edit-toolbar"><el-button :disabled="locked || saving" @click="addStation">新增站点</el-button></div>
              <NcDataTable table-id="rail-base-stations" route-key="/rail-transit/base-data" :data="store.stations" :columns="stationEditColumns" height="calc(100vh - 410px)" empty-text="暂无站点资料">
                <template #cell-sort_order="{ row }"><el-input-number v-if="!locked" v-model="row.sort_order" :min="0" controls-position="right" @change="markStation(row)" /><span v-else>{{ row.sort_order }}</span></template>
                <template #cell-name="{ row }"><el-input v-if="!locked" v-model="row.name" @input="markStation(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-code="{ row }"><el-input v-if="!locked" v-model="row.code" @input="markStation(row)" /><span v-else>{{ display(row.code) }}</span></template>
                <template #cell-line_name="{ row }"><el-input v-if="!locked" v-model="row.line_name" @input="markStation(row)" /><span v-else>{{ display(row.line_name) }}</span></template>
                <template #cell-remark="{ row }"><el-input v-if="!locked" v-model="row.remark" @input="markStation(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-button link type="danger" :disabled="locked" @click="deleteEntity('station', row)">删除</el-button></template>
              </NcDataTable>
            </el-tab-pane>
            <el-tab-pane label="区间" name="sections">
              <div class="edit-toolbar"><el-button :disabled="locked || saving" @click="addSection">新增区间</el-button></div>
              <NcDataTable table-id="rail-base-sections" route-key="/rail-transit/base-data" :data="store.sections" :columns="sectionEditColumns" height="calc(100vh - 410px)" empty-text="暂无区间资料">
                <template #cell-name="{ row }"><el-input v-if="!locked" v-model="row.name" @input="markSection(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-start_station="{ row }"><el-input v-if="!locked" v-model="row.start_station" @input="markSection(row)" /><span v-else>{{ display(row.start_station) }}</span></template>
                <template #cell-end_station="{ row }"><el-input v-if="!locked" v-model="row.end_station" @input="markSection(row)" /><span v-else>{{ display(row.end_station) }}</span></template>
                <template #cell-line_side="{ row }"><el-input v-if="!locked" v-model="row.line_side" @input="markSection(row)" /><span v-else>{{ display(row.line_side) }}</span></template>
                <template #cell-remark="{ row }"><el-input v-if="!locked" v-model="row.remark" @input="markSection(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-button link type="danger" :disabled="locked" @click="deleteEntity('section', row)">删除</el-button></template>
              </NcDataTable>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP" name="trackside-ap">
          <div class="filter-bar">
            <el-input v-model="store.apFilters.query" clearable placeholder="AP 名称 / 点位 / MAC / IP" @keyup.enter="store.applyApFilters" />
            <el-input v-model="store.apFilters.station" clearable placeholder="归属站点" />
            <el-input v-model="store.apFilters.section" clearable placeholder="归属区间" />
            <el-select v-model="store.apFilters.line_side" clearable placeholder="线路方向"><el-option label="左线" value="左线" /><el-option label="右线" value="右线" /><el-option label="出段线" value="出段线" /><el-option label="入段线" value="入段线" /></el-select>
            <el-select v-model="store.apFilters.has_issue" clearable placeholder="数据质量"><el-option label="只看异常" :value="true" /><el-option label="只看正常" :value="false" /></el-select>
            <el-button type="primary" :disabled="!locked" @click="store.applyApFilters">应用筛选</el-button>
            <el-button :disabled="locked || saving" @click="addAp">新增轨旁 AP</el-button>
          </div>
          <NcDataTable table-id="rail-base-trackside-aps" route-key="/rail-transit/base-data" :data="store.aps" :columns="apColumns" height="calc(100vh - 430px)" empty-text="暂无轨旁 AP 扩展资料">
            <template #cell-name="{ row }"><el-input v-if="!locked" v-model="row.name" @input="markAp(row)" /><span v-else>{{ row.name || row.point_code || '--' }}</span></template>
            <template #cell-point_code="{ row }"><el-input v-if="!locked" v-model="row.point_code" @input="markAp(row)" /><span v-else>{{ display(row.point_code) }}</span></template>
            <template #cell-mac="{ row }"><el-input v-if="!locked" v-model="row.mac" @input="markAp(row)" /><span v-else>{{ display(row.mac) }}</span></template>
            <template #cell-station="{ row }"><el-input v-if="!locked" v-model="row.station" @input="markAp(row)" /><span v-else>{{ display(row.station) }}</span></template>
            <template #cell-section="{ row }"><el-input v-if="!locked" v-model="row.section" @input="markAp(row)" /><span v-else>{{ display(row.section) }}</span></template>
            <template #cell-mileage="{ row }"><el-input v-if="!locked" v-model="row.mileage.raw" @input="markAp(row)" /><span v-else>{{ row.mileage.normalized || row.mileage.raw || '--' }}</span></template>
            <template #cell-line_side="{ row }"><el-input v-if="!locked" v-model="row.line_side" @input="markAp(row)" /><span v-else>{{ display(row.line_side) }}</span></template>
            <template #cell-direction="{ row }"><el-input v-if="!locked" v-model="row.direction" @input="markAp(row)" /><span v-else>{{ display(row.direction) }}</span></template>
            <template #cell-remark="{ row }"><el-input v-if="!locked" v-model="row.remark" @input="markAp(row)" /><span v-else>{{ display(row.remark) }}</span></template>
            <template #cell-fit_ap_status="{ row }"><el-tag :type="stateType(row.runtime.fit_ap_status)">{{ row.runtime.fit_ap_status }}</el-tag></template>
            <template #cell-mesh_related_name="{ row }">{{ display(row.runtime.mesh_related_name) }}</template>
            <template #cell-optical_status="{ row }"><el-tag :type="stateType(row.runtime.optical_status)">{{ row.runtime.optical_status }}</el-tag></template>
            <template #cell-issues="{ row }"><el-tag v-if="row.issue_count" :type="issueType(row.highest_issue_severity)">{{ row.issue_count }}</el-tag><span v-else>--</span></template>
            <template #cell-actions="{ row }"><el-button link type="primary" @click="openApAc(row)">FIT-AP</el-button><el-button link type="primary" @click="openApMesh(row)">Mesh-Link</el-button><el-button v-if="!locked" link type="danger" @click="deleteEntity('trackside_ap', row)">删除</el-button></template>
          </NcDataTable>
          <el-pagination background :disabled="!locked" layout="total, prev, pager, next, sizes" :total="store.apTotal" :current-page="store.apFilters.page" :page-size="store.apFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setApPage" @size-change="(size: number) => { store.apFilters.page_size = size; store.applyApFilters() }" />
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP 规划" name="trackside-ap-planning">
          <TracksideApPlanningTab ref="planningTab" :locked="locked" :saving="saving" @change="handlePlanningChange" />
        </el-tab-pane>

        <el-tab-pane label="列车与车载 MR" name="trains">
          <el-tabs v-model="vehicleTab" type="card">
            <el-tab-pane label="列车" name="trains">
              <NcDataTable table-id="rail-base-trains" route-key="/rail-transit/base-data" :data="store.trains" :columns="trainColumns" height="calc(100vh - 365px)" empty-text="暂无列车资料">
                <template #cell-latest_mesh_status="{ row }"><el-tag :type="stateType(row.latest_mesh_status)">{{ row.latest_mesh_status }}</el-tag></template>
              </NcDataTable>
            </el-tab-pane>
            <el-tab-pane label="车载 MR" name="mrs">
              <div class="filter-bar">
                <el-input v-model="store.mrFilters.query" clearable placeholder="MR 名称 / IP / MAC / 设备 ID" @keyup.enter="store.applyMrFilters" />
                <el-input v-model="store.mrFilters.train" clearable placeholder="列车编号" />
                <el-select v-model="store.mrFilters.mr_role" clearable placeholder="MR 角色"><el-option label="CT" value="CT" /><el-option label="TC" value="TC" /></el-select>
                <el-button type="primary" :disabled="!locked" @click="store.applyMrFilters">应用筛选</el-button>
                <el-button :disabled="locked || saving" @click="addMr">新增车载 MR</el-button>
              </div>
              <NcDataTable table-id="rail-base-vehicle-mrs" route-key="/rail-transit/base-data" :data="store.mrs" :columns="mrEditColumns" height="calc(100vh - 430px)" empty-text="暂无车载 MR 资料">
                <template #cell-name="{ row }"><el-input v-if="!locked" v-model="row.name" @input="markMr(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-management_ip="{ row }"><el-input v-if="!locked" v-model="row.management_ip" @input="markMr(row)" /><span v-else>{{ display(row.management_ip) }}</span></template>
                <template #cell-mac="{ row }"><el-input v-if="!locked" v-model="row.mac" @input="markMr(row)" /><span v-else>{{ display(row.mac) }}</span></template>
                <template #cell-connection="{ row }"><div v-if="!locked" class="connection-editor"><el-select v-model="row.protocol" @change="markMr(row)"><el-option label="SSH" value="SSH" /><el-option label="Telnet" value="TELNET" /></el-select><el-input-number v-model="row.port" :min="1" :max="65535" controls-position="right" @change="markMr(row)" /></div><span v-else>{{ display(row.protocol) }} / {{ display(row.port) }}</span></template>
                <template #cell-remark="{ row }"><el-input v-if="!locked" v-model="row.remark" @input="markMr(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-mesh_status="{ row }"><el-tag :type="stateType(row.runtime.mesh_status)">{{ row.runtime.mesh_status }}</el-tag></template>
                <template #cell-actions="{ row }"><el-button link type="primary" @click="openMrMesh(row)">Mesh-Link</el-button><el-button link type="primary" @click="openMrSession(row)">Online MR</el-button></template>
                <template #cell-edit_actions="{ row }"><el-button link type="danger" :disabled="locked" @click="deleteEntity('vehicle_mr', row)">删除</el-button></template>
              </NcDataTable>
              <el-pagination background :disabled="!locked" layout="total, prev, pager, next, sizes" :total="store.mrTotal" :current-page="store.mrFilters.page" :page-size="store.mrFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setMrPage" @size-change="(size: number) => { store.mrFilters.page_size = size; store.applyMrFilters() }" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="数据质量问题" name="quality">
          <div class="filter-bar">
            <el-input v-model="store.issueFilters.query" clearable placeholder="实体 / 错误码 / 说明" @keyup.enter="store.applyIssueFilters" />
            <el-select v-model="store.issueFilters.blocking_only" clearable placeholder="阻断状态"><el-option label="只看阻断问题" :value="true" /><el-option label="排除阻断问题" :value="false" /></el-select>
            <el-select v-model="store.issueFilters.needs_confirmation_only" clearable placeholder="人工确认"><el-option label="只看待人工确认" :value="true" /><el-option label="无需人工确认" :value="false" /></el-select>
            <el-button type="primary" @click="store.applyIssueFilters">应用筛选</el-button>
          </div>
          <div class="issue-stats">
            <el-tag v-for="item in issueCodeStats" :key="item[0]" type="info">{{ item[0] }}：{{ item[1] }}</el-tag>
          </div>
          <NcDataTable table-id="rail-base-quality-groups" route-key="/rail-transit/base-data" :data="store.issueGroups" :columns="issueGroupColumns" height="calc(100vh - 460px)" empty-text="当前没有数据质量问题">
            <template #cell-expand="{ row }"><NcDataTable table-id="rail-base-quality-issues" route-key="/rail-transit/base-data" :preference-scope="row.entity_id" :data="row.issues" :columns="issueColumns" compact :show-column-settings="false" /></template>
            <template #cell-status="{ row }"><el-tag v-if="row.blocking" type="danger">阻断</el-tag><el-tag v-else-if="row.needs_confirmation" type="warning">待确认</el-tag><el-tag v-else type="info">提示</el-tag></template>
          </NcDataTable>
          <el-pagination background layout="total, prev, pager, next" :total="store.issueGroupTotal" :current-page="store.issueFilters.page" :page-size="store.issueFilters.page_size" @current-change="store.setIssuePage" />
        </el-tab-pane>

        <el-tab-pane label="导入预览" name="import-preview">
          <el-alert title="基础资料写入默认关闭" description="支持 XLSX、CSV、JSON；原文件不会保存在运行目录。只有明确授权的范围可以应用，正式身份和运行态字段不会被自动覆盖。" type="warning" :closable="false" show-icon />
          <div class="preview-toolbar">
            <label class="file-picker"><el-icon><UploadFilled /></el-icon><span>{{ store.selectedFileName || '选择预览文件' }}</span><input type="file" accept=".xlsx,.csv,.json" @change="handleFile" /></label>
            <span v-if="store.importPreview">{{ formatBytes(store.importPreview.file_size) }} · {{ store.importPreview.template_type }} · 置信度 {{ store.importPreview.confidence_score }}</span>
          </div>
          <div v-if="store.importPreview" class="preview-summary">
            <article><span>解析行数</span><strong>{{ store.importPreview.total_rows }}</strong></article>
            <article class="normal"><span>有效行</span><strong>{{ store.importPreview.valid_rows }}</strong></article>
            <article class="danger"><span>错误</span><strong>{{ store.importPreview.error_count }}</strong></article>
            <article class="warning"><span>警告</span><strong>{{ store.importPreview.warning_count }}</strong></article>
          </div>
          <div v-if="store.importPreview" class="preview-actions">
            <el-radio-group v-model="previewFilter" class="preview-filter"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="CREATE">CREATE</el-radio-button><el-radio-button value="UPDATE">UPDATE</el-radio-button><el-radio-button value="UNCHANGED">UNCHANGED</el-radio-button><el-radio-button value="CONFLICT">CONFLICT</el-radio-button><el-radio-button value="NEEDS_CONFIRMATION">待人工确认</el-radio-button></el-radio-group>
            <div v-if="store.canApplyImport() && !locked" class="apply-controls">
              <el-checkbox v-model="applyConfirmed">我已核对差异、冲突和目标局点</el-checkbox>
              <el-button type="primary" :loading="store.applyLoading" :disabled="!applyConfirmed || previewBlocked" @click="handleApply">应用导入</el-button>
            </div>
            <el-tag v-else type="info">{{ store.canApplyImport() ? '解锁后可应用' : '写入未授权，仅可预览' }}</el-tag>
          </div>
          <NcDataTable v-loading="store.previewLoading" table-id="rail-base-merge-plan" route-key="/rail-transit/base-data" :data="mergeRows" :columns="mergeColumns" height="calc(100vh - 520px)" empty-text="请选择文件生成合并预览">
            <template #cell-expand="{ row }">
              <NcDataTable table-id="rail-base-merge-field-diffs" route-key="/rail-transit/base-data" :preference-scope="String(row.row_number)" :data="row.field_diffs" :columns="mergeFieldColumns" compact :show-column-settings="false">
                <template #cell-decision="{ row: field }">
                  <el-select v-if="field.action === 'manual_review'" v-model="decisionSelections[decisionKey(row.row_number, field.field_name)]" placeholder="请选择">
                    <el-option label="保留正式值" value="keep_existing" />
                    <el-option label="采用导入值" value="use_imported" />
                  </el-select>
                  <span v-else>{{ field.action }}</span>
                </template>
              </NcDataTable>
            </template>
            <template #cell-result="{ row }"><el-tag :type="mergeType(row.result)">{{ row.result }}</el-tag></template>
          </NcDataTable>
        </el-tab-pane>

        <el-tab-pane label="导入审计" name="import-audit">
          <el-alert title="审计记录只保存文件摘要、字段差异和操作结果，不保存上传原文件。" type="info" :closable="false" show-icon />
          <NcDataTable table-id="rail-base-import-operations" route-key="/rail-transit/base-data" :data="store.importOperations" :columns="operationColumns" class="operation-table" empty-text="暂无导入操作">
            <template #cell-actions="{ row }">
                <el-button link type="primary" @click="store.selectImportOperation(row.operation_id)">查看变更</el-button>
                <el-button
                  v-if="!locked && store.importPolicies?.rollback_enabled && store.canApplyImport() && row.status === 'APPLIED'"
                  link type="danger" @click="handleRollback(row.operation_id)"
                >回滚</el-button>
            </template>
          </NcDataTable>
          <NcDataTable v-if="store.selectedOperationId" table-id="rail-base-import-changes" route-key="/rail-transit/base-data" :preference-scope="store.selectedOperationId" :data="store.importChanges" :columns="changeColumns" class="change-table" empty-text="该操作没有字段变更" />
        </el-tab-pane>

        <el-tab-pane label="关联运行状态" name="relations">
          <NcDataTable table-id="rail-base-relations" route-key="/rail-transit/base-data" :data="store.relations" :columns="relationColumns" height="calc(100vh - 330px)" empty-text="暂无 Mesh-Link 关联快照">
            <template #cell-status="{ row }"><el-tag :type="stateType(row.status)">{{ row.status }}</el-tag></template>
          </NcDataTable>
        </el-tab-pane>
      </el-tabs>
    </div>
  </section>
</template>

<style scoped>
.rail-base-data { max-width: 1760px; margin: 0 auto; }
.page-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 18px 0; }
.toolbar-actions, .edit-toolbar, .connection-editor { display: flex; align-items: center; gap: 10px; }
.toolbar-actions { flex-wrap: wrap; justify-content: flex-end; }
.edit-toolbar { justify-content: flex-end; margin: 8px 0 12px; }
.connection-editor .el-select { width: 92px; }
.connection-editor .el-input-number { width: 120px; }
.page-toolbar h2 { margin: 0; color: var(--nc-text-primary); }
.page-toolbar p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.page-error { margin-bottom: 14px; }
.validation-list { margin: 6px 0 0; padding-left: 20px; }
.content-card { min-width: 0; padding: 0 18px 18px; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 10px; }
.summary-grid, .preview-summary { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 12px; margin: 8px 0 18px; }
.summary-grid article, .preview-summary article { min-height: 86px; padding: 14px 16px; background: var(--nc-bg-muted); border-left: 3px solid var(--nc-border-strong); border-radius: 8px; }
.summary-grid article.normal, .preview-summary article.normal { border-left-color: var(--nc-success); }
.summary-grid article.warning, .preview-summary article.warning { border-left-color: var(--nc-warning); }
.summary-grid article.danger, .preview-summary article.danger { border-left-color: var(--nc-danger); }
.summary-grid span, .preview-summary span { display: block; color: var(--nc-text-secondary); font-size: 12px; }
.summary-grid strong, .preview-summary strong { display: block; margin-top: 8px; color: var(--nc-text-primary); font-size: 25px; }
.meta-block { margin-top: 12px; }
.filter-bar { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)) auto; gap: 10px; margin: 8px 0 14px; }
.el-pagination { justify-content: flex-end; margin-top: 14px; }
.preview-toolbar { display: flex; align-items: center; gap: 16px; margin: 16px 0; color: var(--nc-text-secondary); font-size: 12px; }
.file-picker { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; color: var(--nc-text-inverse); background: var(--nc-primary); border-radius: 6px; cursor: pointer; }
.file-picker input { display: none; }
.preview-summary { grid-template-columns: repeat(4, minmax(140px, 1fr)); }
.preview-filter { margin-bottom: 12px; }
.preview-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.apply-controls { display: flex; align-items: center; gap: 12px; }
.operation-table, .change-table { margin-top: 16px; }
.issue-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.row-issues { display: flex; flex-wrap: wrap; gap: 5px; }
@media (max-width: 1360px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .filter-bar { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 900px) {
  .page-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { justify-content: flex-start; }
}
</style>
