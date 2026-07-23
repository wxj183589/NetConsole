<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, toRaw } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'
import { downloadBackendResource } from '../../platform/runtime'
import { stationTemplateDownloadRequest, stationTemplateExportDownloadRequest } from '../../api/railTransitBaseData'

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
  RailTransitSummary,
  Section,
  Station,
  StationSourceCandidate,
  StationTemplatePreviewRow,
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
interface BaseDataDraft {
  metadata: {
    line_name: string
    system_type: string
    network_domain: string
    main_path_code: string
    increasing_direction_name: string
    decreasing_direction_name: string
    increasing_direction_leading_end: 'car_1_end' | 'car_6_end' | 'unknown'
    station_source_group_name: string
    station_source_field: string
    remark: string
  }
  stations: Station[]
  sections: Section[]
  aps: TracksideAp[]
  mrs: VehicleMr[]
}
const editState = ref<BaseDataEditState>('LOCKED')
const pendingChanges = ref<Record<string, BaseDataChange>>({})
const baselines = new Map<string, Record<string, unknown>>()
const serverSnapshot = ref<BaseDataDraft | null>(null)
const editingDraft = ref<BaseDataDraft | null>(null)
const planningRows = ref<TracksideApPlanRow[]>([])
const planningDirty = ref(false)
const saveIssues = ref<BaseDataValidationIssue[]>([])
const fieldErrors = ref<Record<string, string>>({})
const planningTab = ref<{ reload: (force?: boolean) => Promise<boolean> } | null>(null)
const allowedTabs = new Set(['overview', 'stations', 'trackside-ap', 'trackside-ap-planning', 'trains', 'quality', 'import-preview', 'import-audit', 'relations'])
const activeTab = computed({
  get: () => allowedTabs.has(String(route.query.tab || '')) ? String(route.query.tab) : 'overview',
  set: (value: string) => { void router.replace({ query: { ...route.query, tab: value } }) },
})
const locked = computed(() => editState.value === 'LOCKED')
const saving = computed(() => editState.value === 'VALIDATING' || editState.value === 'SAVING')
const editing = computed(() => !locked.value)
const stationRows = computed(() => editingDraft.value?.stations ?? store.stations)
const sectionRows = computed(() => editingDraft.value?.sections ?? store.sections)
const apRows = computed(() => editingDraft.value?.aps ?? store.aps)
const mrRows = computed(() => editingDraft.value?.mrs ?? store.mrs)
const dirty = computed(() => Object.keys(pendingChanges.value).length > 0 || planningDirty.value)
const canUnlock = computed(() => Boolean(store.editSession?.can_write))
const writeDeniedReason = computed(() => store.editSession?.write_denial_reason || '')
const locationTab = ref('stations')
const vehicleTab = ref('trains')
const previewFilter = ref('all')
const stationSourceDialogVisible = ref(false)
const stationTemplateDialogVisible = ref(false)
const selectedStationSourceIds = ref<string[]>([])
const selectedTemplateRows = ref<number[]>([])
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
const stationSourceCandidates = computed(() => store.stationSourcePreview?.candidates || [])
const stationTemplateRows = computed(() => store.stationTemplatePreview?.rows || [])
const issueCodeStats = computed(() => Object.entries(store.issueCodeCounts).sort((left, right) => right[1] - left[1]))
const summaryCards = computed(() => [
  ['站点', store.summary?.station_count || 0, 'normal'],
  ['普通车站', store.summary?.normal_station_count || 0, 'normal'],
  ['特殊节点', store.summary?.special_node_count || 0, 'warning'],
  ['来源待确认', store.summary?.source_pending_count || 0, 'warning'],
  ['来源冲突', store.summary?.source_conflict_count || 0, 'danger'],
  ['来源失效', store.summary?.source_stale_count || 0, 'warning'],
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
  { key: 'sort_order', label: '主线顺序', valueType: 'number', width: 105, displayValue: (row) => row.sort_order ?? '--' },
  { key: 'code', label: '节点编码', minWidth: 110, displayValue: (row) => display(row.code) },
  { key: 'name', label: '节点名称', valueType: 'name', minWidth: 170 },
  { key: 'node_type', label: '节点类型', valueType: 'status', width: 120, displayValue: (row) => stationNodeTypeLabel(row.node_type) },
  { key: 'path_code', label: '所属路径', minWidth: 115, displayValue: (row) => display(row.path_code) },
  { key: 'participates_in_direction', label: '参与方向', width: 105, displayValue: (row) => boolText(row.participates_in_direction) },
  { key: 'structure_platform', label: '结构 / 站台', minWidth: 160, displayValue: (row) => `${structureTypeLabel(row.structure_type)} / ${platformLayoutLabel(row.platform_layout)}` },
  { key: 'terminals', label: '端点', minWidth: 125, displayValue: (row) => terminalSummary(row) },
  { key: 'turnback', label: '折返', minWidth: 150, displayValue: (row) => turnbackSummary(row) },
  { key: 'source_device_count', label: '来源设备数', valueType: 'number', width: 120 },
  { key: 'source_sync_status', label: '来源状态', valueType: 'status', width: 115, displayValue: (row) => sourceSyncLabel(row.source_sync_status) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 160, displayValue: (row) => display(row.remark), alignmentReason: 'long-text' },
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
  { key: 'mr_position_codes', label: 'MR 端位代码', minWidth: 130, displayValue: (row) => row.mr_position_codes.join(' / ') || '--' },
  { key: 'latest_mesh_status', label: '最近 Mesh-Link', valueType: 'status', width: 140 },
  { key: 'latest_session_id', label: '最近 Online MR', minWidth: 210, displayValue: (row) => display(row.latest_session_id) },
  { key: 'issues', label: '问题', valueType: 'number', width: 90, displayValue: (row) => row.issue_count || '--' },
]
const mrColumns: NcTableColumn<VehicleMr>[] = [
  { key: 'name', label: 'MR 名称', valueType: 'name', minWidth: 170 },
  { key: 'device_id', label: '设备 ID', valueType: 'number', width: 100 },
  { key: 'train_id', label: '所属列车', minWidth: 120 },
  { key: 'mr_position_code', label: 'MR 端位代码', width: 110, displayValue: (row) => row.mr_position_code === 'unknown' ? '--' : row.mr_position_code },
  { key: 'physical_end', label: '物理安装位置', minWidth: 130, displayValue: (row) => physicalEndLabel(row.physical_end) },
  { key: 'car_number', label: '车厢号', valueType: 'number', width: 90, displayValue: (row) => row.car_number ?? '--' },
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
const stationSourceColumns: NcTableColumn<StationSourceCandidate>[] = [
  { key: 'selected', label: '勾选', width: 72, hideable: false },
  { key: 'source_station_value', label: '来源站点值', minWidth: 160 },
  { key: 'code', label: '节点编码', width: 100, displayValue: (row) => display(row.code) },
  { key: 'name', label: '节点名称', valueType: 'name', minWidth: 150 },
  { key: 'node_type', label: '类型', valueType: 'status', width: 110, displayValue: (row) => stationNodeTypeLabel(row.node_type) },
  { key: 'path_code', label: '建议路径', width: 110 },
  { key: 'sort_order', label: '建议顺序', valueType: 'number', width: 105, displayValue: (row) => row.sort_order ?? '--' },
  { key: 'source_device_count', label: '来源设备数', valueType: 'number', width: 120 },
  { key: 'match_status', label: '匹配结果', valueType: 'status', width: 110, displayValue: (row) => sourceMatchLabel(row.match_status) },
  { key: 'issues', label: '问题', valueType: 'description', minWidth: 240, alignmentReason: 'long-text', displayValue: (row) => row.issues.map((item) => item.message).join('；') || (row.node_type === 'station' ? '--' : '未加入主线路径') },
]
const stationTemplateColumns: NcTableColumn<StationTemplatePreviewRow>[] = [
  { key: 'selected', label: '勾选', width: 72, hideable: false },
  { key: 'row_number', label: '行号', valueType: 'number', width: 80 },
  { key: 'source_station_value', label: '来源站点值', minWidth: 160 },
  { key: 'code', label: '节点编码', width: 100, displayValue: (row) => display(row.code) },
  { key: 'name', label: '节点名称', valueType: 'name', minWidth: 150 },
  { key: 'node_type', label: '类型', valueType: 'status', width: 110, displayValue: (row) => stationNodeTypeLabel(row.node_type) },
  { key: 'path_code', label: '所属路径', width: 110 },
  { key: 'sort_order', label: '主线顺序', valueType: 'number', width: 105, displayValue: (row) => row.sort_order ?? '--' },
  { key: 'action', label: '动作', valueType: 'status', width: 105 },
  { key: 'issues', label: '问题', valueType: 'description', minWidth: 220, alignmentReason: 'long-text', displayValue: (row) => row.issues.map((item) => item.message).join('；') || '--' },
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
        ElMessage.warning(session.write_denial_reason || '当前局点基础资料写入未授权')
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
  fieldErrors.value = {}
  serverSnapshot.value = null
  editingDraft.value = null
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
  fieldErrors.value = {}
  editState.value = 'LOCKED'
  baselines.clear()
  serverSnapshot.value = null
  editingDraft.value = null
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
    if (!locked.value) captureBaselines()
  } catch (cause) { ElMessage.error(message(cause, '基础资料刷新失败')) }
}

async function beforeTabLeave(next: string, current: string): Promise<boolean> {
  if (next === current) return true
  if (saving.value) return false
  return !dirty.value || confirmUnsavedChanges()
}

async function saveAllChanges(): Promise<boolean> {
  if (!store.editSession || saving.value || !dirty.value) return !dirty.value
  const changes = Object.values(pendingChanges.value)
  if (planningDirty.value) {
    changes.push({ entity_type: 'trackside_ap_plan', action: 'replace', values: { rows: planningRows.value } })
  }
  editState.value = 'VALIDATING'
  saveIssues.value = []
  fieldErrors.value = {}
  try {
    const validation = await store.validateChanges(changes)
    if (!validation.valid) {
      saveIssues.value = validation.issues
      setFieldErrors(changes, validation.issues)
      editState.value = 'SAVE_FAILED'
      ElMessage.error(validation.issues[0]?.message || '基础资料校验失败')
      return false
    }
    editState.value = 'SAVING'
    const result = await store.saveChanges(changes)
    pendingChanges.value = {}
    planningDirty.value = false
    saveIssues.value = []
    fieldErrors.value = {}
    baselines.clear()
    await Promise.all([store.manualRefresh(), planningTab.value?.reload(true)])
    editState.value = 'LOCKED'
    serverSnapshot.value = null
    editingDraft.value = null
    store.startPolling()
    ElMessage.success(`基础资料已保存：新增 ${result.created_count}，更新 ${result.updated_count}，删除 ${result.deleted_count}`)
    return true
  } catch (cause) {
    editState.value = 'SAVE_FAILED'
    ElMessage.error(message(cause, '基础资料保存失败，修改已保留'))
    return false
  }
}

async function cancelEditing(): Promise<void> {
  if (!dirty.value) {
    lockClean()
    return
  }
  const accepted = await confirm({
    type: 'WARNING',
    title: '放弃基础资料修改',
    message: '当前新增、修改和删除记录都尚未保存。确认放弃并恢复最近一次服务端数据？',
    confirmText: '放弃修改',
  })
  if (accepted) await discardChanges()
}

function captureBaselines(): void {
  baselines.clear()
  const snapshot: BaseDataDraft = {
    metadata: {
      line_name: store.summary?.line_name || '',
      system_type: store.summary?.project_type || '',
      network_domain: store.summary?.network_type || 'default',
      main_path_code: store.summary?.main_path_code || 'MAIN',
      increasing_direction_name: store.summary?.increasing_direction_name || '上行',
      decreasing_direction_name: store.summary?.decreasing_direction_name || '下行',
      increasing_direction_leading_end: store.summary?.increasing_direction_leading_end || 'unknown',
      station_source_group_name: store.summary?.station_source_group_name || '车站',
      station_source_field: store.summary?.station_source_field || 'station',
      remark: store.summary?.remark || '',
    },
    stations: cloneDto(store.stations),
    sections: cloneDto(store.sections),
    aps: cloneDto(store.aps),
    mrs: cloneDto(store.mrs),
  }
  serverSnapshot.value = snapshot
  editingDraft.value = cloneDto(serverSnapshot.value)
  baselines.set(changeKey('site_metadata', 'current'), metadataValues(snapshot.metadata))
  for (const row of serverSnapshot.value.stations) baselines.set(changeKey('station', row.id), stationValues(row))
  for (const row of serverSnapshot.value.sections) baselines.set(changeKey('section', row.id), sectionValues(row))
  for (const row of serverSnapshot.value.aps) baselines.set(changeKey('trackside_ap', row.id), apValues(row))
  for (const row of serverSnapshot.value.mrs) baselines.set(changeKey('vehicle_mr', row.id), mrValues(row))
}

function handlePlanningChange(rows: TracksideApPlanRow[], changed: boolean): void {
  planningRows.value = rows
  planningDirty.value = changed
  updateEditState()
}

function markMetadata(): void {
  if (!editingDraft.value || locked.value) return
  recordChange('site_metadata', 'current', metadataValues(editingDraft.value.metadata))
}

function markStation(row: Station): void { recordChange('station', row.id, stationValues(row)) }
function markSection(row: Section): void { recordChange('section', row.id, sectionValues(row)) }
function markAp(row: TracksideAp): void { recordChange('trackside_ap', row.id, apValues(row)) }
function markMr(row: VehicleMr): void { recordChange('vehicle_mr', row.id, mrValues(row)) }

function recordChange(entityType: BaseDataChange['entity_type'], entityId: string, values: Record<string, unknown>): void {
  if (locked.value) return
  clearFieldErrors(entityType, entityId)
  const key = changeKey(entityType, entityId)
  const baseline = baselines.get(key)
  if (!baseline) {
    baselines.set(key, cloneDto(values))
    if (!entityId.startsWith('new:')) return
  }
  const action = entityId.startsWith('new:') ? 'create' : 'update'
  const payload = action === 'update' ? withOriginalIdentity(entityType, values, baselines.get(key) || {}) : values
  if (action === 'update' && JSON.stringify(values) === JSON.stringify(baselines.get(key))) delete pendingChanges.value[key]
  else pendingChanges.value[key] = { entity_type: entityType, action, entity_id: entityId, values: payload }
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function fieldError(entityType: BaseDataChange['entity_type'], entityId: string, fieldName: string): string | undefined {
  return fieldErrors.value[`${changeKey(entityType, entityId)}:${fieldName}`]
}

function setFieldErrors(changes: BaseDataChange[], issues: BaseDataValidationIssue[]): void {
  const next: Record<string, string> = {}
  for (const issue of issues) {
    const change = changes[issue.change_index]
    if (change && issue.field_name) next[`${changeKey(change.entity_type, change.entity_id || `index:${issue.change_index}`)}:${issue.field_name}`] = issue.message
  }
  fieldErrors.value = next
}

function clearFieldErrors(entityType: BaseDataChange['entity_type'], entityId: string): void {
  const prefix = `${changeKey(entityType, entityId)}:`
  const next = Object.fromEntries(Object.entries(fieldErrors.value).filter(([key]) => !key.startsWith(prefix)))
  fieldErrors.value = next
}

async function deleteEntity(entityType: BaseDataChange['entity_type'], row: Station | Section | TracksideAp | VehicleMr): Promise<void> {
  if (locked.value) return
  const key = changeKey(entityType, row.id)
  if (row.id.startsWith('new:')) {
    delete pendingChanges.value[key]
    baselines.delete(key)
    removeDraftRow(entityType, row.id)
    pendingChanges.value = { ...pendingChanges.value }
    updateEditState()
    return
  }
  const accepted = await confirm({ type: 'DANGER', title: '标记删除', message: '该数据将在点击“保存”后删除；存在业务引用时后端会拒绝。是否继续？', confirmText: '标记删除' })
  if (!accepted) return
  const baseline = baselines.get(key) || valuesFor(entityType, row)
  pendingChanges.value[key] = { entity_type: entityType, action: 'delete', entity_id: row.id, values: withOriginalIdentity(entityType, baseline, baseline) }
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function removeDraftRow(entityType: BaseDataChange['entity_type'], entityId: string): void {
  if (!editingDraft.value) return
  if (entityType === 'station') editingDraft.value.stations = editingDraft.value.stations.filter((item) => item.id !== entityId)
  else if (entityType === 'section') editingDraft.value.sections = editingDraft.value.sections.filter((item) => item.id !== entityId)
  else if (entityType === 'trackside_ap') editingDraft.value.aps = editingDraft.value.aps.filter((item) => item.id !== entityId)
  else editingDraft.value.mrs = editingDraft.value.mrs.filter((item) => item.id !== entityId)
}

function isPendingDelete(entityType: BaseDataChange['entity_type'], entityId: string): boolean {
  return pendingChanges.value[changeKey(entityType, entityId)]?.action === 'delete'
}

function canEditRow(entityType: BaseDataChange['entity_type'], entityId: string): boolean {
  return editing.value && !saving.value && !isPendingDelete(entityType, entityId)
}

function undoDelete(entityType: BaseDataChange['entity_type'], row: Station | Section | TracksideAp | VehicleMr): void {
  const key = changeKey(entityType, row.id)
  if (!isPendingDelete(entityType, row.id)) return
  const values = valuesFor(entityType, row)
  const baseline = baselines.get(key)
  if (baseline && JSON.stringify(values) !== JSON.stringify(baseline)) {
    pendingChanges.value[key] = {
      entity_type: entityType,
      action: 'update',
      entity_id: row.id,
      values: withOriginalIdentity(entityType, values, baseline),
    }
  } else delete pendingChanges.value[key]
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function addStation(): void {
  if (!editingDraft.value) return
  const row: Station = defaultStation({ id: temporaryId(), line_name: store.summary?.line_name || '', sort_order: editingDraft.value.stations.length + 1, source_kind: 'manual', source_sync_status: 'manual' })
  editingDraft.value.stations.push(row); markStation(row)
}
function addSection(): void {
  if (!editingDraft.value) return
  const row: Section = { id: temporaryId(), name: '', start_station: '', end_station: '', line_side: '', ap_count: 0, mileage_min: null, mileage_max: null, remark: '' }
  editingDraft.value.sections.push(row); markSection(row)
}
function addAp(): void {
  if (!editingDraft.value) return
  const row: TracksideAp = { id: temporaryId(), site_id: store.editSession?.site_id || '', line_name: store.summary?.line_name || '', name: '', point_code: '', mac: '', management_ip: '', model: '', station: '', section: '', section_start_station: '', section_end_station: '', mileage: { raw: '', normalized: '', meters: null, line_type: '', valid: false, error: '' }, line_side: '', direction: '', radios: [], remark: '', source_file: '', source_sheet: '', source_row: null, updated_at: '', runtime: emptyRuntime(), issue_count: 0, highest_issue_severity: '', record_kind: 'manual', base_metadata: {} }
  editingDraft.value.aps.push(row); markAp(row)
}
function addMr(): void {
  if (!editingDraft.value) return
  const row: VehicleMr = { id: temporaryId(), device_id: null, name: '', train_id: '', train_no: '', role: '', mr_position_code: 'unknown', physical_end: 'unknown', car_number: null, management_ip: '', station: '', mac: '', protocol: 'SSH', port: 22, remark: '', runtime: emptyRuntime(), issue_count: 0, highest_issue_severity: '' }
  editingDraft.value.mrs.push(row); markMr(row)
}

function updateEditState(): void {
  if (!locked.value && !saving.value) editState.value = dirty.value ? 'UNLOCKED_DIRTY' : 'UNLOCKED_CLEAN'
}
function changeKey(type: string, id: string): string { return `${type}:${id}` }
function temporaryId(): string { return `new:${Date.now()}:${Math.random().toString(16).slice(2)}` }
function stationValues(row: Station): Record<string, unknown> {
  return {
    name: row.name,
    code: row.code,
    line_name: row.line_name,
    sort_order: row.sort_order,
    remark: row.remark,
    source_station_value: row.source_station_value,
    source_station_key: row.source_station_key,
    node_type: row.node_type,
    path_code: row.path_code,
    participates_in_direction: row.participates_in_direction,
    structure_type: row.structure_type,
    platform_layout: row.platform_layout,
    is_line_terminal: row.is_line_terminal,
    is_service_terminal: row.is_service_terminal,
    turnback_capable: row.turnback_capable,
    turnback_type: row.turnback_type,
    turnback_direction: row.turnback_direction,
    enabled: row.enabled,
    source_kind: row.source_kind,
  }
}
function sectionValues(row: Section): Record<string, unknown> { return { name: row.name, start_station: row.start_station, end_station: row.end_station, line_side: row.line_side, remark: row.remark } }
function apValues(row: TracksideAp): Record<string, unknown> { return { line_name: row.line_name, name: row.name, point_code: row.point_code, mac: row.mac, station: row.station, section: row.section, section_start_station: row.section_start_station, section_end_station: row.section_end_station, mileage: row.mileage.raw, line_side: row.line_side, direction: row.direction, remark: row.remark } }
function mrValues(row: VehicleMr): Record<string, unknown> { return { name: row.name, station: row.station, management_ip: row.management_ip, mac: row.mac, protocol: row.protocol, port: row.port, remark: row.remark } }
function metadataValues(metadata: BaseDataDraft['metadata']): Record<string, unknown> {
  return {
    line_name: metadata.line_name,
    system_type: metadata.system_type,
    network_domain: metadata.network_domain,
    main_path_code: metadata.main_path_code,
    increasing_direction_name: metadata.increasing_direction_name,
    decreasing_direction_name: metadata.decreasing_direction_name,
    increasing_direction_leading_end: metadata.increasing_direction_leading_end,
    station_source_group_name: metadata.station_source_group_name,
    station_source_field: 'station',
    remark: metadata.remark,
  }
}
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
function isStationSourceCandidateSelected(candidate: StationSourceCandidate): boolean {
  return selectedStationSourceIds.value.includes(candidate.candidate_id)
}

function isStationSourceCandidateDisabled(candidate: StationSourceCandidate): boolean {
  return candidate.match_status === 'conflict' || candidate.issues.some((issue) => issue.blocking)
}

function isStationTemplateRowSelected(row: StationTemplatePreviewRow): boolean {
  return selectedTemplateRows.value.includes(row.row_number)
}

function isStationTemplateRowDisabled(row: StationTemplatePreviewRow): boolean {
  return !row.valid || row.action === 'conflict'
}

function canApplyStationTemplatePreview(): boolean {
  return !locked.value && selectedTemplateRows.value.length > 0 && !store.stationTemplatePreview?.blocking_count
}

async function openStationSourcePreview(): Promise<void> {
  try {
    const preview = await store.refreshStationSourcePreview()
    selectedStationSourceIds.value = preview.candidates
      .filter((candidate) => !candidate.issues.some((issue) => issue.blocking) && candidate.match_status !== 'conflict')
      .map((candidate) => candidate.candidate_id)
    stationSourceDialogVisible.value = true
  } catch (cause) {
    ElMessage.error(message(cause, '设备管理站点来源预览失败'))
  }
}

function toggleStationSourceCandidate(candidate: StationSourceCandidate, checked: boolean): void {
  const next = new Set(selectedStationSourceIds.value)
  if (checked) next.add(candidate.candidate_id)
  else next.delete(candidate.candidate_id)
  selectedStationSourceIds.value = [...next]
}

function applyStationSourceToDraft(): void {
  if (locked.value || !editingDraft.value) {
    ElMessage.warning('请先解锁基础资料')
    return
  }
  const selected = new Set(selectedStationSourceIds.value)
  const candidates = stationSourceCandidates.value.filter((candidate) => selected.has(candidate.candidate_id) && candidate.match_status !== 'conflict')
  if (!candidates.length) {
    ElMessage.warning('没有可应用的站点来源候选')
    return
  }
  let applied = 0
  for (const candidate of candidates) {
    const proposed = defaultStation(candidate.proposed_station)
    proposed.line_name = proposed.line_name || editingDraft.value.metadata.line_name || store.summary?.line_name || ''
    const matched = candidate.matched_station_id
      ? editingDraft.value.stations.find((station) => station.id === candidate.matched_station_id)
      : editingDraft.value.stations.find((station) => station.source_station_key && station.source_station_key === candidate.source_station_key)
    if (matched) {
      matched.source_station_value = candidate.source_station_value
      matched.source_station_key = candidate.source_station_key
      matched.source_kind = 'device_station_field'
      matched.source_device_count = candidate.source_device_count
      matched.source_sync_status = 'matched'
      markStation(matched)
      applied += 1
      continue
    }
    proposed.id = proposed.id || temporaryId()
    proposed.source_device_count = candidate.source_device_count
    proposed.source_sync_status = 'matched'
    editingDraft.value.stations.push(proposed)
    markStation(proposed)
    applied += 1
  }
  stationSourceDialogVisible.value = false
  ElMessage.success(`已应用 ${applied} 个候选到当前草稿，保存后才会写入数据库`)
}

async function downloadStationTemplate(): Promise<void> {
  const result = await downloadBackendResource(stationTemplateDownloadRequest())
  if (result.status === 'saved' || result.status === 'started') ElMessage.success('站点模板下载已开始')
  else if (result.status === 'failed') ElMessage.error(result.error || '站点模板下载失败')
}

async function exportCurrentStations(): Promise<void> {
  const result = await downloadBackendResource(stationTemplateExportDownloadRequest())
  if (result.status === 'saved' || result.status === 'started') ElMessage.success('当前基础资料导出已开始')
  else if (result.status === 'failed') ElMessage.error(result.error || '当前基础资料导出失败')
}

async function handleStationTemplateFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const preview = await store.previewStationTemplateFile(file)
    selectedTemplateRows.value = preview.rows.filter((row) => row.valid && row.action !== 'conflict').map((row) => row.row_number)
    stationTemplateDialogVisible.value = true
    ElMessage.success('站点模板预览完成，未写入数据库')
  } catch (cause) {
    ElMessage.error(message(cause, '站点模板预览失败'))
  } finally {
    input.value = ''
  }
}

function toggleTemplateRow(row: StationTemplatePreviewRow, checked: boolean): void {
  const next = new Set(selectedTemplateRows.value)
  if (checked) next.add(row.row_number)
  else next.delete(row.row_number)
  selectedTemplateRows.value = [...next]
}

function applyStationTemplateToDraft(): void {
  if (locked.value || !editingDraft.value) {
    ElMessage.warning('请先解锁基础资料')
    return
  }
  const selected = new Set(selectedTemplateRows.value)
  const rows = stationTemplateRows.value.filter((item) => selected.has(item.row_number) && item.valid && item.proposed_station)
  if (!rows.length) {
    ElMessage.warning('没有可应用的模板行')
    return
  }
  let applied = 0
  for (const row of rows) {
    const proposed = defaultStation(row.proposed_station || {})
    const matched = editingDraft.value.stations.find((station) => (
      (proposed.source_station_key && station.source_station_key === proposed.source_station_key)
      || (proposed.code && station.code === proposed.code && station.name === proposed.name)
    ))
    if (matched) {
      Object.assign(matched, { ...proposed, id: matched.id, source_device_count: matched.source_device_count, source_sync_status: matched.source_sync_status })
      markStation(matched)
    } else {
      proposed.id = temporaryId()
      editingDraft.value.stations.push(proposed)
      markStation(proposed)
    }
    applied += 1
  }
  const metadata = store.stationTemplatePreview?.line_metadata || {}
  editingDraft.value.metadata.line_name = String(metadata.line_name || editingDraft.value.metadata.line_name)
  editingDraft.value.metadata.system_type = String(metadata.system_type || editingDraft.value.metadata.system_type)
  editingDraft.value.metadata.network_domain = String(metadata.network_domain || editingDraft.value.metadata.network_domain)
  editingDraft.value.metadata.main_path_code = String(metadata.main_path_code || editingDraft.value.metadata.main_path_code)
  editingDraft.value.metadata.increasing_direction_name = String(metadata.increasing_direction_name || editingDraft.value.metadata.increasing_direction_name)
  editingDraft.value.metadata.decreasing_direction_name = String(metadata.decreasing_direction_name || editingDraft.value.metadata.decreasing_direction_name)
  editingDraft.value.metadata.station_source_group_name = String(metadata.station_source_group_name || editingDraft.value.metadata.station_source_group_name)
  editingDraft.value.metadata.station_source_field = 'station'
  editingDraft.value.metadata.remark = String(metadata.remark || editingDraft.value.metadata.remark)
  markMetadata()
  stationTemplateDialogVisible.value = false
  ElMessage.success(`已应用 ${applied} 行模板预览到当前草稿，保存后才会写入数据库`)
}

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
function physicalEndLabel(value: VehicleMr['physical_end'] | RailTransitSummary['increasing_direction_leading_end']): string {
  return value === 'car_1_end' ? '1车厢端' : value === 'car_6_end' ? '6车厢端' : '未设置'
}
function cloneDto<T>(value: T): T { return structuredClone(toRaw(value)) }
function defaultStation(values: Partial<Station> = {}): Station {
  return {
    id: '',
    name: '',
    code: '',
    line_name: '',
    sort_order: null,
    ap_count: 0,
    section_count: 0,
    mileage_min: null,
    mileage_max: null,
    remark: '',
    source_station_value: '',
    source_station_key: '',
    node_type: 'station',
    path_code: 'MAIN',
    participates_in_direction: true,
    structure_type: 'unknown',
    platform_layout: 'unknown',
    is_line_terminal: false,
    is_service_terminal: false,
    turnback_capable: false,
    turnback_type: 'none',
    turnback_direction: 'none',
    enabled: true,
    source_kind: 'manual',
    source_device_count: 0,
    source_sync_status: 'manual',
    source_last_seen_at: '',
    ...values,
  }
}
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
function boolText(value: boolean): string { return value ? '是' : '否' }
function stationNodeTypeLabel(value: string): string {
  return ({ station: '普通车站', parking_lot: '停车场', depot: '车辆段', connection_point: '接轨点', other: '其他', unknown: '待确认' } as Record<string, string>)[value] || value || '--'
}
function stationNodeTypeTag(value: string): 'success' | 'warning' | 'info' {
  return value === 'station' ? 'success' : value === 'parking_lot' || value === 'depot' ? 'warning' : 'info'
}
function structureTypeLabel(value: string): string {
  return ({ underground: '地下', elevated: '高架', at_grade: '地面', cutting: '路堑', mixed: '混合', unknown: '未填写' } as Record<string, string>)[value] || value || '--'
}
function platformLayoutLabel(value: string): string {
  return ({ island: '岛式', side: '侧式', mixed: '混合式', stacked_island: '叠岛式', stacked_side: '叠侧式', separated: '分离式', unknown: '未填写' } as Record<string, string>)[value] || value || '--'
}
function turnbackTypeLabel(value: string): string {
  return ({ none: '无', crossover: '渡线', pocket_track: '中间折返线/存车线', tail_track: '站后折返线', loop: '环形折返', depot_connection: '出入段线', other: '其他', unknown: '类型未知' } as Record<string, string>)[value] || value || '--'
}
function turnbackDirectionLabel(value: string): string {
  return ({ none: '无', both: '双向', increasing_to_decreasing: '递增转递减', decreasing_to_increasing: '递减转递增', unknown: '未知' } as Record<string, string>)[value] || value || '--'
}
function sourceSyncLabel(value: string): string {
  return ({ matched: '已匹配', stale: '来源失效', conflict: '来源冲突', manual: '人工创建', legacy: 'AP旧资料', unavailable: '不可用' } as Record<string, string>)[value] || value || '--'
}
function sourceMatchLabel(value: string): string {
  return ({ create: '新增', matched: '匹配', conflict: '冲突', manual_review: '待确认' } as Record<string, string>)[value] || value || '--'
}
function terminalSummary(row: Station): string {
  const values = []
  if (row.is_line_terminal) values.push('线路端点')
  if (row.is_service_terminal) values.push('运营终点')
  return values.join(' / ') || '--'
}
function turnbackSummary(row: Station): string {
  if (!row.turnback_capable) return '不可折返'
  return `${turnbackTypeLabel(row.turnback_type)} / ${turnbackDirectionLabel(row.turnback_direction)}`
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
        <el-button v-if="editing" :disabled="saving" @click="cancelEditing">取消修改</el-button>
        <el-button type="primary" :loading="saving" :disabled="locked || !dirty" @click="saveAllChanges">保存</el-button>
      </div>
    </div>
    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />
    <el-alert v-if="locked && writeDeniedReason" :title="writeDeniedReason" type="warning" :closable="false" show-icon class="page-error" />
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
            <el-descriptions-item label="线路与方向参数" :span="2">站序递增方向 = {{ store.summary?.increasing_direction_name || '上行' }}；站序递减方向 = {{ store.summary?.decreasing_direction_name || '下行' }}；递增方向行驶头端 = {{ physicalEndLabel(store.summary?.increasing_direction_leading_end || 'unknown') }}</el-descriptions-item>
            <el-descriptions-item label="线路名称">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.line_name"
                maxlength="200"
                show-word-limit
                placeholder="请输入线路名称"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.line_name || '--' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="项目类型">
              <el-select
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.system_type"
                filterable
                allow-create
                default-first-option
                placeholder="请选择或输入项目类型"
                @change="markMetadata"
              >
                <el-option label="PIS" value="PIS" />
                <el-option label="信号" value="信号" />
                <el-option label="综合监控" value="综合监控" />
                <el-option label="其他" value="其他" />
              </el-select>
              <span v-else>{{ store.summary?.project_type || '--' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="网络类型">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.network_domain"
                maxlength="100"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.network_type || '--' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="主线路径编码">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.main_path_code"
                maxlength="50"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.main_path_code || 'MAIN' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="站序递增方向">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.increasing_direction_name"
                maxlength="50"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.increasing_direction_name || '上行' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="站序递减方向">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.decreasing_direction_name"
                maxlength="50"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.decreasing_direction_name || '下行' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="站序递增时的行驶头端">
              <el-select
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.increasing_direction_leading_end"
                @change="markMetadata"
              >
                <el-option label="1车厢端" value="car_1_end" />
                <el-option label="6车厢端" value="car_6_end" />
                <el-option label="未设置" value="unknown" />
              </el-select>
              <span v-else>{{ physicalEndLabel(store.summary?.increasing_direction_leading_end || 'unknown') }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="来源分组">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.station_source_group_name"
                maxlength="100"
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.station_source_group_name || '车站' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="来源字段">
              <span>设备管理 · 站点字段</span>
            </el-descriptions-item>
            <el-descriptions-item label="数据更新时间">{{ store.summary?.updated_at || '--' }}</el-descriptions-item>
            <el-descriptions-item label="备注" :span="2">
              <el-input
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.remark"
                type="textarea"
                :rows="2"
                maxlength="1000"
                show-word-limit
                @input="markMetadata"
              />
              <span v-else>{{ store.summary?.remark || '--' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="说明" :span="3">{{ store.summary?.message || '--' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <el-tab-pane label="站点与区间" name="stations">
          <el-tabs v-model="locationTab" type="card">
            <el-tab-pane label="站点" name="stations">
              <el-alert class="station-source-note" title="车站初稿来自设备管理中分组为“车站”的设备的“站点”字段。设备名称、系统名和地址不参与站点识别。" type="info" :closable="false" show-icon />
              <div class="edit-toolbar">
                <el-button :loading="store.stationSourceLoading" @click="openStationSourcePreview">从设备管理生成</el-button>
                <el-button :icon="Download" @click="downloadStationTemplate">下载模板</el-button>
                <label class="inline-file-button">
                  <el-icon><UploadFilled /></el-icon><span>导入模板</span>
                  <input type="file" accept=".xlsx" @change="handleStationTemplateFile" />
                </label>
                <el-button :icon="Download" @click="exportCurrentStations">导出当前</el-button>
                <el-button :icon="Plus" :disabled="locked || saving" @click="addStation">新增节点</el-button>
              </div>
              <NcDataTable table-id="rail-base-stations" route-key="/rail-transit/base-data" :data="stationRows" :columns="stationEditColumns" height="calc(100vh - 410px)" empty-text="暂无站点资料">
                <template #cell-sort_order="{ row }"><el-input-number v-if="canEditRow('station', row.id) && row.participates_in_direction" v-model="row.sort_order" :min="0" controls-position="right" @change="markStation(row)" /><span v-else>{{ row.sort_order ?? '--' }}</span></template>
                <template #cell-name="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.name" :class="{ 'field-error': fieldError('station', row.id, 'name') }" @input="markStation(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-code="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.code" :class="{ 'field-error': fieldError('station', row.id, 'code') }" @input="markStation(row)" /><span v-else>{{ display(row.code) }}</span></template>
                <template #cell-node_type="{ row }"><el-tag :type="stationNodeTypeTag(row.node_type)">{{ stationNodeTypeLabel(row.node_type) }}</el-tag></template>
                <template #cell-path_code="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.path_code" @input="markStation(row)" /><span v-else>{{ display(row.path_code) }}</span></template>
                <template #cell-participates_in_direction="{ row }"><el-switch v-if="canEditRow('station', row.id)" v-model="row.participates_in_direction" @change="markStation(row)" /><span v-else>{{ boolText(row.participates_in_direction) }}</span></template>
                <template #cell-structure_platform="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="compact-pair">
                    <el-select v-model="row.structure_type" @change="markStation(row)"><el-option label="未填写" value="unknown" /><el-option label="地下" value="underground" /><el-option label="高架" value="elevated" /><el-option label="地面" value="at_grade" /><el-option label="路堑" value="cutting" /><el-option label="混合" value="mixed" /></el-select>
                    <el-select v-model="row.platform_layout" @change="markStation(row)"><el-option label="未填写" value="unknown" /><el-option label="岛式" value="island" /><el-option label="侧式" value="side" /><el-option label="混合式" value="mixed" /><el-option label="叠岛式" value="stacked_island" /><el-option label="叠侧式" value="stacked_side" /><el-option label="分离式" value="separated" /></el-select>
                  </div>
                  <span v-else>{{ structureTypeLabel(row.structure_type) }} / {{ platformLayoutLabel(row.platform_layout) }}</span>
                </template>
                <template #cell-terminals="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="inline-checks">
                    <el-checkbox v-model="row.is_line_terminal" @change="markStation(row)">线路</el-checkbox>
                    <el-checkbox v-model="row.is_service_terminal" @change="markStation(row)">运营</el-checkbox>
                  </div>
                  <span v-else>{{ terminalSummary(row) }}</span>
                </template>
                <template #cell-turnback="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="compact-pair">
                    <el-switch v-model="row.turnback_capable" @change="markStation(row)" />
                    <el-select v-model="row.turnback_type" :disabled="!row.turnback_capable" @change="markStation(row)"><el-option label="无" value="none" /><el-option label="渡线" value="crossover" /><el-option label="中间折返线/存车线" value="pocket_track" /><el-option label="站后折返线" value="tail_track" /><el-option label="环形折返" value="loop" /><el-option label="出入段线" value="depot_connection" /><el-option label="其他" value="other" /><el-option label="类型未知" value="unknown" /></el-select>
                  </div>
                  <span v-else>{{ turnbackSummary(row) }}</span>
                </template>
                <template #cell-source_sync_status="{ row }"><el-tag :type="stateType(row.source_sync_status)">{{ sourceSyncLabel(row.source_sync_status) }}</el-tag></template>
                <template #cell-remark="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.remark" @input="markStation(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('station', row)">移除</el-button><template v-if="isPendingDelete('station', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('station', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('station', row)">删除</el-button></template>
              </NcDataTable>
            </el-tab-pane>
            <el-tab-pane label="区间" name="sections">
              <div class="edit-toolbar"><el-button :disabled="locked || saving" @click="addSection">新增区间</el-button></div>
              <NcDataTable table-id="rail-base-sections" route-key="/rail-transit/base-data" :data="sectionRows" :columns="sectionEditColumns" height="calc(100vh - 410px)" empty-text="暂无区间资料">
                <template #cell-name="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.name" :class="{ 'field-error': fieldError('section', row.id, 'name') }" @input="markSection(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-start_station="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.start_station" @input="markSection(row)" /><span v-else>{{ display(row.start_station) }}</span></template>
                <template #cell-end_station="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.end_station" @input="markSection(row)" /><span v-else>{{ display(row.end_station) }}</span></template>
                <template #cell-line_side="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.line_side" @input="markSection(row)" /><span v-else>{{ display(row.line_side) }}</span></template>
                <template #cell-remark="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.remark" @input="markSection(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('section', row)">移除</el-button><template v-if="isPendingDelete('section', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('section', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('section', row)">删除</el-button></template>
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
          <NcDataTable table-id="rail-base-trackside-aps" route-key="/rail-transit/base-data" :data="apRows" :columns="apColumns" height="calc(100vh - 430px)" empty-text="暂无轨旁 AP 扩展资料">
            <template #cell-name="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.name" :class="{ 'field-error': fieldError('trackside_ap', row.id, 'name') }" @input="markAp(row)" /><span v-else>{{ row.name || row.point_code || '--' }}</span></template>
            <template #cell-point_code="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.point_code" :class="{ 'field-error': fieldError('trackside_ap', row.id, 'point_code') }" @input="markAp(row)" /><span v-else>{{ display(row.point_code) }}</span></template>
            <template #cell-mac="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.mac" :class="{ 'field-error': fieldError('trackside_ap', row.id, 'mac') }" @input="markAp(row)" /><span v-else>{{ display(row.mac) }}</span></template>
            <template #cell-station="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.station" @input="markAp(row)" /><span v-else>{{ display(row.station) }}</span></template>
            <template #cell-section="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.section" @input="markAp(row)" /><span v-else>{{ display(row.section) }}</span></template>
            <template #cell-mileage="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.mileage.raw" @input="markAp(row)" /><span v-else>{{ row.mileage.normalized || row.mileage.raw || '--' }}</span></template>
            <template #cell-line_side="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.line_side" @input="markAp(row)" /><span v-else>{{ display(row.line_side) }}</span></template>
            <template #cell-direction="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.direction" @input="markAp(row)" /><span v-else>{{ display(row.direction) }}</span></template>
            <template #cell-remark="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.remark" @input="markAp(row)" /><span v-else>{{ display(row.remark) }}</span></template>
            <template #cell-fit_ap_status="{ row }"><el-tag :type="stateType(row.runtime.fit_ap_status)">{{ row.runtime.fit_ap_status }}</el-tag></template>
            <template #cell-mesh_related_name="{ row }">{{ display(row.runtime.mesh_related_name) }}</template>
            <template #cell-optical_status="{ row }"><el-tag :type="stateType(row.runtime.optical_status)">{{ row.runtime.optical_status }}</el-tag></template>
            <template #cell-issues="{ row }"><el-tag v-if="row.issue_count" :type="issueType(row.highest_issue_severity)">{{ row.issue_count }}</el-tag><span v-else>--</span></template>
            <template #cell-actions="{ row }"><el-button link type="primary" @click="openApAc(row)">FIT-AP</el-button><el-button link type="primary" @click="openApMesh(row)">Mesh-Link</el-button><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('trackside_ap', row)">移除</el-button><template v-if="isPendingDelete('trackside_ap', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('trackside_ap', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('trackside_ap', row)">删除</el-button></template>
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
                <el-select v-model="store.mrFilters.mr_role" clearable placeholder="MR 端位代码"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
                <el-button type="primary" :disabled="!locked" @click="store.applyMrFilters">应用筛选</el-button>
                <el-button :disabled="locked || saving" @click="addMr">新增车载 MR</el-button>
              </div>
              <NcDataTable table-id="rail-base-vehicle-mrs" route-key="/rail-transit/base-data" :data="mrRows" :columns="mrEditColumns" height="calc(100vh - 430px)" empty-text="暂无车载 MR 资料">
                <template #cell-name="{ row }"><el-input v-if="canEditRow('vehicle_mr', row.id)" v-model="row.name" :class="{ 'field-error': fieldError('vehicle_mr', row.id, 'name') }" @input="markMr(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-management_ip="{ row }"><el-input v-if="canEditRow('vehicle_mr', row.id)" v-model="row.management_ip" :class="{ 'field-error': fieldError('vehicle_mr', row.id, 'management_ip') }" @input="markMr(row)" /><span v-else>{{ display(row.management_ip) }}</span></template>
                <template #cell-mac="{ row }"><el-input v-if="canEditRow('vehicle_mr', row.id)" v-model="row.mac" @input="markMr(row)" /><span v-else>{{ display(row.mac) }}</span></template>
                <template #cell-connection="{ row }"><div v-if="canEditRow('vehicle_mr', row.id)" class="connection-editor"><el-select v-model="row.protocol" @change="markMr(row)"><el-option label="SSH" value="SSH" /><el-option label="Telnet" value="TELNET" /></el-select><el-input-number v-model="row.port" :min="1" :max="65535" controls-position="right" @change="markMr(row)" /></div><span v-else>{{ display(row.protocol) }} / {{ display(row.port) }}</span></template>
                <template #cell-remark="{ row }"><el-input v-if="canEditRow('vehicle_mr', row.id)" v-model="row.remark" @input="markMr(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-mesh_status="{ row }"><el-tag :type="stateType(row.runtime.mesh_status)">{{ row.runtime.mesh_status }}</el-tag></template>
                <template #cell-actions="{ row }"><el-button link type="primary" @click="openMrMesh(row)">Mesh-Link</el-button><el-button link type="primary" @click="openMrSession(row)">Online MR</el-button></template>
                <template #cell-edit_actions="{ row }"><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('vehicle_mr', row)">移除</el-button><template v-if="isPendingDelete('vehicle_mr', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('vehicle_mr', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('vehicle_mr', row)">删除</el-button></template>
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

    <el-dialog v-model="stationSourceDialogVisible" title="设备管理站点来源预览" width="min(1280px, 96vw)" append-to-body destroy-on-close>
      <div v-if="store.stationSourcePreview" class="preview-dialog">
        <el-alert
          v-if="locked"
          title="请先解锁基础资料"
          description="锁定状态可以预览设备管理站点字段，但不能应用到当前草稿。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="!store.stationSourcePreview.group_found"
          :title="`未找到设备分组“${store.stationSourcePreview.source_group_name}”`"
          type="warning"
          :closable="false"
          show-icon
        />
        <div class="preview-summary source-summary">
          <article><span>扫描设备数</span><strong>{{ store.stationSourcePreview.scanned_device_count }}</strong></article>
          <article class="warning"><span>站点字段为空</span><strong>{{ store.stationSourcePreview.empty_station_device_count }}</strong></article>
          <article><span>唯一站点数</span><strong>{{ store.stationSourcePreview.unique_station_value_count }}</strong></article>
          <article class="normal"><span>普通车站</span><strong>{{ store.stationSourcePreview.normal_station_count }}</strong></article>
          <article class="warning"><span>特殊节点</span><strong>{{ store.stationSourcePreview.special_node_count }}</strong></article>
          <article class="normal"><span>新增</span><strong>{{ store.stationSourcePreview.create_count }}</strong></article>
          <article><span>匹配</span><strong>{{ store.stationSourcePreview.match_count }}</strong></article>
          <article class="danger"><span>冲突</span><strong>{{ store.stationSourcePreview.conflict_count }}</strong></article>
        </div>
        <div class="source-meta">
          <el-tag type="info">来源分组：{{ store.stationSourcePreview.source_group_name }}</el-tag>
          <el-tag type="info">来源字段：设备管理 · 站点字段</el-tag>
          <el-tag type="warning" v-if="store.stationSourcePreview.warning_count">警告 {{ store.stationSourcePreview.warning_count }}</el-tag>
        </div>
        <div v-if="store.stationSourcePreview.issues.length" class="row-issues">
          <el-tag v-for="issue in store.stationSourcePreview.issues" :key="`${issue.code}:${issue.message}`" :type="issueType(issue.severity)">
            {{ issue.message }}
          </el-tag>
        </div>
        <NcDataTable
          v-loading="store.stationSourceLoading"
          table-id="rail-base-station-source-preview"
          route-key="/rail-transit/base-data"
          :data="stationSourceCandidates"
          :columns="stationSourceColumns"
          height="420px"
          empty-text="暂无可用站点来源候选"
        >
          <template #cell-selected="{ row }">
            <el-checkbox
              :model-value="isStationSourceCandidateSelected(row)"
              :disabled="isStationSourceCandidateDisabled(row)"
              @change="(checked: boolean) => toggleStationSourceCandidate(row, checked)"
            />
          </template>
          <template #cell-node_type="{ row }"><el-tag :type="stationNodeTypeTag(row.node_type)">{{ stationNodeTypeLabel(row.node_type) }}</el-tag></template>
          <template #cell-match_status="{ row }"><el-tag :type="row.match_status === 'conflict' ? 'danger' : row.match_status === 'matched' ? 'success' : 'info'">{{ sourceMatchLabel(row.match_status) }}</el-tag></template>
          <template #cell-issues="{ row }">
            <div class="row-issues">
              <el-tag v-if="row.node_type !== 'station'" type="warning">未加入主线路径</el-tag>
              <el-tag v-for="issue in row.issues" :key="`${row.candidate_id}:${issue.code}`" :type="issueType(issue.severity)">{{ issue.message }}</el-tag>
              <span v-if="row.node_type === 'station' && !row.issues.length">--</span>
            </div>
          </template>
        </NcDataTable>
      </div>
      <template #footer>
        <el-button @click="stationSourceDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="locked || saving || selectedStationSourceIds.length === 0"
          @click="applyStationSourceToDraft"
        >应用到当前草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stationTemplateDialogVisible" title="站点模板导入预览" width="min(1280px, 96vw)" append-to-body destroy-on-close>
      <div v-if="store.stationTemplatePreview" class="preview-dialog">
        <el-alert
          v-if="locked"
          title="请先解锁基础资料"
          description="模板预览不会写入数据库；解锁后才能应用到当前草稿。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="store.stationTemplatePreview.blocking_count"
          title="模板存在阻断问题"
          description="请修正枚举、重复来源或来源字段后重新导入。"
          type="error"
          :closable="false"
          show-icon
        />
        <el-descriptions :column="3" border class="meta-block">
          <el-descriptions-item label="线路名称">{{ display(store.stationTemplatePreview.line_metadata.line_name) }}</el-descriptions-item>
          <el-descriptions-item label="项目类型">{{ display(store.stationTemplatePreview.line_metadata.system_type) }}</el-descriptions-item>
          <el-descriptions-item label="网络类型">{{ display(store.stationTemplatePreview.line_metadata.network_domain) }}</el-descriptions-item>
          <el-descriptions-item label="主线路径">{{ display(store.stationTemplatePreview.line_metadata.main_path_code) }}</el-descriptions-item>
          <el-descriptions-item label="递增方向">{{ display(store.stationTemplatePreview.line_metadata.increasing_direction_name) }}</el-descriptions-item>
          <el-descriptions-item label="递减方向">{{ display(store.stationTemplatePreview.line_metadata.decreasing_direction_name) }}</el-descriptions-item>
          <el-descriptions-item label="来源分组">{{ display(store.stationTemplatePreview.line_metadata.station_source_group_name) }}</el-descriptions-item>
          <el-descriptions-item label="来源字段">设备管理 · 站点字段</el-descriptions-item>
          <el-descriptions-item label="备注">{{ display(store.stationTemplatePreview.line_metadata.remark) }}</el-descriptions-item>
        </el-descriptions>
        <div class="preview-summary template-summary">
          <article class="normal"><span>新增</span><strong>{{ store.stationTemplatePreview.create_count }}</strong></article>
          <article><span>更新</span><strong>{{ store.stationTemplatePreview.update_count }}</strong></article>
          <article><span>不变</span><strong>{{ store.stationTemplatePreview.unchanged_count }}</strong></article>
          <article class="danger"><span>冲突</span><strong>{{ store.stationTemplatePreview.conflict_count }}</strong></article>
          <article class="danger"><span>阻断</span><strong>{{ store.stationTemplatePreview.blocking_count }}</strong></article>
        </div>
        <div v-if="store.stationTemplatePreview.issues.length" class="row-issues">
          <el-tag v-for="issue in store.stationTemplatePreview.issues" :key="`${issue.code}:${issue.message}`" :type="issueType(issue.severity)">
            {{ issue.message }}
          </el-tag>
        </div>
        <NcDataTable
          v-loading="store.previewLoading"
          table-id="rail-base-station-template-preview"
          route-key="/rail-transit/base-data"
          :data="stationTemplateRows"
          :columns="stationTemplateColumns"
          height="420px"
          empty-text="模板中没有可预览的线路节点"
        >
          <template #cell-selected="{ row }">
            <el-checkbox
              :model-value="isStationTemplateRowSelected(row)"
              :disabled="isStationTemplateRowDisabled(row)"
              @change="(checked: boolean) => toggleTemplateRow(row, checked)"
            />
          </template>
          <template #cell-node_type="{ row }"><el-tag :type="stationNodeTypeTag(row.node_type)">{{ stationNodeTypeLabel(row.node_type) }}</el-tag></template>
          <template #cell-action="{ row }"><el-tag :type="row.action === 'conflict' ? 'danger' : row.action === 'create' ? 'success' : 'info'">{{ row.action }}</el-tag></template>
          <template #cell-issues="{ row }">
            <div class="row-issues">
              <el-tag v-for="issue in row.issues" :key="`${row.row_number}:${issue.code}`" :type="issueType(issue.severity)">{{ issue.message }}</el-tag>
              <span v-if="!row.issues.length">--</span>
            </div>
          </template>
        </NcDataTable>
      </div>
      <template #footer>
        <el-button @click="stationTemplateDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!canApplyStationTemplatePreview() || saving"
          @click="applyStationTemplateToDraft"
        >应用到当前草稿</el-button>
      </template>
    </el-dialog>
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
.source-summary { grid-template-columns: repeat(4, minmax(130px, 1fr)); }
.template-summary { grid-template-columns: repeat(5, minmax(120px, 1fr)); }
.preview-filter { margin-bottom: 12px; }
.preview-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.apply-controls { display: flex; align-items: center; gap: 12px; }
.operation-table, .change-table { margin-top: 16px; }
.issue-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.row-issues { display: flex; flex-wrap: wrap; gap: 5px; }
.preview-dialog { display: grid; gap: 12px; }
.source-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.inline-file-button { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; color: var(--nc-text-primary); background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 6px; cursor: pointer; }
.inline-file-button input { display: none; }
.compact-pair { display: grid; grid-template-columns: minmax(58px, 0.7fr) minmax(115px, 1.3fr); gap: 8px; align-items: center; min-width: 190px; }
.inline-checks { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.field-error :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--nc-danger) inset; }
@media (max-width: 1360px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .source-summary, .template-summary { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
  .filter-bar { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 900px) {
  .page-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { justify-content: flex-start; }
  .summary-grid, .source-summary, .template-summary { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .filter-bar { grid-template-columns: 1fr; }
}
</style>
