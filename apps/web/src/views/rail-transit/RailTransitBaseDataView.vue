<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Download, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { downloadBackendResource } from '../../platform/runtime'
import {
  getStationConflictPreview,
  preflightStationDeletion,
  stationTemplateDownloadRequest,
  stationTemplateExportDownloadRequest,
} from '../../api/railTransitBaseData'
import {
  exportTracksideApBase,
  exportTracksideApImportIssues,
  exportTracksideApRenameCommands,
} from '../../api/tracksideApBusiness'
import { isFeatureEnabled } from '../../features'

import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import TracksideApPlanningTab from '../../components/rail-transit/base-data/TracksideApPlanningTab.vue'
import { useRailTransitBaseDataStore } from '../../stores/railTransitBaseData'
import { useTaskStore } from '../../stores/tasks'
import type {
  DataQualityEntityGroup,
  DataQualityIssue,
  BaseDataClearPreview,
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
  SectionGenerationPreviewItem,
  Station,
  StationConflictGroup,
  StationDeletePreflightItem,
  StationSourceCandidate,
  StationSourceProcessingStrategy,
  StationTemplateSectionPreviewRow,
  StationTemplatePreviewRow,
  TracksideAp,
  Train,
  VehicleMr,
} from '../../types/railTransitBaseData'
import type { TracksideApPlanRow } from '../../types/tracksideApBusiness'
import { activeTaskStatuses } from '../../utils/taskStatus'
import {
  groupStationOrderConflicts,
  MANUAL_STATION_FIELDS,
  overwriteStationFromSource,
  overwriteStationFromStation,
  stationOverwriteDiffs,
  stationOverwriteDiffsFromStation,
  stationCombinationErrors,
  type StationFieldDiff,
} from './stationConflictDraft'

const store = useRailTransitBaseDataStore()
const route = useRoute()
const router = useRouter()
const { confirm, confirmChoice } = useConfirm()
const userSelectedExport = useUserSelectedExport()
const taskStore = useTaskStore()
const activeTaskStateSet = new Set(activeTaskStatuses)
const apBaseTaskTypes = new Set([
  'web_export_trackside_ap_base_xlsx',
  'web_export_trackside_ap_rename_commands',
])
type BaseDataEditState = 'LOCKED' | 'UNLOCKED_CLEAN' | 'UNLOCKED_DIRTY' | 'VALIDATING' | 'SAVING' | 'SAVE_FAILED'
interface BaseDataDraft {
  metadata: {
    line_name: string
    system_type: string
    network_domain: string
    main_path_code: string
    increasing_direction_name: string
    decreasing_direction_name: string
    increasing_direction_line_side: string
    decreasing_direction_line_side: string
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
interface StationReferencePatch {
  entityType: 'section' | 'trackside_ap'
  entityId: string
  field: string
  before: unknown
  after: unknown
}
interface StationCombinationDiff {
  field: string
  current: unknown
  proposed: unknown
}
const editState = ref<BaseDataEditState>('LOCKED')
const pendingChanges = ref<Record<string, BaseDataChange>>({})
const baselines = new Map<string, Record<string, unknown>>()
const stationReferencePatches = new Map<string, StationReferencePatch[]>()
const serverSnapshot = ref<BaseDataDraft | null>(null)
const editingDraft = ref<BaseDataDraft | null>(null)
const planningDraft = ref<TracksideApPlanRow[] | null>(null)
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
const clearAllDialogVisible = ref(false)
const clearAllPreview = ref<BaseDataClearPreview | null>(null)
const clearAllLoading = ref(false)
const stationTemplateDialogVisible = ref(false)
const sectionGenerationDialogVisible = ref(false)
const apImportDialogVisible = ref(false)
const tracksideApImportInput = ref<HTMLInputElement | null>(null)
const apBaseTaskId = ref('')
const apBaseTaskRunning = computed(() => taskStore.tasks.some(
  (item) => apBaseTaskTypes.has(item.type) && activeTaskStateSet.has(item.status),
))
const selectedStationSourceIds = ref<string[]>([])
const stationSourceStrategies = ref<Record<string, StationSourceProcessingStrategy>>({})
const stationSourceTargets = ref<Record<string, string>>({})
const stationTable = ref<{ clearSelection: () => void; toggleRowSelection: (row: Station, selected?: boolean) => void } | null>(null)
const selectedStationIds = ref<string[]>([])
const stationDeletePreflightVisible = ref(false)
const stationDeletePreflightItems = ref<StationDeletePreflightItem[]>([])
const stationDeletePreflightLoading = ref(false)
const stationConflictDrawerVisible = ref(false)
const stationConflictLoading = ref(false)
const backendStationConflictGroups = ref<StationConflictGroup[]>([])
const stationMergeDialogVisible = ref(false)
const stationMergeTargetId = ref('')
const stationMergeMemberIds = ref<string[]>([])
const stationMergeNameSourceId = ref('')
const stationMergeCodeSourceId = ref('')
const stationMergeOrderSourceId = ref('')
const stationMergeOrderConfirmed = ref(false)
const stationMergeRemarks = ref(false)
const stationMergeSourceInfo = ref(true)
const stationOverwriteDialogVisible = ref(false)
const stationOverwriteCandidateId = ref('')
const stationOverwriteSourceStationId = ref('')
const stationOverwriteTargetId = ref('')
const stationOverwriteManualFields = ref<string[]>([])
const selectedTemplateRows = ref<number[]>([])
const selectedTemplateSectionRows = ref<number[]>([])
const selectedSectionGenerationIds = ref<string[]>([])
const decisionSelections = ref<Record<string, MergeFieldDecision['action'] | ''>>({})
const mergeRows = computed(() => {
  const rows = store.importPreview?.merge_plan?.items || []
  if (previewFilter.value === 'all') return rows
  if (previewFilter.value === 'WARNING') {
    return rows.filter((row) => row.issues.some((issue) => issue.severity === 'warning'))
  }
  return rows.filter((row) => row.result === previewFilter.value)
})
const previewImportableCount = computed(
  () => store.importPreview?.merge_plan?.summary.importable_count || 0,
)
const previewProblemRows = computed(() => (
  (store.importPreview?.merge_plan?.items || [])
    .filter((item) => ['CONFLICT', 'INVALID'].includes(item.result))
    .flatMap((item) => {
      const identity = item.source_identity
      const issues = [...item.issues]
      if (item.result === 'CONFLICT' && !issues.some((issue) => issue.severity === 'error')) {
        issues.push({
            severity: 'error',
            code: 'identity_conflict',
            entity_type: 'ap',
            entity_id: '',
            entity_name: '',
            row_number: item.row_number,
            field_name: '',
            original_value: '',
            message: item.conflict_summary || '该行存在身份冲突',
            suggested_action: '核对 AP MAC 与点位编号',
            blocking: true,
        })
      }
      return issues.map((issue) => ({
        row_number: item.row_number,
        result: item.result,
        severity: issue.severity,
        code: issue.code,
        field_name: issue.field_name,
        original_value: issue.original_value,
        message: issue.message,
        suggested_action: issue.suggested_action,
        ap_name: String(identity.ap_name || ''),
        point_code: String(identity.ap_point_code || ''),
        ap_mac: String(identity.ap_mac || ''),
      }))
    })
))
const stationSourceCandidates = computed(() => store.stationSourcePreview?.candidates || [])
const localStationConflictGroups = computed(() => groupStationOrderConflicts(stationRows.value))
const stationConflictGroups = computed(() => editingDraft.value
  ? localStationConflictGroups.value
  : backendStationConflictGroups.value.length
    ? backendStationConflictGroups.value
    : localStationConflictGroups.value)
const nonOrderSaveIssues = computed(() => saveIssues.value.filter((issue) => issue.code !== 'station_order_duplicate'))
const selectedStations = computed(() => stationRows.value.filter((station) => selectedStationIds.value.includes(station.id)))
const stationMergeMembers = computed(() => stationRows.value.filter((station) => stationMergeMemberIds.value.includes(station.id)))
const stationMergeTarget = computed(() => stationMergeMembers.value.find((station) => station.id === stationMergeTargetId.value) || null)
const stationMergeSources = computed(() => stationMergeMembers.value.filter((station) => station.id !== stationMergeTargetId.value))
const stationMergeOrderConflict = computed(() => new Set(stationMergeMembers.value.map((station) => station.sort_order)).size > 1)
const stationCombinationDiffRows = computed<StationCombinationDiff[]>(() => {
  const target = stationMergeTarget.value
  if (!target) return []
  const nameSource = stationMergeMembers.value.find((row) => row.id === stationMergeNameSourceId.value) || target
  const codeSource = stationMergeMembers.value.find((row) => row.id === stationMergeCodeSourceId.value) || target
  const orderSource = stationMergeMembers.value.find((row) => row.id === stationMergeOrderSourceId.value) || target
  const proposedRemark = stationMergeRemarks.value
    ? [...new Set(stationMergeMembers.value.map((row) => row.remark.trim()).filter(Boolean))].join('；')
    : target.remark
  return [
    { field: '名称', current: target.name, proposed: nameSource.name },
    { field: '节点编码', current: target.code, proposed: codeSource.code },
    { field: '主线顺序', current: target.sort_order, proposed: orderSource.sort_order },
    { field: '人工备注', current: target.remark, proposed: proposedRemark },
    { field: '保留身份', current: `${target.id} / ${target.node_uid}`, proposed: `${target.id} / ${target.node_uid}` },
  ]
})
const stationMergeErrors = computed(() => {
  if (!stationMergeTarget.value) return ['请选择保留目标站点']
  const errors = stationCombinationErrors(stationMergeTarget.value, stationMergeSources.value)
  const selfLoop = stationCombinationSelfLoopError(stationMergeTarget.value, stationMergeSources.value)
  if (selfLoop) errors.push(selfLoop)
  if (stationMergeOrderConflict.value && !stationMergeOrderConfirmed.value) {
    errors.push('来源站点主线顺序不同，请明确选择保留的主线顺序')
  }
  return errors
})
const stationOverwriteCandidate = computed(() => stationSourceCandidates.value.find((candidate) => candidate.candidate_id === stationOverwriteCandidateId.value) || null)
const stationOverwriteSourceStation = computed(() => stationRows.value.find((station) => station.id === stationOverwriteSourceStationId.value) || null)
const stationOverwriteTarget = computed(() => stationRows.value.find((station) => station.id === stationOverwriteTargetId.value) || null)
const stationOverwriteDiffRows = computed<StationFieldDiff[]>(() => {
  if (!stationOverwriteTarget.value) return []
  if (stationOverwriteCandidate.value) return stationOverwriteDiffs(stationOverwriteTarget.value, stationOverwriteCandidate.value)
  if (stationOverwriteSourceStation.value) return stationOverwriteDiffsFromStation(stationOverwriteTarget.value, stationOverwriteSourceStation.value)
  return []
})
const stationTemplateRows = computed(() => store.stationTemplatePreview?.rows || [])
const stationTemplateSectionRows = computed(() => store.stationTemplatePreview?.section_rows || [])
const sectionGenerationRows = computed(() => store.sectionGenerationPreview?.generated_sections || [])
const sectionNodeOptions = computed(() => {
  const rows = editingDraft.value?.stations ?? store.stations
  const options: Array<{ display_label: string; persisted_name: string; uid: string; type: 'station' | 'terminal_endpoint' }> = rows
    .filter((station) => station.enabled)
    .map((station) => ({
      display_label: station.name,
      persisted_name: station.name,
      uid: station.node_uid,
      type: 'station',
    }))
  for (const station of rows) {
    if (!station.enabled || !station.is_line_terminal || !station.terminal_extension_enabled) continue
    const ordered = rows
      .filter((item) => item.enabled && item.participates_in_direction && item.node_type === 'station' && item.path_code === station.path_code && item.sort_order !== null)
      .sort((left, right) => Number(left.sort_order) - Number(right.sort_order))
    const side = ordered[0]?.node_uid === station.node_uid
      ? 'low'
      : ordered.at(-1)?.node_uid === station.node_uid
        ? 'high'
        : ''
    if (!side) continue
    const persistedName = station.terminal_endpoint_label || '端点'
    options.push({
      display_label: `${persistedName}（${station.name}端）`,
      persisted_name: persistedName,
      uid: `endpoint:${station.path_code}:${side}`,
      type: 'terminal_endpoint',
    })
  }
  return options
})
const issueCodeStats = computed(() => Object.entries(store.issueCodeCounts).sort((left, right) => right[1] - left[1]))
function summaryMetric(value: number | undefined): number | string {
  if (store.summary) return value ?? 0
  return store.summaryError ? '加载失败' : '—'
}
const summaryCards = computed(() => [
  ['站点', summaryMetric(store.summary?.station_count), 'normal'],
  ['普通车站', summaryMetric(store.summary?.normal_station_count), 'normal'],
  ['特殊节点', summaryMetric(store.summary?.special_node_count), 'warning'],
  ['来源待确认', summaryMetric(store.summary?.source_pending_count), 'warning'],
  ['来源冲突', summaryMetric(store.summary?.source_conflict_count), 'danger'],
  ['来源失效', summaryMetric(store.summary?.source_stale_count), 'warning'],
  ['区间', summaryMetric(store.summary?.section_count), 'normal'],
  ['轨旁 AP', summaryMetric(store.summary?.ap_count), 'normal'],
  ['列车', summaryMetric(store.summary?.train_count), 'normal'],
  ['车载 MR', summaryMetric(store.summary?.mr_count), 'normal'],
  ['缺失位置 AP', summaryMetric(store.summary?.missing_location_ap_count), 'warning'],
  ['无效里程', summaryMetric(store.summary?.invalid_mileage_count), 'danger'],
  ['重复 AP MAC', summaryMetric(store.summary?.duplicate_ap_mac_count), 'danger'],
  ['重复静态 IP', summaryMetric(store.summary?.duplicate_static_ip_count), 'danger'],
  ['未关联列车 MR', summaryMetric(store.summary?.unbound_mr_count), 'warning'],
])

const stationColumns: NcTableColumn<Station>[] = [
  { key: 'sort_order', label: '主线顺序', valueType: 'number', width: 105, displayValue: (row) => row.sort_order ?? '--' },
  { key: 'code', label: '节点编码', minWidth: 110, displayValue: (row) => display(row.code) },
  { key: 'name', label: '节点名称', valueType: 'name', minWidth: 170 },
  { key: 'node_type', label: '节点类型', valueType: 'status', width: 120, displayValue: (row) => stationNodeTypeLabel(row.node_type) },
  { key: 'path_code', label: '所属路径', minWidth: 115, displayValue: (row) => display(row.path_code) },
  { key: 'participates_in_direction', label: '参与方向', width: 105, displayValue: (row) => boolText(row.participates_in_direction) },
  { key: 'center_mileage_text', label: '中心里程', valueType: 'mileage', minWidth: 145, displayValue: (row) => display(row.center_mileage_text) },
  { key: 'structure_platform', label: '结构 / 站台', minWidth: 160, displayValue: (row) => `${structureTypeLabel(row.structure_type)} / ${platformLayoutLabel(row.platform_layout)}` },
  { key: 'terminals', label: '终点属性', minWidth: 180, displayValue: (row) => terminalSummary(row) },
  { key: 'track_facilities', label: '轨道设施', minWidth: 220, displayValue: (row) => trackFacilitiesSummary(row) },
  { key: 'turnback', label: '折返能力 / 方向', minWidth: 170, displayValue: (row) => turnbackSummary(row) },
  { key: 'terminal_extension', label: '端点延伸区间', minWidth: 300, displayValue: (row) => terminalExtensionSummary(row) },
  { key: 'source_device_count', label: '来源设备数', valueType: 'number', width: 120 },
  { key: 'source_sync_status', label: '来源状态', valueType: 'status', width: 115, displayValue: (row) => sourceSyncLabel(row.source_sync_status) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 160, displayValue: (row) => display(row.remark), alignmentReason: 'long-text' },
]
const sectionColumns: NcTableColumn<Section>[] = [
  { key: 'name', label: '区间名称', valueType: 'name', minWidth: 200 },
  { key: 'section_kind', label: '类型', valueType: 'status', minWidth: 120, displayValue: (row) => sectionKindLabel(row.section_kind) },
  { key: 'path_code', label: '所属路径', minWidth: 110, displayValue: (row) => display(row.path_code) },
  { key: 'start_station', label: '起始节点', minWidth: 170, displayValue: (row) => display(row.start_station) },
  { key: 'end_station', label: '终到节点', minWidth: 170, displayValue: (row) => display(row.end_station) },
  { key: 'line_direction', label: '线路方向', minWidth: 120, displayValue: (row) => display(row.line_direction || row.line_side) },
  { key: 'section_mileage_range', label: '区间里程范围', valueType: 'mileage', minWidth: 340, displayValue: (row) => sectionMileageRange(row) },
  { key: 'ap_count', label: 'AP 数量', valueType: 'number', width: 110 },
  { key: 'mileage_range', label: 'AP 里程统计', valueType: 'mileage', minWidth: 160, displayValue: (row) => mileageRange(row.mileage_min, row.mileage_max) },
  { key: 'source_kind', label: '来源', valueType: 'status', width: 120, displayValue: (row) => sectionSourceLabel(row) },
  { key: 'enabled', label: '状态', valueType: 'status', width: 90, displayValue: (row) => row.enabled ? '启用' : '停用' },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, displayValue: (row) => display(row.remark), alignmentReason: 'long-text' },
]
const apColumns: NcTableColumn<TracksideAp>[] = [
  { key: 'name', label: 'AP 名称', valueType: 'name', minWidth: 150, fixed: 'left', displayValue: (row) => row.runtime.fit_ap_name || row.name || row.point_code || '--' },
  { key: 'point_code', label: '点位编号', minWidth: 120, displayValue: (row) => display(row.point_code) },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', minWidth: 150 },
  { key: 'management_ip', label: '管理 IP', valueType: 'ip', minWidth: 125, displayValue: (row) => display(row.management_ip) },
  { key: 'station', label: '站点', minWidth: 130, displayValue: (row) => display(row.station) },
  { key: 'section', label: '区间', minWidth: 170, displayValue: (row) => display(row.section) },
  { key: 'mileage', label: '里程', valueType: 'mileage', minWidth: 120, displayValue: (row) => row.mileage.normalized || row.mileage.raw || '--' },
  { key: 'direction', label: '行车方向', width: 110, displayValue: (row) => display(row.direction) },
  { key: 'remark', label: '备注', valueType: 'description', minWidth: 180, alignmentReason: 'long-text', displayValue: (row) => display(row.remark) },
  { key: 'fit_ap_status', label: 'FIT-AP 状态', valueType: 'status', width: 120 },
  { key: 'optical_status', label: '光衰', valueType: 'status', width: 105 },
  { key: 'source_file', label: '数据来源', align: 'left', alignmentReason: 'path', minWidth: 150, showOverflowTooltip: true },
  { key: 'issues', label: '问题', valueType: 'status', width: 90 },
  { key: 'actions', label: '操作', valueType: 'actions', width: 190, fixed: 'right', hideable: false },
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
  { key: 'ap_point_code', label: '点位编号', minWidth: 130, displayValue: (row) => display(row.source_values.ap_point_code) },
  { key: 'ap_mac', label: 'AP MAC', valueType: 'mac', minWidth: 150, displayValue: (row) => display(row.source_identity.ap_mac) },
  { key: 'station_name', label: '归属站点', minWidth: 130, displayValue: (row) => display(row.source_values.station_name) },
  { key: 'section_name', label: '归属区间', minWidth: 210, displayValue: (row) => display(row.source_values.section_name) },
  { key: 'direction', label: '线路方向', width: 100, displayValue: (row) => display(row.source_values.direction) },
  { key: 'uplink_switch', label: '室内交换机', minWidth: 140, displayValue: (row) => display(row.source_values.uplink_switch) },
  { key: 'uplink_port', label: '接口名称', minWidth: 120, displayValue: (row) => display(row.source_values.uplink_port) },
  { key: 'matched_entity_name', label: '正式实体', valueType: 'name', minWidth: 170, displayValue: (row) => display(row.matched_entity_name) },
  { key: 'match_method', label: '匹配方式', width: 140 },
  { key: 'field_diffs', label: '字段差异', valueType: 'description', minWidth: 320, alignmentReason: 'long-text', displayValue: (row) => diffSummary(row.field_diffs), showOverflowTooltip: true },
  { key: 'issues', label: '问题', valueType: 'error', minWidth: 240, alignmentReason: 'long-text', displayValue: (row) => row.issues.map((issue) => issue.message).join('；') || display(row.conflict_summary), showOverflowTooltip: true },
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
  { key: 'source_order', label: '解析编号', valueType: 'number', width: 100, displayValue: (row) => row.source_order ?? '--' },
  { key: 'code', label: '节点编码', width: 100, displayValue: (row) => display(row.code) },
  { key: 'canonical_name', label: '规范站名', valueType: 'name', minWidth: 150, displayValue: (row) => display(row.canonical_name || row.canonical_station_name || row.name) },
  { key: 'node_type', label: '类型', valueType: 'status', width: 110, displayValue: (row) => stationNodeTypeLabel(row.node_type) },
  { key: 'participates_in_direction', label: '参与主线', valueType: 'status', width: 100, displayValue: (row) => row.participates_in_direction ? '是' : '否' },
  { key: 'order_parse_method', label: '解析方式', width: 130 },
  { key: 'parse_confidence', label: '可信度', valueType: 'status', width: 130 },
  { key: 'sort_order', label: '建议顺序', valueType: 'number', width: 105, displayValue: (row) => row.sort_order ?? '--' },
  { key: 'source_device_count', label: '来源设备数', valueType: 'number', width: 120 },
  { key: 'matched_station_name', label: '现有站点', valueType: 'name', minWidth: 150, displayValue: (row) => display(row.matched_station_name) },
  { key: 'match_status', label: '匹配依据', valueType: 'status', width: 150, displayValue: (row) => sourceMatchLabel(row.match_status) },
  { key: 'processing_strategy', label: '处理方式', valueType: 'actions', minWidth: 170, hideable: false },
  { key: 'suggested_action', label: '建议动作', width: 130 },
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
const stationTemplateSectionColumns: NcTableColumn<StationTemplateSectionPreviewRow>[] = [
  { key: 'selected', label: '勾选', width: 72, hideable: false },
  { key: 'row_number', label: '行号', valueType: 'number', width: 80 },
  { key: 'section_code', label: '区间编码', minWidth: 130, displayValue: (row) => display(row.section_code) },
  { key: 'name', label: '区间名称', valueType: 'name', minWidth: 210 },
  { key: 'section_kind', label: '类型', valueType: 'status', width: 120, displayValue: (row) => sectionKindLabel(row.section_kind) },
  { key: 'path_code', label: '所属路径', width: 110 },
  { key: 'line_direction', label: '线路方向', width: 110, displayValue: (row) => display(row.line_direction) },
  { key: 'start_station', label: '起始节点', minWidth: 160 },
  { key: 'end_station', label: '终到节点', minWidth: 160 },
  { key: 'action', label: '动作', valueType: 'status', width: 105 },
  { key: 'issues', label: '问题', valueType: 'description', minWidth: 220, alignmentReason: 'long-text', displayValue: (row) => row.issues.map((item) => item.message).join('；') || '--' },
]
const sectionGenerationColumns: NcTableColumn<SectionGenerationPreviewItem>[] = [
  { key: 'selected', label: '勾选', width: 72, hideable: false },
  { key: 'name', label: '区间名称', valueType: 'name', minWidth: 220, displayValue: (row) => generationSection(row)?.name || '--' },
  { key: 'section_kind', label: '类型', valueType: 'status', width: 120, displayValue: (row) => sectionKindLabel(generationSection(row)?.section_kind || 'manual') },
  { key: 'path_code', label: '所属路径', width: 110, displayValue: (row) => generationSection(row)?.path_code || '--' },
  { key: 'line_direction', label: '线路方向', width: 110, displayValue: (row) => generationSection(row)?.line_direction || '--' },
  { key: 'start_station', label: '起始节点', minWidth: 170, displayValue: (row) => generationSection(row)?.start_station || '--' },
  { key: 'end_station', label: '终到节点', minWidth: 170, displayValue: (row) => generationSection(row)?.end_station || '--' },
  { key: 'section_mileage_range', label: '区间里程范围', valueType: 'mileage', minWidth: 170, displayValue: (row) => generationSection(row) ? sectionMileageRange(generationSection(row) as Section) : '未生成' },
  { key: 'result', label: '处理结果', valueType: 'status', width: 110 },
  { key: 'issues', label: '问题', valueType: 'description', minWidth: 240, alignmentReason: 'long-text', displayValue: (row) => row.issues.map((item) => item.message).join('；') || '--' },
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

const stationEditColumns = computed<NcTableColumn<Station>[]>(() => [
  ...(locked.value ? [] : [{ key: 'selection', label: '选择', type: 'selection', width: 48, hideable: false } as NcTableColumn<Station>]),
  ...stationColumns,
  { key: 'edit_actions', label: '操作', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
])
const sectionEditColumns: NcTableColumn<Section>[] = [
  ...sectionColumns,
  { key: 'edit_actions', label: '操作', valueType: 'actions', width: 160, fixed: 'right', hideable: false },
]
const mrEditColumns: NcTableColumn<VehicleMr>[] = [
  ...mrColumns,
  { key: 'edit_actions', label: '维护', valueType: 'actions', width: 90, fixed: 'right', hideable: false },
]

watch(stationRows, async (rows) => {
  const valid = new Set(rows.map((row) => row.id))
  selectedStationIds.value = selectedStationIds.value.filter((id) => valid.has(id))
  await nextTick()
  for (const row of rows) {
    if (selectedStationIds.value.includes(row.id)) {
      stationTable.value?.toggleRowSelection?.(row, true)
    }
  }
})

watch(locked, (value) => {
  if (value) clearStationSelection()
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  window.addEventListener('beforeunload', beforeUnload)
  store.startPolling()
  void store.refreshImportGovernance().catch(() => undefined)
  void taskStore.refresh().then(() => {
    apBaseTaskId.value = taskStore.tasks.find(
      (item) => apBaseTaskTypes.has(item.type) && activeTaskStateSet.has(item.status),
    )?.id || ''
  })
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
  stationReferencePatches.clear()
  fieldErrors.value = {}
  serverSnapshot.value = null
  editingDraft.value = null
  clearStationSelection()
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
  stationReferencePatches.clear()
  serverSnapshot.value = null
  editingDraft.value = null
  clearStationSelection()
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

async function openClearAllDialog(): Promise<void> {
  if (locked.value) {
    ElMessage.warning('请先解锁基础资料，再执行清空全部')
    return
  }
  if (dirty.value) {
    ElMessage.warning('请先保存或放弃当前未保存修改，再执行清空全部')
    return
  }
  clearAllLoading.value = true
  try {
    clearAllPreview.value = await store.previewClearAll()
    clearAllDialogVisible.value = true
  } catch (cause) {
    ElMessage.error(message(cause, '清空影响数量加载失败'))
  } finally {
    clearAllLoading.value = false
  }
}

async function executeClearAll(): Promise<void> {
  if (!clearAllPreview.value || locked.value || dirty.value || saving.value) return
  clearAllLoading.value = true
  try {
    const result = await store.clearAll(clearAllPreview.value)
    pendingChanges.value = {}
    planningDirty.value = false
    planningDraft.value = null
    saveIssues.value = []
    fieldErrors.value = {}
    baselines.clear()
    serverSnapshot.value = null
    editingDraft.value = null
    clearAllDialogVisible.value = false
    editState.value = 'LOCKED'
    await Promise.all([
      store.manualRefresh(),
      store.refreshEditSession(),
      planningTab.value?.reload(true),
    ])
    store.startPolling()
    ElMessage.success(`已清空 ${result.deleted_station_count} 个站点、${result.deleted_section_count} 个区间，并解除 ${result.unlinked_trackside_ap_count} 条轨旁 AP 关联`)
  } catch (cause) {
    ElMessage.error(message(cause, '清空失败，数据库事务已回滚'))
  } finally {
    clearAllLoading.value = false
  }
}

async function beforeTabLeave(next: string, current: string): Promise<boolean> {
  if (next === current) return true
  if (saving.value) return false
  return !dirty.value || confirmUnsavedChanges()
}

async function saveAllChanges(successMessage = ''): Promise<boolean> {
  if (!store.editSession || saving.value || !dirty.value) return !dirty.value
  const changes = Object.values(pendingChanges.value)
  if (planningDirty.value && planningDraft.value) {
    changes.push({
      entity_type: 'trackside_ap_plan',
      action: 'replace',
      values: { rows: planningDraft.value },
    })
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
    const validationWarnings = validation.issues.filter((issue) => !issue.blocking)
    if (validationWarnings.length) ElMessage.warning(`存在 ${validationWarnings.length} 条非阻断提示，将继续保存`)
    editState.value = 'SAVING'
    const result = await store.saveChanges(changes)
    pendingChanges.value = {}
    planningDirty.value = false
    saveIssues.value = []
    fieldErrors.value = {}
    baselines.clear()
    stationReferencePatches.clear()
    await Promise.all([store.manualRefresh(), planningTab.value?.reload(true)])
    editState.value = 'LOCKED'
    serverSnapshot.value = null
    editingDraft.value = null
    store.startPolling()
    ElMessage.success(
      successMessage
      || `基础资料已保存：新增 ${result.created_count}，更新 ${result.updated_count}，删除 ${result.deleted_count}${result.warnings.length ? `，提示 ${result.warnings.length}` : ''}`,
    )
    return true
  } catch (cause) {
    editState.value = 'SAVE_FAILED'
    ElMessage.error(message(cause, '基础资料保存失败，修改已保留'))
    return false
  }
}

async function saveTracksideApPlanning(): Promise<void> {
  await saveAllChanges('轨旁 AP 规划已保存。')
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
  stationReferencePatches.clear()
  const snapshot: BaseDataDraft = {
    metadata: {
      line_name: store.summary?.line_name || '',
      system_type: store.summary?.project_type || '',
      network_domain: store.summary?.network_type || 'default',
      main_path_code: store.summary?.main_path_code || 'MAIN',
      increasing_direction_name: store.summary?.increasing_direction_name || '上行',
      decreasing_direction_name: store.summary?.decreasing_direction_name || '下行',
      increasing_direction_line_side: store.summary?.increasing_direction_line_side || '右线',
      decreasing_direction_line_side: store.summary?.decreasing_direction_line_side || '左线',
      increasing_direction_leading_end: store.summary?.increasing_direction_leading_end || 'unknown',
      station_source_group_name: store.summary?.station_source_group_name || '车站',
      station_source_field: store.summary?.station_source_field || 'station',
      remark: store.summary?.remark || '',
    },
    stations: cloneDto(store.stations),
    sections: cloneDto(store.sections.map((section) => defaultSection(section))),
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
  clearStationSelection()
}

function handlePlanningChange(rows: TracksideApPlanRow[], changed: boolean): void {
  planningDraft.value = rows
  planningDirty.value = changed
  updateEditState()
}

function markMetadata(): void {
  if (!editingDraft.value || locked.value) return
  recordChange('site_metadata', 'current', metadataValues(editingDraft.value.metadata))
}

function handleLineSideMappingChange(): void {
  if (!editingDraft.value || locked.value) return
  markMetadata()
  for (const section of editingDraft.value.sections) {
    if (section.manual_override_fields?.includes('line_side')) continue
    const expected = sectionLineSide(section)
    if (expected && section.line_side !== expected) {
      section.line_side = expected
      markSection(section)
    }
  }
  syncAllAutomaticApLineSides()
}

function markStation(row: Station): void { recordChange('station', row.id, stationValues(row)) }
function markSection(row: Section): void { recordChange('section', row.id, sectionValues(row)) }
const sectionGeneratorFields = new Set([
  'name', 'section_kind', 'path_code', 'start_node_type', 'start_node_uid', 'start_station',
  'end_node_type', 'end_node_uid', 'end_station', 'direction_role', 'line_direction', 'line_side', 'enabled',
  'section_mileage_start_m', 'section_mileage_end_m', 'section_mileage_open_end', 'section_mileage_source',
])
function markSectionField(row: Section, ...fields: string[]): void {
  if (row.auto_generated) {
    const overrides = new Set(row.manual_override_fields || [])
    for (const field of fields) if (sectionGeneratorFields.has(field)) overrides.add(field)
    row.manual_override_fields = [...overrides].sort()
  }
  markSection(row)
}
function markSectionMileage(row: Section, field: 'section_mileage_start_m' | 'section_mileage_end_m'): void {
  row.section_mileage_source = 'manual'
  markSectionField(row, field, 'section_mileage_source')
}
function handleSectionMileageOpenEnd(row: Section, openEnd: boolean): void {
  row.section_mileage_open_end = openEnd
  if (openEnd) row.section_mileage_end_m = null
  row.section_mileage_source = 'manual'
  markSectionField(row, 'section_mileage_open_end', 'section_mileage_end_m', 'section_mileage_source')
}
function handleSectionKindChange(row: Section): void {
  if (row.section_kind !== 'terminal_extension' && row.section_mileage_open_end) {
    row.section_mileage_open_end = false
    markSectionField(row, 'section_kind', 'section_mileage_open_end')
    return
  }
  markSectionField(row, 'section_kind')
}
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
  if (entityType === 'station') {
    await openStationDeletePreflight([row.id])
    return
  }
  const accepted = await confirm({ type: 'DANGER', title: '标记删除', message: '该数据将在点击“保存”后删除；存在业务引用时后端会拒绝。是否继续？', confirmText: '标记删除' })
  if (!accepted) return
  const baseline = baselines.get(key) || valuesFor(entityType, row)
  pendingChanges.value[key] = { entity_type: entityType, action: 'delete', entity_id: row.id, values: withOriginalIdentity(entityType, baseline, baseline) }
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function handleStationSelection(rows: Station[]): void {
  if (locked.value) {
    selectedStationIds.value = []
    return
  }
  selectedStationIds.value = rows.map((row) => row.id)
}

function clearStationSelection(): void {
  selectedStationIds.value = []
  stationTable.value?.clearSelection?.()
}

async function selectConflictStations(): Promise<void> {
  if (locked.value) return
  const ids = new Set(localStationConflictGroups.value.flatMap((group) => group.stations.map((station) => station.station_id)))
  selectedStationIds.value = [...ids]
  await nextTick()
  stationTable.value?.clearSelection?.()
  for (const row of stationRows.value) {
    if (ids.has(row.id)) stationTable.value?.toggleRowSelection?.(row, true)
  }
}

async function deleteSelectedStations(): Promise<void> {
  if (locked.value || !selectedStationIds.value.length) return
  await openStationDeletePreflight(selectedStationIds.value)
}

async function openStationDeletePreflight(stationIds: string[]): Promise<void> {
  if (locked.value || !editingDraft.value || !store.editSession) return
  const selected = stationRows.value.filter((row) => stationIds.includes(row.id))
  const newRows = selected.filter((row) => row.id.startsWith('new:'))
  const localItems: StationDeletePreflightItem[] = newRows.map((row) => {
    const sectionStartCount = editingDraft.value?.sections.filter((item) => item.start_station === row.name).length || 0
    const sectionEndCount = editingDraft.value?.sections.filter((item) => item.end_station === row.name).length || 0
    const apCount = editingDraft.value?.aps.filter((item) => item.station === row.name).length || 0
    const planCount = planningDraft.value?.filter(
      (item) => item.station_id === row.id || item.station_name === row.name,
    ).length || 0
    const totalCount = sectionStartCount + sectionEndCount + apCount + planCount
    const status: StationDeletePreflightItem['status'] = row.is_line_terminal ? 'BLOCKED' : totalCount ? 'REQUIRES_MERGE' : 'SAFE_DELETE'
    return {
      station_id: row.id,
      station_name: row.name,
      code: row.code,
      sort_order: row.sort_order,
      source_kind: row.source_kind,
      status,
      reason: row.is_line_terminal
        ? '线路端点不能直接删除'
        : totalCount
          ? '该未保存站点已被当前草稿引用，必须先合并或重新指向'
          : '该站点尚未保存，确认后只从当前草稿移除',
      is_manual: row.source_kind === 'manual',
      is_line_terminal: row.is_line_terminal,
      references: {
        section_start_count: sectionStartCount,
        section_end_count: sectionEndCount,
        ap_count: apCount,
        relation_count: 0,
        endpoint_extension_count: editingDraft.value?.sections.filter((item) => item.section_kind === 'terminal_extension' && [item.start_station, item.end_station].includes(row.name)).length || 0,
        plan_count: planCount,
        total_count: totalCount,
      },
    }
  })
  const persistedIds = selected.filter((row) => !row.id.startsWith('new:')).map((row) => row.id)
  if (!persistedIds.length) {
    stationDeletePreflightItems.value = localItems
    stationDeletePreflightVisible.value = true
    return
  }
  stationDeletePreflightLoading.value = true
  try {
    const result = await preflightStationDeletion({
      site_id: store.editSession.site_id,
      base_revision: store.editSession.base_revision,
      station_ids: persistedIds,
    })
    stationDeletePreflightItems.value = [...localItems, ...result.items]
    stationDeletePreflightVisible.value = true
  } catch (cause) {
    ElMessage.error(message(cause, '站点删除依赖预检失败'))
  } finally {
    stationDeletePreflightLoading.value = false
  }
}

function markStationDelete(row: Station): void {
  const key = changeKey('station', row.id)
  const baseline = baselines.get(key) || stationValues(row)
  pendingChanges.value[key] = {
    entity_type: 'station',
    action: 'delete',
    entity_id: row.id,
    values: withOriginalIdentity('station', baseline, baseline),
  }
}

function applySafeStationDeletes(): void {
  if (!editingDraft.value) return
  const safeIds = new Set(stationDeletePreflightItems.value.filter((item) => item.status === 'SAFE_DELETE').map((item) => item.station_id))
  if (!safeIds.size) {
    ElMessage.warning('没有可安全直接删除的站点；请先合并或重新指向')
    return
  }
  for (const row of editingDraft.value.stations) {
    if (!safeIds.has(row.id)) continue
    if (row.id.startsWith('new:')) {
      delete pendingChanges.value[changeKey('station', row.id)]
      baselines.delete(changeKey('station', row.id))
      removeDraftRow('station', row.id)
    } else {
      markStationDelete(row)
    }
  }
  pendingChanges.value = { ...pendingChanges.value }
  stationDeletePreflightVisible.value = false
  updateEditState()
  ElMessage.success(`已将 ${safeIds.size} 个无引用站点标记为待删除；尚未写入数据库`)
}

function undoSelectedStationChanges(): void {
  if (!editingDraft.value || locked.value) return
  const ids = new Set(selectedStationIds.value)
  for (const id of ids) {
    const key = changeKey('station', id)
    const change = pendingChanges.value[key]
    if (!change) continue
    if (id.startsWith('new:')) {
      removeDraftRow('station', id)
      baselines.delete(key)
      delete pendingChanges.value[key]
      continue
    }
    const baseline = baselines.get(key)
    const current = editingDraft.value.stations.find((row) => row.id === id)
    if (baseline && current) Object.assign(current, baseline)
    if (change.action === 'replace') {
      const sourceIds = (change.values.merge_source_ids as string[] | undefined) || []
      for (const sourceId of sourceIds) {
        if (editingDraft.value.stations.some((row) => row.id === sourceId)) continue
        const original = serverSnapshot.value?.stations.find((row) => row.id === sourceId)
        if (original) editingDraft.value.stations.push(cloneDto(original))
      }
      restoreStationReferencePatches(id)
    }
    delete pendingChanges.value[key]
  }
  pendingChanges.value = { ...pendingChanges.value }
  updateEditState()
}

function recordStationReferencePatch(
  stationId: string,
  entityType: StationReferencePatch['entityType'],
  entityId: string,
  row: Record<string, unknown>,
  field: string,
  nextValue: unknown,
): void {
  const before = row[field]
  if (JSON.stringify(before) === JSON.stringify(nextValue)) return
  const patches = stationReferencePatches.get(stationId) || []
  const existing = patches.find((patch) => patch.entityType === entityType && patch.entityId === entityId && patch.field === field)
  if (existing) {
    existing.after = cloneDto(nextValue)
  } else {
    patches.push({
      entityType,
      entityId,
      field,
      before: cloneDto(before),
      after: cloneDto(nextValue),
    })
  }
  stationReferencePatches.set(stationId, patches)
  row[field] = nextValue
}

function restoreStationReferencePatches(stationId: string): void {
  if (!editingDraft.value) return
  for (const patch of stationReferencePatches.get(stationId) || []) {
    const rows = patch.entityType === 'section' ? editingDraft.value.sections : editingDraft.value.aps
    const row = rows.find((item) => item.id === patch.entityId) as unknown as Record<string, unknown> | undefined
    if (!row || JSON.stringify(row[patch.field]) !== JSON.stringify(patch.after)) continue
    row[patch.field] = cloneDto(patch.before)
    const key = changeKey(patch.entityType, patch.entityId)
    if (pendingChanges.value[key]) {
      if (patch.entityType === 'section') markSection(row as unknown as Section)
      else markAp(row as unknown as TracksideAp)
    }
  }
  stationReferencePatches.delete(stationId)
}

function openStationCombination(memberIds = selectedStationIds.value): void {
  if (locked.value) return
  const members = stationRows.value.filter((station) => memberIds.includes(station.id))
  if (members.length < 2) {
    ElMessage.warning('至少选择两个站点才能合并')
    return
  }
  const target = members.find((station) => !station.id.startsWith('new:') && ['manual', 'template'].includes(station.source_kind))
    || members.find((station) => !station.id.startsWith('new:'))
  if (!target) {
    ElMessage.warning('合并必须保留一个已有正式站点的 id 和 node_uid')
    return
  }
  stationMergeMemberIds.value = members.map((station) => station.id)
  stationMergeTargetId.value = target.id
  stationMergeNameSourceId.value = target.id
  stationMergeCodeSourceId.value = target.id
  stationMergeOrderSourceId.value = target.id
  stationMergeOrderConfirmed.value = false
  stationMergeRemarks.value = false
  stationMergeSourceInfo.value = true
  stationMergeDialogVisible.value = true
}

function handleStationCombinationTargetChange(): void {
  stationMergeOrderSourceId.value = stationMergeTargetId.value
  stationMergeOrderConfirmed.value = false
}

function handleStationCombinationOrderSourceChange(): void {
  stationMergeOrderConfirmed.value = true
}

function stationCombinationSelfLoopError(target: Station, sources: Station[]): string {
  if (!editingDraft.value) return ''
  const sourceNames = new Set(sources.map((source) => source.name))
  const sourceUids = new Set(sources.map((source) => source.node_uid).filter(Boolean))
  const section = editingDraft.value.sections.find((row) => {
    const startName = sourceNames.has(row.start_station) ? target.name : row.start_station
    const endName = sourceNames.has(row.end_station) ? target.name : row.end_station
    const startUid = sourceUids.has(row.start_node_uid) ? target.node_uid : row.start_node_uid
    const endUid = sourceUids.has(row.end_node_uid) ? target.node_uid : row.end_node_uid
    return (startUid && startUid === endUid) || (startName && startName === endName)
  })
  return section ? `合并后区间“${section.name}”将形成自环` : ''
}

function applyStationCombination(): void {
  if (!editingDraft.value || !stationMergeTarget.value) return
  const target = stationMergeTarget.value
  const sources = stationMergeSources.value
  const errors = [...stationMergeErrors.value]
  if (errors.length) {
    ElMessage.error(errors[0])
    return
  }
  const nameSource = stationMergeMembers.value.find((row) => row.id === stationMergeNameSourceId.value) || target
  const codeSource = stationMergeMembers.value.find((row) => row.id === stationMergeCodeSourceId.value) || target
  const orderSource = stationMergeMembers.value.find((row) => row.id === stationMergeOrderSourceId.value) || target
  const merged = cloneDto(target)
  merged.name = nameSource.name
  merged.code = codeSource.code
  merged.sort_order = orderSource.sort_order
  if (stationMergeSourceInfo.value) {
    const source = [target, ...sources].find((row) => row.source_kind === 'device_station_field' && row.source_station_key)
    if (source) {
      merged.source_station_value = source.source_station_value
      merged.source_station_key = source.source_station_key
      merged.source_kind = 'device_station_field'
      merged.source_device_count = source.source_device_count
      merged.source_sync_status = 'matched'
      merged.source_last_seen_at = source.source_last_seen_at
    }
  }
  if (stationMergeRemarks.value) {
    merged.remark = [...new Set([target, ...sources].map((row) => row.remark.trim()).filter(Boolean))].join('；')
  }
  applyStationCombinationDraft(target, sources, merged)
  stationMergeDialogVisible.value = false
  ElMessage.success(`已在草稿中合并 ${sources.length} 个重复站点；保存前仍会再次校验`)
}

function applyStationCombinationDraft(target: Station, sources: Station[], merged: Station): void {
  if (!editingDraft.value) return
  const sourceNames = new Set(sources.map((source) => source.name))
  if (target.name !== merged.name) sourceNames.add(target.name)
  const sourceUids = new Set(sources.map((source) => source.node_uid).filter(Boolean))
  for (const section of editingDraft.value.sections) {
    const row = section as unknown as Record<string, unknown>
    if (sourceNames.has(section.start_station)) recordStationReferencePatch(target.id, 'section', section.id, row, 'start_station', merged.name)
    if (sourceNames.has(section.end_station)) recordStationReferencePatch(target.id, 'section', section.id, row, 'end_station', merged.name)
    if (sourceUids.has(section.start_node_uid)) recordStationReferencePatch(target.id, 'section', section.id, row, 'start_node_uid', target.node_uid)
    if (sourceUids.has(section.end_node_uid)) recordStationReferencePatch(target.id, 'section', section.id, row, 'end_node_uid', target.node_uid)
    if (pendingChanges.value[changeKey('section', section.id)]) markSection(section)
  }
  for (const ap of editingDraft.value.aps) {
    const row = ap as unknown as Record<string, unknown>
    if (sourceNames.has(ap.station)) recordStationReferencePatch(target.id, 'trackside_ap', ap.id, row, 'station', merged.name)
    if (sourceNames.has(ap.section_start_station)) recordStationReferencePatch(target.id, 'trackside_ap', ap.id, row, 'section_start_station', merged.name)
    if (sourceNames.has(ap.section_end_station)) recordStationReferencePatch(target.id, 'trackside_ap', ap.id, row, 'section_end_station', merged.name)
    if (pendingChanges.value[changeKey('trackside_ap', ap.id)]) markAp(ap)
  }
  const targetIndex = editingDraft.value.stations.findIndex((row) => row.id === target.id)
  editingDraft.value.stations.splice(targetIndex, 1, merged)
  editingDraft.value.stations = editingDraft.value.stations.filter((row) => !sources.some((source) => source.id === row.id))
  for (const source of sources) delete pendingChanges.value[changeKey('station', source.id)]
  const persistedSources = sources.filter((source) => !source.id.startsWith('new:'))
  const targetBaseline = baselines.get(changeKey('station', target.id)) || stationValues(target)
  const existingChange = pendingChanges.value[changeKey('station', target.id)]
  const existingSourceNames = (existingChange?.values.merge_source_names as string[] | undefined) || []
  const existingSourceUids = (existingChange?.values.merge_source_node_uids as string[] | undefined) || []
  const existingSourceIds = (existingChange?.values.merge_source_ids as string[] | undefined) || []
  const values = {
    ...stationValues(merged),
    old_name: targetBaseline.name,
    merge_source_names: [...new Set([
      ...existingSourceNames,
      ...persistedSources.map((source) => (baselines.get(changeKey('station', source.id))?.name as string) || source.name),
    ])],
    merge_source_node_uids: [...new Set([
      ...existingSourceUids,
      ...persistedSources.map((source) => source.node_uid).filter(Boolean),
    ])],
    merge_source_ids: [...new Set([
      ...existingSourceIds,
      ...persistedSources.map((source) => source.id),
    ])],
  }
  pendingChanges.value[changeKey('station', target.id)] = {
    entity_type: 'station',
    action: persistedSources.length ? 'replace' : 'update',
    entity_id: target.id,
    values,
  }
  pendingChanges.value = { ...pendingChanges.value }
  selectedStationIds.value = [target.id]
  updateEditState()
}

function openStationTableOverwrite(): void {
  if (locked.value || selectedStations.value.length !== 2) {
    ElMessage.warning('覆盖更新需要选择一个设备来源站点和一个正式目标站点')
    return
  }
  const source = selectedStations.value.find((station) => station.source_kind === 'device_station_field')
  const target = selectedStations.value.find((station) => station.id !== source?.id && !station.id.startsWith('new:'))
  if (!source || !target) {
    ElMessage.warning('请选择一个设备来源站点和一个已有正式目标站点')
    return
  }
  openStationOverwrite('', target.id, source.id)
}

function openStationOverwrite(candidateId: string, targetId: string, sourceStationId = ''): void {
  stationOverwriteCandidateId.value = candidateId
  stationOverwriteSourceStationId.value = sourceStationId
  stationOverwriteTargetId.value = targetId
  stationOverwriteManualFields.value = []
  stationOverwriteDialogVisible.value = true
}

function applyStationOverwrite(): void {
  if (!editingDraft.value || !stationOverwriteTarget.value) return
  const target = stationOverwriteTarget.value
  const manualFields = stationOverwriteManualFields.value as (keyof Station)[]
  const sourceStation = stationOverwriteSourceStation.value
  const overwritten = stationOverwriteCandidate.value
    ? overwriteStationFromSource(target, stationOverwriteCandidate.value, manualFields)
    : sourceStation
    ? overwriteStationFromStation(target, sourceStation, manualFields)
    : null
  if (!overwritten) return
  const sources = sourceStation && sourceStation.id !== target.id ? [sourceStation] : []
  const selfLoop = stationCombinationSelfLoopError(target, sources)
  if (selfLoop) {
    ElMessage.error(selfLoop)
    return
  }
  applyStationCombinationDraft(target, sources, overwritten)
  stationOverwriteDialogVisible.value = false
  ElMessage.success('来源字段已覆盖到正式目标草稿，目标 id、node_uid 与人工字段保持不变')
}

async function openStationConflictDrawer(): Promise<void> {
  stationConflictDrawerVisible.value = true
  backendStationConflictGroups.value = []
  if (!store.editSession) return
  stationConflictLoading.value = true
  try {
    const preview = await getStationConflictPreview(store.editSession.base_revision)
    backendStationConflictGroups.value = preview.groups
  } catch (cause) {
    ElMessage.warning(message(cause, '已使用当前草稿生成冲突组'))
  } finally {
    stationConflictLoading.value = false
  }
}

function keepConflictStation(group: StationConflictGroup, keepId: string): void {
  if (!editingDraft.value) return
  for (const member of group.stations) {
    if (member.station_id === keepId) continue
    const row = editingDraft.value.stations.find((station) => station.id === member.station_id)
    if (row) {
      row.participates_in_direction = false
      markStation(row)
    }
  }
}

function combineConflictGroup(group: StationConflictGroup): void {
  stationConflictDrawerVisible.value = false
  openStationCombination(group.stations.map((station) => station.station_id))
}

function overwriteConflictGroup(group: StationConflictGroup): void {
  const members = stationRows.value.filter((station) => group.stations.some((member) => member.station_id === station.id))
  const source = members.find((station) => station.source_kind === 'device_station_field')
  const target = members.find((station) => station.id !== source?.id && !station.id.startsWith('new:') && ['manual', 'template'].includes(station.source_kind))
    || members.find((station) => station.id !== source?.id && !station.id.startsWith('new:'))
  if (!source || !target) {
    ElMessage.warning('该冲突组无法识别唯一的设备来源与正式目标，请使用“合并”或手动处理')
    return
  }
  stationConflictDrawerVisible.value = false
  openStationOverwrite('', target.id, source.id)
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
  const row: Station = defaultStation({
    id: temporaryId(),
    node_uid: newNodeUid(),
    line_name: store.summary?.line_name || '',
    path_code: editingDraft.value.metadata.main_path_code || 'MAIN',
    sort_order: editingDraft.value.stations.length + 1,
    structure_type: 'underground',
    platform_layout: 'island',
    source_kind: 'manual',
    source_sync_status: 'manual',
  })
  editingDraft.value.stations.push(row); markStation(row)
}
function addSection(): void {
  if (!editingDraft.value) return
  const row = defaultSection({
    id: temporaryId(),
    path_code: editingDraft.value.metadata.main_path_code || 'MAIN',
    source_kind: 'manual',
  })
  editingDraft.value.sections.push(row); markSection(row)
}
function addAp(): void {
  if (!editingDraft.value) return
  const row = newTracksideAp()
  editingDraft.value.aps.push(row); markAp(row)
}
function newTracksideAp(): TracksideAp {
  return { id: temporaryId(), site_id: store.editSession?.site_id || '', line_name: store.summary?.line_name || '', name: '', point_code: '', mac: '', management_ip: '', model: '', station: '', section: '', section_start_station: '', section_end_station: '', mileage: { raw: '', normalized: '', meters: null, line_type: '', valid: false, error: '' }, line_side: '', line_side_source: 'unavailable', line_side_derivation_issue_code: '', line_side_derivation_issue_message: '', direction: '', radios: [], remark: '', source_file: '', source_sheet: '', source_row: null, updated_at: '', runtime: emptyRuntime(), issue_count: 0, highest_issue_severity: '', record_kind: 'manual', base_metadata: {} }
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
function newNodeUid(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `draft-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
function stationValues(row: Station): Record<string, unknown> {
  return {
    node_uid: row.node_uid,
    name: row.name,
    code: row.code,
    line_name: row.line_name,
    sort_order: row.sort_order,
    remark: row.remark,
    source_station_value: row.source_station_value,
    source_station_key: row.source_station_key,
    source_order_text: row.source_order_text,
    source_order: row.source_order,
    canonical_station_name: row.canonical_station_name,
    node_type: row.node_type,
    path_code: row.path_code,
    participates_in_direction: row.participates_in_direction,
    structure_type: row.structure_type,
    platform_layout: row.platform_layout,
    center_mileage_text: row.center_mileage_text,
    center_mileage_m: row.center_mileage_m,
    is_line_terminal: row.is_line_terminal,
    is_service_terminal: row.is_service_terminal,
    turnback_capable: row.turnback_capable,
    turnback_type: row.turnback_type,
    track_facilities: row.track_facilities,
    turnback_direction: row.turnback_direction,
    terminal_extension_enabled: row.terminal_extension_enabled,
    terminal_endpoint_label: row.terminal_endpoint_label,
    terminal_extension_distance_m: row.terminal_extension_distance_m,
    terminal_endpoint_mileage_text: row.terminal_endpoint_mileage_text,
    enabled: row.enabled,
    source_kind: row.source_kind,
  }
}
function sectionValues(row: Section): Record<string, unknown> {
  return {
    name: row.name,
    section_code: row.section_code,
    section_kind: row.section_kind,
    path_code: row.path_code,
    direction_role: row.direction_role,
    line_direction: row.line_direction,
    start_node_type: row.start_node_type,
    start_node_uid: row.start_node_uid,
    start_station: row.start_station,
    end_node_type: row.end_node_type,
    end_node_uid: row.end_node_uid,
    end_station: row.end_station,
    line_side: row.line_side,
    auto_generated: row.auto_generated,
    generation_key: row.generation_key,
    manual_override_fields: row.manual_override_fields,
    section_mileage_start_m: row.section_mileage_start_m,
    section_mileage_end_m: row.section_mileage_end_m,
    section_mileage_open_end: row.section_mileage_open_end,
    section_mileage_source: row.section_mileage_source,
    enabled: row.enabled,
    source_kind: row.source_kind,
    remark: row.remark,
  }
}
function apValues(row: TracksideAp): Record<string, unknown> {
  return {
    line_name: row.line_name,
    ap_name: row.name,
    ap_point_code: row.point_code,
    ap_mac_display: row.mac,
    station_name: row.station,
    section_name: row.section,
    section_start_station: row.section_start_station,
    section_end_station: row.section_end_station,
    mileage: row.mileage.raw,
    line_side: row.line_side,
    direction: row.direction,
    remark: row.remark,
    source_file: row.source_file,
    source_sheet: row.source_sheet,
    source_row: row.source_row,
    base_metadata: row.base_metadata,
    ...Object.fromEntries(
      ['system_type', 'network_domain', 'belong_type', 'yard_name', 'area_name', 'distance_to_prev_m', 'curve_radius_m', 'curve_start_text', 'curve_end_text', 'install_scene', 'location_desc', 'power_station', 'power_distribution', 'fiber_access_station', 'fiber_distribution', 'uplink_switch', 'uplink_port', 'optical_port']
        .map((field) => [field, row.base_metadata[field] ?? '']),
    ),
  }
}
function mrValues(row: VehicleMr): Record<string, unknown> { return { name: row.name, station: row.station, management_ip: row.management_ip, mac: row.mac, protocol: row.protocol, port: row.port, remark: row.remark } }
function metadataValues(metadata: BaseDataDraft['metadata']): Record<string, unknown> {
  return {
    line_name: metadata.line_name,
    system_type: metadata.system_type,
    network_domain: metadata.network_domain,
    main_path_code: metadata.main_path_code,
    increasing_direction_name: metadata.increasing_direction_name,
    decreasing_direction_name: metadata.decreasing_direction_name,
    increasing_direction_line_side: metadata.increasing_direction_line_side,
    decreasing_direction_line_side: metadata.decreasing_direction_line_side,
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
function emptyRuntime() { return { fit_ap_id: '', fit_ap_ac_id: '', fit_ap_name: '', fit_ap_match_status: 'unmatched', fit_ap_status: 'unknown', optical_status: 'no_data', mesh_status: 'unknown', mesh_related_name: '', latest_session_id: '', latest_session_status: '', updated_at: '' } }
function message(cause: unknown, fallback: string): string { return cause instanceof Error && cause.message ? cause.message : fallback }
function isStationSourceCandidateSelected(candidate: StationSourceCandidate): boolean {
  return selectedStationSourceIds.value.includes(candidate.candidate_id)
}

function isStationSourceCandidateDisabled(candidate: StationSourceCandidate): boolean {
  const strategy = stationSourceStrategies.value[candidate.candidate_id] || candidate.processing_strategy
  if (strategy === 'merge_duplicates' && (candidate.matched_station_ids?.length || 0) > 1) {
    return candidate.issues.some((issue) => issue.blocking && issue.code !== 'station_source_ambiguous_match')
  }
  if (strategy === 'manual_target') {
    return !stationSourceTargets.value[candidate.candidate_id]
  }
  return candidate.issues.some((issue) => issue.blocking)
}

function isStationTemplateRowSelected(row: StationTemplatePreviewRow): boolean {
  return selectedTemplateRows.value.includes(row.row_number)
}

function isStationTemplateRowDisabled(row: StationTemplatePreviewRow): boolean {
  return !row.valid || row.action === 'conflict'
}

function isStationTemplateSectionRowSelected(row: StationTemplateSectionPreviewRow): boolean {
  return selectedTemplateSectionRows.value.includes(row.row_number)
}

function isStationTemplateSectionRowDisabled(row: StationTemplateSectionPreviewRow): boolean {
  return !row.valid || row.action === 'conflict'
}

function canApplyStationTemplatePreview(): boolean {
  return !locked.value
    && (selectedTemplateRows.value.length > 0 || selectedTemplateSectionRows.value.length > 0)
    && !store.stationTemplatePreview?.blocking_count
}

function handleStationClassificationChange(row: Station): void {
  const mainPath = editingDraft.value?.metadata.main_path_code || store.summary?.main_path_code || 'MAIN'
  if (row.node_type === 'station' && row.path_code === mainPath) {
    if (row.structure_type === 'unknown') row.structure_type = 'underground'
    if (row.platform_layout === 'unknown') row.platform_layout = 'island'
  }
  markStation(row)
}

function handleLineTerminalChange(row: Station): void {
  if (!row.is_line_terminal) row.terminal_extension_enabled = false
  markStation(row)
}

function sectionNodeValue(row: Section, endpoint: 'start' | 'end'): string {
  return endpoint === 'start' ? row.start_node_uid || row.start_station : row.end_node_uid || row.end_station
}
function handleSectionNodeChange(row: Section, endpoint: 'start' | 'end', value: string): void {
  const selected = sectionNodeOptions.value.find((item) => item.uid === value)
  if (endpoint === 'start') {
    row.start_node_type = selected?.type || 'legacy'
    row.start_node_uid = selected?.uid || ''
    row.start_station = selected?.persisted_name || value
  } else {
    row.end_node_type = selected?.type || 'legacy'
    row.end_node_uid = selected?.uid || ''
    row.end_station = selected?.persisted_name || value
  }
  markSectionField(row, endpoint === 'start' ? 'start_node_type' : 'end_node_type', endpoint === 'start' ? 'start_node_uid' : 'end_node_uid', endpoint === 'start' ? 'start_station' : 'end_station')
}
function handleSectionDirectionChange(row: Section, direction: string): void {
  row.line_direction = direction
  const increasing = editingDraft.value?.metadata.increasing_direction_name || store.summary?.increasing_direction_name || '上行'
  const decreasing = editingDraft.value?.metadata.decreasing_direction_name || store.summary?.decreasing_direction_name || '下行'
  row.direction_role = direction === increasing ? 'increasing' : direction === decreasing ? 'decreasing' : 'none'
  row.line_side = sectionLineSide(row)
  markSectionField(row, 'line_direction', 'line_side', 'direction_role')
  syncAutomaticApsForSection(row)
}

function sectionLineSide(section: Section): string {
  const metadata = editingDraft.value?.metadata
  const increasingName = metadata?.increasing_direction_name || store.summary?.increasing_direction_name || '上行'
  const decreasingName = metadata?.decreasing_direction_name || store.summary?.decreasing_direction_name || '下行'
  if (section.direction_role === 'increasing' || section.line_direction === increasingName) {
    return metadata?.increasing_direction_line_side || store.summary?.increasing_direction_line_side || '右线'
  }
  if (section.direction_role === 'decreasing' || section.line_direction === decreasingName) {
    return metadata?.decreasing_direction_line_side || store.summary?.decreasing_direction_line_side || '左线'
  }
  return ''
}

function matchesApSection(row: TracksideAp, section: Section): boolean {
  const metadata = row.base_metadata || {}
  return row.section === section.name
    || Boolean(section.section_code && metadata.section_code === section.section_code)
    || Boolean(section.generation_key && metadata.section_generation_key === section.generation_key)
    || Boolean(section.id && metadata.section_id === section.id)
}

function syncAutomaticApLineSide(row: TracksideAp): boolean {
  if (!editingDraft.value) return false
  const section = editingDraft.value.sections.find((item) => matchesApSection(row, item))
  if (!section) return false
  const expected = sectionLineSide(section)
  if (!expected) return false
  const source = String(row.base_metadata?.line_side_source || (row.line_side ? 'legacy' : 'unavailable'))
  if (row.line_side && source !== 'section_direction' && source !== 'unavailable') return false
  const before = JSON.stringify(apValues(row))
  row.line_side = expected
  row.line_side_source = 'section_direction'
  row.line_side_derivation_issue_code = ''
  row.line_side_derivation_issue_message = ''
  row.section = section.name
  row.section_start_station = section.start_station
  row.section_end_station = section.end_station
  row.base_metadata = {
    ...row.base_metadata,
    line_side_source: 'section_direction',
    section_id: section.id,
    section_name: section.name,
    section_code: section.section_code,
    section_generation_key: section.generation_key,
  }
  if (before === JSON.stringify(apValues(row))) return false
  markAp(row)
  return true
}

function syncAutomaticApsForSection(section: Section): void {
  if (!editingDraft.value) return
  for (const row of editingDraft.value.aps) {
    if (matchesApSection(row, section)) syncAutomaticApLineSide(row)
  }
}

function syncAllAutomaticApLineSides(): void {
  if (!editingDraft.value) return
  for (const row of editingDraft.value.aps) syncAutomaticApLineSide(row)
}

function handleApSectionChange(row: TracksideAp): void {
  if (!syncAutomaticApLineSide(row)) markAp(row)
}

async function openStationSourcePreview(): Promise<void> {
  try {
    const preview = await store.refreshStationSourcePreview()
    stationSourceStrategies.value = Object.fromEntries(
      preview.candidates.map((candidate) => [candidate.candidate_id, candidate.processing_strategy || (candidate.matched_station_id ? 'overwrite_existing' : candidate.match_status === 'create' ? 'create' : 'manual_target')]),
    )
    stationSourceTargets.value = Object.fromEntries(
      preview.candidates.map((candidate) => [candidate.candidate_id, candidate.matched_station_id || candidate.matched_station_ids?.[0] || '']),
    )
    selectedStationSourceIds.value = preview.candidates
      .filter((candidate) => !isStationSourceCandidateDisabled(candidate) && stationSourceStrategies.value[candidate.candidate_id] !== 'ignore')
      .map((candidate) => candidate.candidate_id)
    stationSourceDialogVisible.value = true
  } catch (cause) {
    ElMessage.error(message(cause, '设备管理站点来源预览失败'))
  }
}

function stationSourceStrategy(candidate: StationSourceCandidate): StationSourceProcessingStrategy {
  return stationSourceStrategies.value[candidate.candidate_id] || candidate.processing_strategy || 'manual_target'
}

function updateStationSourceStrategy(candidate: StationSourceCandidate, strategy: StationSourceProcessingStrategy): void {
  stationSourceStrategies.value = { ...stationSourceStrategies.value, [candidate.candidate_id]: strategy }
  if (strategy === 'ignore') {
    selectedStationSourceIds.value = selectedStationSourceIds.value.filter((id) => id !== candidate.candidate_id)
  }
}

function stationSourceStrategyLabel(strategy: StationSourceProcessingStrategy): string {
  return {
    auto_match: '自动匹配现有',
    overwrite_existing: '覆盖现有',
    create: '新增',
    ignore: '忽略',
    manual_target: '人工选择目标',
    merge_duplicates: '合并重复项',
  }[strategy]
}

function stationSourceTargetOptions(candidate: StationSourceCandidate): Station[] {
  const persisted = stationRows.value.filter((station) => !station.id.startsWith('new:'))
  if (stationSourceStrategy(candidate) !== 'merge_duplicates') return persisted
  const matchedIds = new Set(candidate.matched_station_ids || [])
  return persisted.filter((station) => matchedIds.has(station.id))
}

function selectSuggestedStationSources(): void {
  selectedStationSourceIds.value = stationSourceCandidates.value
    .filter((candidate) => !isStationSourceCandidateDisabled(candidate) && stationSourceStrategy(candidate) !== 'ignore')
    .map((candidate) => candidate.candidate_id)
}

function selectStationSourcesByStrategy(strategy: 'overwrite_existing' | 'create'): void {
  selectedStationSourceIds.value = stationSourceCandidates.value
    .filter((candidate) => stationSourceStrategy(candidate) === strategy && !isStationSourceCandidateDisabled(candidate))
    .map((candidate) => candidate.candidate_id)
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
  const candidates = stationSourceCandidates.value.filter((candidate) => selected.has(candidate.candidate_id) && !isStationSourceCandidateDisabled(candidate))
  if (!candidates.length) {
    ElMessage.warning('没有可应用的站点来源候选')
    return
  }
  let applied = 0
  for (const candidate of candidates) {
    const strategy = stationSourceStrategy(candidate)
    if (strategy === 'ignore') continue
    const proposed = defaultStation(candidate.proposed_station)
    proposed.line_name = proposed.line_name || editingDraft.value.metadata.line_name || store.summary?.line_name || ''
    const targetId = stationSourceTargets.value[candidate.candidate_id] || candidate.matched_station_id
    const matched = targetId
      ? editingDraft.value.stations.find((station) => station.id === targetId)
      : editingDraft.value.stations.find((station) => station.source_station_key && station.source_station_key === candidate.source_station_key)
    if (strategy === 'merge_duplicates') {
      const memberIds = candidate.matched_station_ids || []
      const members = editingDraft.value.stations.filter((station) => memberIds.includes(station.id))
      const target = members.find((station) => station.id === targetId)
        || members.find((station) => ['manual', 'template'].includes(station.source_kind))
        || members[0]
      if (!target || members.length < 2) continue
      const sources = members.filter((station) => station.id !== target.id)
      if (stationCombinationErrors(target, sources).length || stationCombinationSelfLoopError(target, sources)) continue
      const overwritten = overwriteStationFromSource(target, candidate)
      applyStationCombinationDraft(target, sources, overwritten)
      applied += 1
      continue
    }
    if (matched && ['overwrite_existing', 'auto_match', 'manual_target'].includes(strategy)) {
      const overwritten = overwriteStationFromSource(matched, candidate)
      applyStationCombinationDraft(matched, [], overwritten)
      if (overwritten.node_type === 'station' && overwritten.path_code === editingDraft.value.metadata.main_path_code) {
        if (overwritten.structure_type === 'unknown') overwritten.structure_type = 'underground'
        if (overwritten.platform_layout === 'unknown') overwritten.platform_layout = 'island'
      }
      applied += 1
      continue
    }
    if (strategy !== 'create') continue
    proposed.id = proposed.id || temporaryId()
    proposed.node_uid = proposed.node_uid || newNodeUid()
    proposed.source_device_count = candidate.source_device_count
    proposed.source_sync_status = 'matched'
    editingDraft.value.stations.push(proposed)
    markStation(proposed)
    applied += 1
  }
  if (!applied) {
    ElMessage.warning('所选候选没有可应用的安全目标，请调整处理方式或目标站点')
    return
  }
  stationSourceDialogVisible.value = false
  ElMessage.success(`已应用 ${applied} 个候选到当前草稿，保存后才会写入数据库`)
}

async function downloadStationTemplate(): Promise<void> {
  try {
    const result = await downloadBackendResource(stationTemplateDownloadRequest())
    if (result.status === 'saved') ElMessage.success('线路站点与区间模板已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载线路站点与区间模板')
    else if (result.status === 'failed') ElMessage.error(result.error || '基础资料模板下载失败')
  } catch (cause) {
    ElMessage.error(message(cause, '基础资料模板下载失败'))
  }
}

async function startApBaseExport(template: boolean): Promise<void> {
  let draftRows: TracksideAp[] | undefined
  if (!template && !locked.value && dirty.value) {
    const choice = await confirmChoice({
      type: 'WARNING',
      title: '选择导出数据',
      message: '当前页面存在未保存修改，请明确选择导出当前草稿或数据库中已保存的数据。',
      confirmText: '导出当前草稿',
      secondaryText: '导出已保存数据',
      cancelText: '取消',
    })
    if (choice === 'cancel') return
    if (choice === 'confirm') draftRows = cloneDto(apRows.value)
  }
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: template ? 'rail.trackside_base_template' : 'rail.trackside_base_current',
      suggestedName: `${safeExportPart(store.summary?.line_name || '当前局点')}-${template ? '轨旁AP基础资料模板' : '轨旁AP基础资料'}-${exportTimestamp()}.xlsx`,
      context: { template, draft: Boolean(draftRows) },
      submit: () => exportTracksideApBase(template, draftRows),
    })
    if (result.status === 'cancelled') return
    apBaseTaskId.value = result.task.task_id
    await taskStore.refresh()
    ElMessage.success(template
      ? '轨旁 AP 模板导出任务已启动，完成后将写入所选位置'
      : '轨旁 AP 当前数据导出任务已启动，完成后将写入所选位置')
  } catch (cause) {
    ElMessage.error(message(cause, template ? '轨旁 AP 模板导出启动失败' : '轨旁 AP 当前数据导出启动失败'))
  }
}

async function exportImportIssues(): Promise<void> {
  if (!previewProblemRows.value.length) {
    ElMessage.info('当前没有冲突或无效数据')
    return
  }
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.trackside_base_import_issues',
      suggestedName: `${safeExportPart(store.summary?.line_name || '当前局点')}-轨旁AP导入问题明细-${exportTimestamp()}.xlsx`,
      context: { issue_count: previewProblemRows.value.length },
      submit: () => exportTracksideApImportIssues(previewProblemRows.value),
    })
    if (result.status === 'cancelled') return
    apBaseTaskId.value = result.task.task_id
    await taskStore.refresh()
  } catch (cause) {
    ElMessage.error(message(cause, '导入问题明细导出失败'))
  }
}

async function startApRenameCommandExport(): Promise<void> {
  let draftRows: TracksideAp[] | undefined
  if (!locked.value && dirty.value) {
    const choice = await confirmChoice({
      type: 'WARNING',
      title: '选择导出数据',
      message: '当前存在未保存修改，请选择导出当前草稿还是数据库中已保存的数据。',
      confirmText: '导出当前草稿',
      secondaryText: '导出已保存数据',
      cancelText: '取消',
    })
    if (choice === 'cancel') return
    if (choice === 'confirm') draftRows = cloneDto(apRows.value)
  }
  try {
    const result = await userSelectedExport.submitExportAfterDestinationSelected({
      action: 'rail.trackside_rename_commands',
      suggestedName: `${safeExportPart(store.summary?.line_name || '当前局点')}-轨旁AP重命名命令-${exportTimestamp()}.txt`,
      context: { draft: Boolean(draftRows) },
      submit: () => exportTracksideApRenameCommands(draftRows),
    })
    if (result.status === 'cancelled') return
    apBaseTaskId.value = result.task.task_id
    await taskStore.refresh()
    ElMessage.success('轨旁 AP 重命名命令导出任务已启动，完成后将写入所选位置')
  } catch (cause) {
    ElMessage.error(message(cause, '轨旁 AP 重命名命令导出启动失败'))
  }
}

function safeExportPart(value: string): string {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || '当前局点'
}

function exportTimestamp(now = new Date()): string {
  const part = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}${part(now.getMonth() + 1)}${part(now.getDate())}_${part(now.getHours())}${part(now.getMinutes())}${part(now.getSeconds())}`
}

async function exportCurrentStations(): Promise<void> {
  if (dirty.value) ElMessage.warning('未保存修改不包含在本次导出中')
  try {
    const result = await downloadBackendResource(stationTemplateExportDownloadRequest())
    if (result.status === 'saved') ElMessage.success('已保存当前正式基础资料')
    else if (result.status === 'started') ElMessage.success('浏览器已开始导出当前正式基础资料')
    else if (result.status === 'failed') ElMessage.error(result.error || '当前基础资料导出失败')
  } catch (cause) {
    ElMessage.error(message(cause, '当前基础资料导出失败'))
  }
}

async function handleStationTemplateFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const preview = await store.previewStationTemplateFile(file)
    selectedTemplateRows.value = preview.rows.filter((row) => row.valid && row.action !== 'conflict').map((row) => row.row_number)
    selectedTemplateSectionRows.value = preview.section_rows.filter((row) => row.valid && row.action !== 'conflict').map((row) => row.row_number)
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

function toggleTemplateSectionRow(row: StationTemplateSectionPreviewRow, checked: boolean): void {
  const next = new Set(selectedTemplateSectionRows.value)
  if (checked) next.add(row.row_number)
  else next.delete(row.row_number)
  selectedTemplateSectionRows.value = [...next]
}

function applyStationTemplateToDraft(): void {
  if (locked.value || !editingDraft.value) {
    ElMessage.warning('请先解锁基础资料')
    return
  }
  const selected = new Set(selectedTemplateRows.value)
  const rows = stationTemplateRows.value.filter((item) => selected.has(item.row_number) && item.valid && item.proposed_station)
  const selectedSections = new Set(selectedTemplateSectionRows.value)
  const sectionRows = stationTemplateSectionRows.value.filter((item) => selectedSections.has(item.row_number) && item.valid && item.proposed_section)
  if (!rows.length && !sectionRows.length) {
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
      proposed.node_uid = proposed.node_uid || newNodeUid()
      editingDraft.value.stations.push(proposed)
      markStation(proposed)
    }
    applied += 1
  }
  for (const row of sectionRows) {
    const proposed = defaultSection(row.proposed_section || {})
    const matched = editingDraft.value.sections.find((section) => (
      (proposed.generation_key && section.generation_key === proposed.generation_key)
      || (proposed.section_code && section.section_code === proposed.section_code)
      || section.name === proposed.name
    ))
    if (matched) {
      Object.assign(matched, {
        ...proposed,
        id: matched.id,
        ap_count: matched.ap_count,
        mileage_min: matched.mileage_min,
        mileage_max: matched.mileage_max,
      })
      markSection(matched)
    } else {
      proposed.id = temporaryId()
      editingDraft.value.sections.push(proposed)
      markSection(proposed)
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
  editingDraft.value.metadata.increasing_direction_line_side = String(metadata.increasing_direction_line_side || editingDraft.value.metadata.increasing_direction_line_side)
  editingDraft.value.metadata.decreasing_direction_line_side = String(metadata.decreasing_direction_line_side || editingDraft.value.metadata.decreasing_direction_line_side)
  editingDraft.value.metadata.station_source_group_name = String(metadata.station_source_group_name || editingDraft.value.metadata.station_source_group_name)
  editingDraft.value.metadata.station_source_field = 'station'
  editingDraft.value.metadata.remark = String(metadata.remark || editingDraft.value.metadata.remark)
  handleLineSideMappingChange()
  stationTemplateDialogVisible.value = false
  ElMessage.success(`已应用 ${applied} 行模板预览到当前草稿，保存后才会写入数据库`)
}

async function openSectionGenerationPreview(): Promise<void> {
  const metadata = editingDraft.value?.metadata
  const stations = editingDraft.value?.stations ?? store.stations
  const sections = editingDraft.value?.sections ?? store.sections
  try {
    const preview = await store.previewSectionsFromDraft(
      {
        main_path_code: metadata?.main_path_code || store.summary?.main_path_code || 'MAIN',
        increasing_direction_name: metadata?.increasing_direction_name || store.summary?.increasing_direction_name || '上行',
        decreasing_direction_name: metadata?.decreasing_direction_name || store.summary?.decreasing_direction_name || '下行',
        increasing_direction_line_side: metadata?.increasing_direction_line_side || store.summary?.increasing_direction_line_side || '右线',
        decreasing_direction_line_side: metadata?.decreasing_direction_line_side || store.summary?.decreasing_direction_line_side || '左线',
      },
      cloneDto(stations),
      cloneDto(sections),
    )
    selectedSectionGenerationIds.value = preview.generated_sections
      .filter((item) => item.selectable && item.selected_by_default)
      .map((item) => item.item_id)
    sectionGenerationDialogVisible.value = true
  } catch (cause) {
    ElMessage.error(message(cause, '区间生成预览失败'))
  }
}

function generationSection(row: SectionGenerationPreviewItem): Section | null {
  return row.proposed_section || row.current_section
}

function isSectionGenerationSelected(row: SectionGenerationPreviewItem): boolean {
  return selectedSectionGenerationIds.value.includes(row.item_id)
}

function toggleSectionGenerationRow(row: SectionGenerationPreviewItem, checked: boolean): void {
  const next = new Set(selectedSectionGenerationIds.value)
  if (checked) next.add(row.item_id)
  else next.delete(row.item_id)
  selectedSectionGenerationIds.value = [...next]
}

function markSectionForDeletion(row: Section): void {
  const key = changeKey('section', row.id)
  if (row.id.startsWith('new:')) {
    delete pendingChanges.value[key]
    baselines.delete(key)
    removeDraftRow('section', row.id)
    return
  }
  const baseline = baselines.get(key) || sectionValues(row)
  pendingChanges.value[key] = {
    entity_type: 'section',
    action: 'delete',
    entity_id: row.id,
    values: withOriginalIdentity('section', baseline, baseline),
  }
}

function applySectionGenerationToDraft(): void {
  if (locked.value || !editingDraft.value) {
    ElMessage.warning('请先解锁基础资料')
    return
  }
  const selected = new Set(selectedSectionGenerationIds.value)
  let applied = 0
  for (const item of sectionGenerationRows.value) {
    if (!selected.has(item.item_id) || !item.selectable || item.result === 'CONFLICT') continue
    if (item.result === 'STALE' && item.current_section) {
      const current = editingDraft.value.sections.find((section) => section.id === item.current_section?.id)
      if (current) {
        markSectionForDeletion(current)
        applied += 1
      }
      continue
    }
    if (!item.proposed_section || item.result === 'UNCHANGED') continue
    const proposed = defaultSection(item.proposed_section)
    const current = editingDraft.value.sections.find((section) => (
      section.id === item.current_section?.id
      || (proposed.generation_key && section.generation_key === proposed.generation_key)
    ))
    if (current) {
      Object.assign(current, {
        ...proposed,
        id: current.id,
        remark: current.remark,
        ap_count: current.ap_count,
        mileage_min: current.mileage_min,
        mileage_max: current.mileage_max,
        manual_override_fields: current.manual_override_fields,
      })
      markSection(current)
    } else {
      proposed.id = proposed.id.startsWith('new:') ? proposed.id : temporaryId()
      editingDraft.value.sections.push(proposed)
      markSection(proposed)
    }
    applied += 1
  }
  pendingChanges.value = { ...pendingChanges.value }
  syncAllAutomaticApLineSides()
  updateEditState()
  sectionGenerationDialogVisible.value = false
  ElMessage.success(`已应用 ${applied} 项区间生成结果到当前草稿，保存后才会写入数据库`)
}

async function restoreSectionAutomaticValues(row: Section): Promise<void> {
  if (locked.value || !editingDraft.value || !row.auto_generated || !row.generation_key) return
  try {
    const preview = await store.previewSectionsFromDraft(
      cloneDto(editingDraft.value.metadata),
      cloneDto(editingDraft.value.stations),
      cloneDto(editingDraft.value.sections.filter((section) => section.id !== row.id)),
    )
    const suggestion = preview.generated_sections.find((item) => (
      item.result !== 'CONFLICT' && item.proposed_section?.generation_key === row.generation_key
    ))?.proposed_section
    if (!suggestion) {
      ElMessage.warning('当前站点顺序无法生成该区间，不能恢复自动值')
      return
    }
    Object.assign(row, {
      ...defaultSection(suggestion),
      id: row.id,
      remark: row.remark,
      ap_count: row.ap_count,
      mileage_min: row.mileage_min,
      mileage_max: row.mileage_max,
      manual_override_fields: [],
    })
    markSection(row)
    ElMessage.success('已恢复自动建议值，保存后才会写入数据库')
  } catch {
    ElMessage.error('恢复自动值失败，请稍后重试')
  }
}

async function handleFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  await previewApImport(file)
  input.value = ''
}

async function handleTracksideApFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const completed = await previewApImport(file)
  input.value = ''
  if (completed) apImportDialogVisible.value = true
}

async function previewApImport(file: File): Promise<boolean> {
  try {
    await store.previewImport(file)
    decisionSelections.value = {}
    ElMessage.success('导入预览解析完成，未写入数据库')
    return true
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '导入预览失败')
    return false
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
  if (locked.value || !editingDraft.value || previewImportableCount.value <= 0) return
  try {
    const decisions = new Map(
      manualDecisions().map((item) => [decisionKey(item.row_number, item.field_name), item.action]),
    )
    let applied = 0
    for (const item of store.importPreview?.merge_plan?.items || []) {
      if (item.blocking || !['CREATE', 'UPDATE'].includes(item.result)) continue
      if (item.result === 'CREATE') {
        const row = newTracksideAp()
        for (const [field, value] of Object.entries(item.source_values)) {
          if (value !== null && value !== '') applyImportedApValue(row, field, value)
        }
        editingDraft.value.aps.push(row)
        markAp(row)
        applied += 1
        continue
      }
      const row = editingDraft.value.aps.find((candidate) => candidate.id === item.matched_entity_id)
      if (!row) continue
      for (const diff of item.field_diffs) {
        const selected = decisions.get(decisionKey(item.row_number, diff.field_name))
        if (diff.action === 'manual_review' && selected !== 'use_imported') continue
        if (diff.action === 'keep_existing') continue
        applyImportedApValue(row, diff.field_name, diff.proposed_value)
      }
      for (const field of ['source_file', 'source_sheet', 'source_row', 'raw_payload_json']) {
        const value = item.source_values[field]
        if (value !== null && value !== '') applyImportedApValue(row, field, value)
      }
      markAp(row)
      applied += 1
    }
    apImportDialogVisible.value = false
    const summary = store.importPreview?.merge_plan?.summary
    const unmatched = summary?.unmatched_fit_ap_count || 0
    ElMessage.success(
      `有效数据已加入编辑草稿：新增 ${summary?.create_count || 0} 条，更新 ${summary?.update_count || 0} 条，不变 ${summary?.unchanged_count || 0} 条；`
      + `跳过冲突 ${summary?.conflict_count || 0} 条，无效 ${summary?.invalid_count || 0} 条。`
      + `${unmatched ? `${unmatched} 条记录暂未匹配 FIT-AP，不影响 MR 日志识别。` : ''}`
      + `本次草稿应用 ${applied} 条，请点击页面顶部“保存并锁定”使其生效。`,
    )
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '导入应用失败')
  }
}

function applyImportedApValue(row: TracksideAp, field: string, value: unknown): void {
  const text = value === null || value === undefined ? '' : String(value)
  if (field === 'line_name') row.line_name = text
  else if (field === 'ap_name') row.name = text
  else if (field === 'ap_point_code') row.point_code = text
  else if (field === 'ap_mac_display') row.mac = text
  else if (field === 'ap_mac_norm' && !row.mac) row.mac = text.replace(/[^0-9a-f]/gi, '').replace(/^(.{4})(.{4})(.{4})$/, '$1-$2-$3')
  else if (field === 'station_name') row.station = text
  else if (field === 'section_name') row.section = text
  else if (field === 'section_start_station') row.section_start_station = text
  else if (field === 'section_end_station') row.section_end_station = text
  else if (field === 'line_side') row.line_side = text
  else if (field === 'direction') row.direction = text
  else if (field === 'mileage_text') row.mileage = { ...row.mileage, raw: text, normalized: text }
  else if (field === 'remark') row.remark = text
  else if (field === 'source_file') row.source_file = text
  else if (field === 'source_sheet') row.source_sheet = text
  else if (field === 'source_row') row.source_row = Number.isFinite(Number(value)) ? Number(value) : null
  else if (field === 'belong_type') {
    row.record_kind = text || 'unknown'
    row.base_metadata.belong_type = text || 'unknown'
  } else if (field === 'raw_payload_json') {
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) row.base_metadata = { ...row.base_metadata, ...parsed }
    } catch { /* 无效来源元数据不影响已校验的正式字段。 */ }
  } else if (!['id', 'mileage_m'].includes(field)) row.base_metadata[field] = value
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
  if (!ap.runtime.fit_ap_id) {
    ElMessage.warning(ap.runtime.fit_ap_match_status === 'conflict'
      ? '该 AP MAC 匹配到多个 AC FIT-AP，请先处理重复 MAC。'
      : '未在当前局点的 AC FIT-AP 资源中找到该 AP，请先采集或刷新 AC FIT-AP 数据。')
    return
  }
  router.push({ path: '/ac-management', query: { ac_id: ap.runtime.fit_ap_ac_id || undefined, ap: ap.runtime.fit_ap_id } })
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
  if (value === 'CONFLICT' || value === 'INVALID') return 'danger'
  if (value === 'NEEDS_CONFIRMATION') return 'warning'
  return 'info'
}
function templateLabel(value: string): string {
  return value === 'ap_switch_port_point_table' ? 'AP 交换机端口点表' : value || '未识别模板'
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
function cloneDto<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
function defaultStation(values: Partial<Station> = {}): Station {
  return {
    id: '',
    node_uid: '',
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
    source_order_text: '',
    source_order: null,
    canonical_station_name: '',
    node_type: 'station',
    path_code: 'MAIN',
    participates_in_direction: true,
    structure_type: 'unknown',
    platform_layout: 'unknown',
    center_mileage_text: '',
    center_mileage_m: null,
    is_line_terminal: false,
    is_service_terminal: false,
    turnback_capable: false,
    turnback_type: 'none',
    track_facilities: [],
    turnback_direction: 'none',
    terminal_extension_enabled: false,
    terminal_endpoint_label: '端点',
    terminal_extension_distance_m: null,
    terminal_endpoint_mileage_text: '',
    enabled: true,
    source_kind: 'manual',
    source_device_count: 0,
    source_sync_status: 'manual',
    source_last_seen_at: '',
    ...values,
  }
}
function defaultSection(values: Partial<Section> = {}): Section {
  return {
    id: '',
    name: '',
    section_code: '',
    section_kind: 'manual',
    path_code: 'MAIN',
    direction_role: 'none',
    line_direction: '',
    start_node_type: 'legacy',
    start_node_uid: '',
    start_station: '',
    end_node_type: 'legacy',
    end_node_uid: '',
    end_station: '',
    line_side: '',
    auto_generated: false,
    generation_key: '',
    manual_override_fields: [],
    section_mileage_start_m: null,
    section_mileage_end_m: null,
    section_mileage_open_end: false,
    section_mileage_source: 'unavailable',
    enabled: true,
    source_kind: 'manual',
    ap_count: 0,
    mileage_min: null,
    mileage_max: null,
    remark: '',
    ...values,
  }
}
function mileageRange(minimum: number | null, maximum: number | null): string {
  if (minimum === null && maximum === null) return '--'
  if (minimum === maximum || maximum === null) return `${minimum} m`
  return `${minimum}–${maximum} m`
}
function sectionMileageRange(row: Section): string {
  if (row.section_mileage_source === 'unavailable' || row.section_mileage_start_m === null) return '未生成'
  const start = formatMileageNumber(row.section_mileage_start_m)
  if (row.section_mileage_open_end) return `${start}+ m`
  if (row.section_mileage_end_m === null) return '未生成'
  return `${start}–${formatMileageNumber(row.section_mileage_end_m)} m`
}
function formatMileageNumber(value: number): string { return String(Number(value)) }
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
function turnbackDirectionLabel(value: string): string {
  return ({ none: '无', both: '双向', increasing_to_decreasing: '递增转递减', decreasing_to_increasing: '递减转递增', unknown: '未知' } as Record<string, string>)[value] || value || '--'
}
function sourceSyncLabel(value: string): string {
  return ({ matched: '已匹配', stale: '来源失效', conflict: '来源冲突', manual: '人工创建', legacy: 'AP旧资料', unavailable: '不可用' } as Record<string, string>)[value] || value || '--'
}
function sourceMatchLabel(value: string): string {
  return ({
    exact_source_key: '来源键精确',
    canonical_name: '规范名称',
    canonical_name_and_type: '规范名称与类型',
    alias: '来源别名',
    create: '新增',
    conflict: '冲突',
    manual_review: '待确认',
  } as Record<string, string>)[value] || value || '--'
}
function terminalSummary(row: Station): string {
  const values = []
  if (row.is_line_terminal) values.push('线路端点')
  if (row.is_service_terminal) values.push('运营终到/折返')
  return values.join(' / ') || '--'
}
function trackFacilityLabel(value: string): string {
  return ({ turnback_track: '折返线', crossover: '渡线', storage_track: '存车线', depot_connection: '出入段线', tail_track: '站后折返线', loop: '环形折返', siding: '其他侧线', other: '其他' } as Record<string, string>)[value] || value
}
function trackFacilitiesSummary(row: Station): string {
  return row.track_facilities.map(trackFacilityLabel).join(' / ') || '--'
}
function turnbackSummary(row: Station): string {
  if (!row.turnback_capable) return '不可折返'
  return `可折返 / ${turnbackDirectionLabel(row.turnback_direction)}`
}
function terminalExtensionSummary(row: Station): string {
  if (!row.is_line_terminal || !row.terminal_extension_enabled) return '--'
  const detail = [
    row.terminal_endpoint_label || '端点',
    row.terminal_extension_distance_m === null ? '' : `${row.terminal_extension_distance_m} m`,
    row.terminal_endpoint_mileage_text,
  ].filter(Boolean)
  return detail.join(' / ')
}
function sectionKindLabel(value: string): string {
  return ({ between_stations: '站间区间', terminal_extension: '端点延伸', depot_connection: '出入段连接', manual: '人工区间', legacy: '兼容区间' } as Record<string, string>)[value] || value || '--'
}
function sectionSourceLabel(row: Section): string {
  if (row.auto_generated) return (row.manual_override_fields || []).length ? '自动生成 · 已调整' : '自动生成'
  return ({ manual: '人工创建', template: '模板导入', legacy_ap_derived: '旧资料派生' } as Record<string, string>)[row.source_kind] || row.source_kind || '--'
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
        <el-button type="primary" :loading="saving" :disabled="locked || !dirty" @click="saveAllChanges()">保存</el-button>
      </div>
    </div>
    <el-alert
      v-if="store.error"
      :title="store.error"
      :type="store.backendOffline ? 'error' : 'warning'"
      :closable="false"
      show-icon
      class="page-error"
    >
      <details v-if="store.refreshErrors.length" class="refresh-error-details">
        <summary>查看失败详情（{{ store.refreshErrors.length }}）</summary>
        <ul>
          <li v-for="item in store.refreshErrors" :key="item.key">
            <strong>{{ item.label }}</strong>
            <span>错误码：{{ item.code || 'UNKNOWN_ERROR' }}</span>
            <span v-if="item.status > 0">HTTP {{ item.status }}</span>
            <span v-if="item.requestId">request_id：{{ item.requestId }}</span>
            <span>连续失败：{{ item.consecutiveFailures }} 次</span>
            <span>最近成功：{{ item.lastSuccessfulAt || '尚无成功记录' }}</span>
            <span>{{ item.retainedLastSuccess ? '已保留该项目最后成功数据' : '该项目暂无成功缓存' }}</span>
            <small>{{ item.path }}</small>
            <small>{{ item.originalMessage }}</small>
          </li>
        </ul>
      </details>
    </el-alert>
    <el-alert v-if="locked && writeDeniedReason" :title="writeDeniedReason" type="warning" :closable="false" show-icon class="page-error" />
    <el-alert v-if="saveIssues.length || localStationConflictGroups.length" title="基础资料校验失败" type="error" :closable="false" show-icon class="page-error">
      <div v-if="localStationConflictGroups.length" class="conflict-summary">
        <strong>{{ localStationConflictGroups[0].path_code }} 路径存在 {{ localStationConflictGroups.length }} 组主线顺序冲突</strong>
        <ul>
          <li v-for="group in localStationConflictGroups.slice(0, 8)" :key="group.group_id">
            顺序 {{ group.sort_order }}：{{ group.stations.map((station) => station.station_name).join(' / ') }}
          </li>
        </ul>
        <el-button type="danger" plain @click="openStationConflictDrawer">立即处理冲突</el-button>
      </div>
      <ul v-if="nonOrderSaveIssues.length" class="validation-list"><li v-for="issue in nonOrderSaveIssues" :key="`${issue.change_index}:${issue.code}:${issue.field_name}`">{{ issue.message }}</li></ul>
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
            <el-descriptions-item label="递增方向线路侧">
              <el-select
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.increasing_direction_line_side"
                filterable
                allow-create
                default-first-option
                @change="handleLineSideMappingChange"
              >
                <el-option label="右线" value="右线" />
                <el-option label="左线" value="左线" />
              </el-select>
              <span v-else>{{ store.summary?.increasing_direction_line_side || '右线' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="递减方向线路侧">
              <el-select
                v-if="editing && editingDraft"
                v-model="editingDraft.metadata.decreasing_direction_line_side"
                filterable
                allow-create
                default-first-option
                @change="handleLineSideMappingChange"
              >
                <el-option label="左线" value="左线" />
                <el-option label="右线" value="右线" />
              </el-select>
              <span v-else>{{ store.summary?.decreasing_direction_line_side || '左线' }}</span>
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
                <span class="selection-count">已选择 {{ selectedStationIds.length }} 项</span>
                <el-button :disabled="locked || saving || !selectedStationIds.length" @click="deleteSelectedStations">删除选中</el-button>
                <el-button :disabled="locked || saving || selectedStationIds.length < 2" @click="openStationCombination()">合并重复项</el-button>
                <el-button :disabled="locked || saving || selectedStationIds.length !== 2" @click="openStationTableOverwrite">覆盖更新</el-button>
                <el-button :disabled="locked || saving || !selectedStationIds.length" @click="undoSelectedStationChanges">撤销选中变更</el-button>
                <el-button :disabled="locked || saving || !localStationConflictGroups.length" @click="selectConflictStations">选择全部冲突项</el-button>
                <el-button :disabled="locked || !selectedStationIds.length" @click="clearStationSelection">清空选择</el-button>
                <el-button type="danger" plain :loading="clearAllLoading" :disabled="locked || dirty || saving" @click="openClearAllDialog">清空全部</el-button>
              </div>
              <el-alert v-if="stationRows.length === 0 && sectionRows.length === 0" title="当前局点尚未配置站点与区间，可从设备管理重新生成或手动新增。" type="info" :closable="false" show-icon />
              <NcDataTable ref="stationTable" table-id="rail-base-stations" route-key="/rail-transit/base-data" :data="stationRows" :columns="stationEditColumns" row-key="id" height="calc(100vh - 410px)" empty-text="当前局点尚未配置站点与区间，可从设备管理重新生成或手动新增。" @selection-change="handleStationSelection">
                <template #cell-sort_order="{ row }"><el-input-number v-if="canEditRow('station', row.id) && row.participates_in_direction" v-model="row.sort_order" :min="0" controls-position="right" @change="markStation(row)" /><span v-else>{{ row.sort_order ?? '--' }}</span></template>
                <template #cell-name="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.name" :class="{ 'field-error': fieldError('station', row.id, 'name') }" @input="markStation(row)" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-code="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.code" :class="{ 'field-error': fieldError('station', row.id, 'code') }" @input="markStation(row)" /><span v-else>{{ display(row.code) }}</span></template>
                <template #cell-node_type="{ row }">
                  <el-select v-if="canEditRow('station', row.id)" v-model="row.node_type" @change="handleStationClassificationChange(row)">
                    <el-option label="普通车站" value="station" />
                    <el-option label="停车场" value="parking_lot" />
                    <el-option label="车辆段" value="depot" />
                    <el-option label="接轨点" value="connection_point" />
                    <el-option label="其他" value="other" />
                  </el-select>
                  <el-tag v-else :type="stationNodeTypeTag(row.node_type)">{{ stationNodeTypeLabel(row.node_type) }}</el-tag>
                </template>
                <template #cell-path_code="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.path_code" @change="handleStationClassificationChange(row)" /><span v-else>{{ display(row.path_code) }}</span></template>
                <template #cell-participates_in_direction="{ row }"><el-switch v-if="canEditRow('station', row.id)" v-model="row.participates_in_direction" @change="markStation(row)" /><span v-else>{{ boolText(row.participates_in_direction) }}</span></template>
                <template #cell-center_mileage_text="{ row }">
                  <el-tooltip content="站点在线路上的中心参考里程，用于后续区间定位和运行方向分析。" placement="top">
                    <el-input v-if="canEditRow('station', row.id)" v-model="row.center_mileage_text" placeholder="如 K12+345" @input="markStation(row)" />
                    <span v-else>{{ display(row.center_mileage_text) }}</span>
                  </el-tooltip>
                </template>
                <template #cell-structure_platform="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="compact-pair">
                    <el-select v-model="row.structure_type" @change="markStation(row)"><el-option label="未填写" value="unknown" /><el-option label="地下" value="underground" /><el-option label="高架" value="elevated" /><el-option label="地面" value="at_grade" /><el-option label="路堑" value="cutting" /><el-option label="混合" value="mixed" /></el-select>
                    <el-select v-model="row.platform_layout" @change="markStation(row)"><el-option label="未填写" value="unknown" /><el-option label="岛式" value="island" /><el-option label="侧式" value="side" /><el-option label="混合式" value="mixed" /><el-option label="叠岛式" value="stacked_island" /><el-option label="叠侧式" value="stacked_side" /><el-option label="分离式" value="separated" /></el-select>
                  </div>
                  <span v-else>{{ structureTypeLabel(row.structure_type) }} / {{ platformLayoutLabel(row.platform_layout) }}</span>
                </template>
                <template #cell-terminals="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="inline-checks">
                    <el-tooltip content="线路端点：轨道线路实际到这里结束，通常是主线起点或终点。" placement="top">
                      <el-checkbox v-model="row.is_line_terminal" @change="handleLineTerminalChange(row)">线路端点</el-checkbox>
                    </el-tooltip>
                    <el-tooltip content="运营终到/折返：正常运营列车会在这里作为终到、始发或折返站。" placement="top">
                      <el-checkbox v-model="row.is_service_terminal" @change="markStation(row)">运营终到/折返</el-checkbox>
                    </el-tooltip>
                  </div>
                  <span v-else>{{ terminalSummary(row) }}</span>
                </template>
                <template #cell-track_facilities="{ row }">
                  <el-tooltip content="该站具备的实际轨道设施，可同时选择折返线、渡线、存车线、出入段线等多项。" placement="top">
                    <el-select v-if="canEditRow('station', row.id)" v-model="row.track_facilities" multiple clearable collapse-tags :max-collapse-tags="2" @change="markStation(row)">
                      <el-option label="折返线" value="turnback_track" />
                      <el-option label="渡线" value="crossover" />
                      <el-option label="存车线" value="storage_track" />
                      <el-option label="出入段线" value="depot_connection" />
                      <el-option label="站后折返线" value="tail_track" />
                      <el-option label="环形折返" value="loop" />
                      <el-option label="其他侧线" value="siding" />
                      <el-option label="其他" value="other" />
                    </el-select>
                    <div v-else class="facility-tags">
                      <el-tag v-for="facility in row.track_facilities" :key="facility" type="info">{{ trackFacilityLabel(facility) }}</el-tag>
                      <span v-if="!row.track_facilities.length">--</span>
                    </div>
                  </el-tooltip>
                </template>
                <template #cell-turnback="{ row }">
                  <div v-if="canEditRow('station', row.id)" class="compact-pair">
                    <el-switch v-model="row.turnback_capable" @change="markStation(row)" />
                    <el-select v-model="row.turnback_direction" :disabled="!row.turnback_capable" @change="markStation(row)"><el-option label="无" value="none" /><el-option label="双向" value="both" /><el-option label="递增转递减" value="increasing_to_decreasing" /><el-option label="递减转递增" value="decreasing_to_increasing" /><el-option label="未知" value="unknown" /></el-select>
                  </div>
                  <span v-else>{{ turnbackSummary(row) }}</span>
                </template>
                <template #cell-terminal_extension="{ row }">
                  <el-tooltip content="终点站外侧至线路物理端点之间仍存在一段轨道时启用。" placement="top">
                    <div v-if="canEditRow('station', row.id) && row.is_line_terminal" class="terminal-extension-editor">
                      <el-checkbox v-model="row.terminal_extension_enabled" @change="markStation(row)">启用</el-checkbox>
                      <template v-if="row.terminal_extension_enabled">
                        <el-input v-model="row.terminal_endpoint_label" placeholder="端点名称" @input="markStation(row)" />
                        <el-input-number v-model="row.terminal_extension_distance_m" :min="0" :precision="1" controls-position="right" placeholder="距离" @change="markStation(row)" />
                        <el-input v-model="row.terminal_endpoint_mileage_text" placeholder="端点里程" @input="markStation(row)" />
                      </template>
                    </div>
                    <span v-else>{{ terminalExtensionSummary(row) }}</span>
                  </el-tooltip>
                </template>
                <template #cell-source_sync_status="{ row }"><el-tag :type="stateType(row.source_sync_status)">{{ sourceSyncLabel(row.source_sync_status) }}</el-tag></template>
                <template #cell-remark="{ row }"><el-input v-if="canEditRow('station', row.id)" v-model="row.remark" @input="markStation(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('station', row)">移除</el-button><template v-if="isPendingDelete('station', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('station', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('station', row)">删除</el-button></template>
              </NcDataTable>
            </el-tab-pane>
            <el-tab-pane label="区间" name="sections">
              <div class="edit-toolbar">
                <el-button :icon="Connection" :loading="store.sectionGenerationLoading" @click="openSectionGenerationPreview">根据站点生成区间</el-button>
                <label class="inline-file-button">
                  <el-icon><UploadFilled /></el-icon><span>导入模板</span>
                  <input type="file" accept=".xlsx" @change="handleStationTemplateFile" />
                </label>
                <el-button :icon="Download" @click="exportCurrentStations">导出当前</el-button>
                <el-button :icon="Plus" :disabled="locked || saving" @click="addSection">新增区间</el-button>
              </div>
              <NcDataTable table-id="rail-base-sections" route-key="/rail-transit/base-data" :data="sectionRows" :columns="sectionEditColumns" height="calc(100vh - 410px)" empty-text="当前局点尚未配置站点与区间，可从设备管理重新生成或手动新增。">
                <template #cell-name="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.name" data-field="section-name" :class="{ 'field-error': fieldError('section', row.id, 'name') }" @input="markSectionField(row, 'name')" /><span v-else>{{ display(row.name) }}</span></template>
                <template #cell-section_kind="{ row }">
                  <el-select v-if="canEditRow('section', row.id)" v-model="row.section_kind" @change="handleSectionKindChange(row)"><el-option label="站间区间" value="between_stations" /><el-option label="端点延伸" value="terminal_extension" /><el-option label="人工区间" value="manual" /><el-option label="出入段连接" value="depot_connection" /></el-select>
                  <el-tag v-else :type="row.section_kind === 'terminal_extension' ? 'warning' : row.auto_generated ? 'success' : 'info'">{{ sectionKindLabel(row.section_kind) }}</el-tag>
                </template>
                <template #cell-path_code="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.path_code" @input="markSectionField(row, 'path_code')" /><span v-else>{{ display(row.path_code) }}</span></template>
                <template #cell-start_station="{ row }">
                  <el-select v-if="canEditRow('section', row.id)" :model-value="sectionNodeValue(row, 'start')" data-field="section-start-node" filterable allow-create default-first-option @change="(value: string) => handleSectionNodeChange(row, 'start', value)">
                    <el-option v-for="option in sectionNodeOptions" :key="`start:${option.uid}`" :label="option.display_label" :value="option.uid" />
                  </el-select>
                  <span v-else>{{ display(row.start_station) }}</span>
                </template>
                <template #cell-end_station="{ row }">
                  <el-select v-if="canEditRow('section', row.id)" :model-value="sectionNodeValue(row, 'end')" data-field="section-end-node" filterable allow-create default-first-option @change="(value: string) => handleSectionNodeChange(row, 'end', value)">
                    <el-option v-for="option in sectionNodeOptions" :key="`end:${option.uid}`" :label="option.display_label" :value="option.uid" />
                  </el-select>
                  <span v-else>{{ display(row.end_station) }}</span>
                </template>
                <template #cell-line_direction="{ row }">
                  <el-select v-if="canEditRow('section', row.id)" v-model="row.line_direction" data-field="section-direction" @change="(value: string) => handleSectionDirectionChange(row, value)">
                    <el-option :label="editingDraft?.metadata.increasing_direction_name || store.summary?.increasing_direction_name || '上行'" :value="editingDraft?.metadata.increasing_direction_name || store.summary?.increasing_direction_name || '上行'" />
                    <el-option :label="editingDraft?.metadata.decreasing_direction_name || store.summary?.decreasing_direction_name || '下行'" :value="editingDraft?.metadata.decreasing_direction_name || store.summary?.decreasing_direction_name || '下行'" />
                  </el-select>
                  <span v-else>{{ display(row.line_direction || row.line_side) }}</span>
                </template>
                <template #cell-section_mileage_range="{ row }">
                  <div v-if="canEditRow('section', row.id)" class="section-mileage-editor">
                    <el-input-number v-model="row.section_mileage_start_m" data-field="section-mileage-start" :min="0" :controls="false" placeholder="起点" @change="markSectionMileage(row, 'section_mileage_start_m')" />
                    <span>至</span>
                    <el-input-number v-model="row.section_mileage_end_m" data-field="section-mileage-end" :min="0" :controls="false" placeholder="终点" :disabled="row.section_mileage_open_end" @change="markSectionMileage(row, 'section_mileage_end_m')" />
                    <el-checkbox :model-value="row.section_mileage_open_end" data-field="section-mileage-open-end" :disabled="row.section_kind !== 'terminal_extension'" @change="(value: boolean) => handleSectionMileageOpenEnd(row, value)">开放</el-checkbox>
                  </div>
                  <span v-else>{{ sectionMileageRange(row) }}</span>
                </template>
                <template #cell-source_kind="{ row }"><el-tag :type="row.auto_generated ? 'success' : row.source_kind === 'legacy_ap_derived' ? 'warning' : 'info'">{{ sectionSourceLabel(row) }}</el-tag></template>
                <template #cell-enabled="{ row }"><el-switch v-if="canEditRow('section', row.id)" v-model="row.enabled" @change="markSectionField(row, 'enabled')" /><el-tag v-else :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag></template>
                <template #cell-remark="{ row }"><el-input v-if="canEditRow('section', row.id)" v-model="row.remark" @input="markSection(row)" /><span v-else>{{ display(row.remark) }}</span></template>
                <template #cell-edit_actions="{ row }"><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.auto_generated && !locked && !saving" link type="primary" @click="restoreSectionAutomaticValues(row)">恢复自动值</el-button><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('section', row)">移除</el-button><template v-if="isPendingDelete('section', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('section', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('section', row)">删除</el-button></template>
              </NcDataTable>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP" name="trackside-ap">
          <div class="filter-bar">
            <el-input v-model="store.apFilters.query" clearable placeholder="AP 名称 / 点位 / MAC / IP" @keyup.enter="store.applyApFilters" />
            <el-input v-model="store.apFilters.station" clearable placeholder="归属站点" />
            <el-input v-model="store.apFilters.section" clearable placeholder="归属区间" />
            <el-select v-model="store.apFilters.has_issue" clearable placeholder="数据质量"><el-option label="只看异常" :value="true" /><el-option label="只看正常" :value="false" /></el-select>
            <el-button type="primary" :disabled="!locked" @click="store.applyApFilters">应用筛选</el-button>
            <input ref="tracksideApImportInput" type="file" accept=".xlsx,.csv,.json" hidden @change="handleTracksideApFile">
            <el-button v-if="isFeatureEnabled('web.rail_trackside_ap_base_io')" :icon="Download" :disabled="apBaseTaskRunning" @click="startApBaseExport(true)">下载模板</el-button>
            <el-button v-if="isFeatureEnabled('web.rail_trackside_ap_base_io')" :icon="UploadFilled" :loading="store.previewLoading" :disabled="saving" @click="tracksideApImportInput?.click()">导入并预览</el-button>
            <el-button v-if="isFeatureEnabled('web.rail_trackside_ap_base_io')" :icon="Download" :disabled="apBaseTaskRunning" @click="startApBaseExport(false)">导出当前</el-button>
            <el-button v-if="isFeatureEnabled('web.rail_trackside_ap_base_io')" :icon="Download" :disabled="apBaseTaskRunning" @click="startApRenameCommandExport">导出重命名命令</el-button>
            <el-button :icon="Plus" :disabled="locked || saving" @click="addAp">新增轨旁 AP</el-button>
          </div>
          <NcDataTable table-id="rail-base-trackside-aps" route-key="/rail-transit/base-data" :data="apRows" :columns="apColumns" height="calc(100vh - 430px)" empty-text="暂无轨旁 AP 扩展资料">
            <template #cell-name="{ row }"><span>{{ row.runtime.fit_ap_name || row.name || row.point_code || '--' }}</span></template>
            <template #cell-point_code="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.point_code" :class="{ 'field-error': fieldError('trackside_ap', row.id, 'point_code') }" @input="markAp(row)" /><span v-else>{{ display(row.point_code) }}</span></template>
            <template #cell-mac="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.mac" :class="{ 'field-error': fieldError('trackside_ap', row.id, 'mac') }" @input="markAp(row)" /><span v-else>{{ display(row.mac) }}</span></template>
            <template #cell-station="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.station" @input="markAp(row)" /><span v-else>{{ display(row.station) }}</span></template>
            <template #cell-section="{ row }"><el-select v-if="canEditRow('trackside_ap', row.id)" v-model="row.section" filterable allow-create default-first-option @change="handleApSectionChange(row)"><el-option v-for="section in sectionRows" :key="section.id" :label="section.name" :value="section.name" /></el-select><span v-else>{{ display(row.section) }}</span></template>
            <template #cell-mileage="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.mileage.raw" @input="markAp(row)" /><span v-else>{{ row.mileage.normalized || row.mileage.raw || '--' }}</span></template>
            <template #cell-direction="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.direction" @input="markAp(row)" /><span v-else>{{ display(row.direction) }}</span></template>
            <template #cell-remark="{ row }"><el-input v-if="canEditRow('trackside_ap', row.id)" v-model="row.remark" @input="markAp(row)" /><span v-else>{{ display(row.remark) }}</span></template>
            <template #cell-fit_ap_status="{ row }"><el-tag :type="stateType(row.runtime.fit_ap_status)">{{ row.runtime.fit_ap_status }}</el-tag></template>
            <template #cell-optical_status="{ row }"><el-tag :type="stateType(row.runtime.optical_status)">{{ row.runtime.optical_status }}</el-tag></template>
            <template #cell-issues="{ row }"><el-tag v-if="row.issue_count" :type="issueType(row.highest_issue_severity)">{{ row.issue_count }}</el-tag><span v-else>--</span></template>
            <template #cell-actions="{ row }"><el-button link type="primary" @click="openApAc(row)">FIT-AP</el-button><el-tag v-if="row.id.startsWith('new:')" type="success">新增</el-tag><el-button v-if="row.id.startsWith('new:')" link type="danger" :disabled="saving" @click="deleteEntity('trackside_ap', row)">移除</el-button><template v-if="isPendingDelete('trackside_ap', row.id)"><el-tag type="danger">待删除</el-tag><el-button link type="primary" @click="undoDelete('trackside_ap', row)">撤销</el-button></template><el-button v-else-if="!row.id.startsWith('new:')" link type="danger" :disabled="locked || saving" @click="deleteEntity('trackside_ap', row)">删除</el-button></template>
          </NcDataTable>
          <el-pagination background :disabled="!locked" layout="total, prev, pager, next, sizes" :total="store.apTotal" :current-page="store.apFilters.page" :page-size="store.apFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setApPage" @size-change="(size: number) => { store.apFilters.page_size = size; store.applyApFilters() }" />
          <el-dialog v-model="apImportDialogVisible" title="轨旁 AP 导入预览" width="min(1400px, 94vw)" destroy-on-close>
            <template v-if="store.importPreview">
              <el-descriptions :column="5" border>
                <el-descriptions-item label="文件名">{{ store.importPreview.file_name }}</el-descriptions-item><el-descriptions-item label="工作表">{{ store.importPreview.sheet_names?.join('、') || '--' }}</el-descriptions-item><el-descriptions-item label="模板类型">{{ templateLabel(store.importPreview.template_type) }}</el-descriptions-item><el-descriptions-item label="总行数">{{ store.importPreview.total_rows }}</el-descriptions-item><el-descriptions-item label="可导入">{{ previewImportableCount }}</el-descriptions-item>
                <el-descriptions-item label="新增">{{ store.importPreview.merge_plan?.summary.create_count || 0 }}</el-descriptions-item><el-descriptions-item label="更新">{{ store.importPreview.merge_plan?.summary.update_count || 0 }}</el-descriptions-item><el-descriptions-item label="不变">{{ store.importPreview.merge_plan?.summary.unchanged_count || 0 }}</el-descriptions-item><el-descriptions-item label="警告">{{ store.importPreview.merge_plan?.summary.warning_count || 0 }}</el-descriptions-item><el-descriptions-item label="冲突">{{ store.importPreview.merge_plan?.summary.conflict_count || 0 }}</el-descriptions-item>
                <el-descriptions-item label="无效">{{ store.importPreview.merge_plan?.summary.invalid_count || 0 }}</el-descriptions-item><el-descriptions-item label="缺少里程">{{ store.importPreview.statistics?.missing_mileage_rows || 0 }}</el-descriptions-item><el-descriptions-item label="未匹配 FIT-AP">{{ store.importPreview.merge_plan?.summary.unmatched_fit_ap_count || 0 }}</el-descriptions-item>
              </el-descriptions>
              <el-alert v-if="store.importPreview.merge_plan?.summary.unmatched_fit_ap_count" title="当前局点暂无对应 FIT-AP 运行态资料，不影响基础资料导入及 MR 日志识别。" type="warning" :closable="false" show-icon />
              <NcDataTable table-id="rail-base-trackside-ap-direct-preview" route-key="/rail-transit/base-data" :data="mergeRows" :columns="mergeColumns" height="430" empty-text="当前文件没有可预览数据">
                <template #cell-expand="{ row }"><NcDataTable table-id="rail-base-trackside-ap-direct-field-diffs" route-key="/rail-transit/base-data" :preference-scope="String(row.row_number)" :data="row.field_diffs" :columns="mergeFieldColumns" compact :show-column-settings="false"><template #cell-decision="{ row: field }"><el-select v-if="field.action === 'manual_review'" v-model="decisionSelections[decisionKey(row.row_number, field.field_name)]" placeholder="请选择"><el-option label="保留正式值" value="keep_existing" /><el-option label="采用导入值" value="use_imported" /></el-select><span v-else>{{ field.action }}</span></template></NcDataTable></template>
                <template #cell-result="{ row }"><el-tag :type="mergeType(row.result)">{{ row.result }}</el-tag></template>
              </NcDataTable>
            </template>
            <template #footer><el-button @click="apImportDialogVisible = false">关闭</el-button><el-button :icon="Download" :disabled="!previewProblemRows.length" @click="exportImportIssues">导出问题明细</el-button><el-button type="primary" :disabled="locked || saving || previewImportableCount <= 0" @click="handleApply">导入 {{ previewImportableCount }} 条有效数据到草稿</el-button></template>
          </el-dialog>
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP 规划" name="trackside-ap-planning">
          <TracksideApPlanningTab
            ref="planningTab"
            :locked="locked"
            :saving="saving"
            :stations="stationRows.map((row) => ({ id: row.id, name: row.name, sort_order: row.sort_order }))"
            :line-name="store.summary?.line_name || store.summary?.site_name || ''"
            @change="handlePlanningChange"
            @save="saveTracksideApPlanning"
          />
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
          <el-alert title="逐行校验并导入有效数据" description="支持 XLSX、CSV、JSON；冲突和无效行会跳过，未匹配 FIT-AP 仅提示且不影响基础资料导入。" type="info" :closable="false" show-icon />
          <div class="preview-toolbar">
            <label class="file-picker"><el-icon><UploadFilled /></el-icon><span>{{ store.selectedFileName || '选择预览文件' }}</span><input type="file" accept=".xlsx,.csv,.json" @change="handleFile" /></label>
            <span v-if="store.importPreview">{{ formatBytes(store.importPreview.file_size) }} · {{ templateLabel(store.importPreview.template_type) }} · 工作表 {{ store.importPreview.sheet_names?.join('、') || '--' }} · 置信度 {{ store.importPreview.confidence_score }}</span>
          </div>
          <div v-if="store.importPreview" class="preview-summary">
            <article><span>解析行数</span><strong>{{ store.importPreview.total_rows }}</strong></article>
            <article class="normal"><span>可导入</span><strong>{{ previewImportableCount }}</strong></article>
            <article class="normal"><span>新增</span><strong>{{ store.importPreview.merge_plan?.summary.create_count || 0 }}</strong></article>
            <article><span>更新</span><strong>{{ store.importPreview.merge_plan?.summary.update_count || 0 }}</strong></article>
            <article><span>不变</span><strong>{{ store.importPreview.merge_plan?.summary.unchanged_count || 0 }}</strong></article>
            <article class="warning"><span>警告</span><strong>{{ store.importPreview.merge_plan?.summary.warning_count || 0 }}</strong></article>
            <article class="danger"><span>冲突</span><strong>{{ store.importPreview.merge_plan?.summary.conflict_count || 0 }}</strong></article>
            <article class="danger"><span>无效</span><strong>{{ store.importPreview.merge_plan?.summary.invalid_count || 0 }}</strong></article>
            <article class="warning"><span>未匹配 FIT-AP</span><strong>{{ store.importPreview.merge_plan?.summary.unmatched_fit_ap_count || 0 }}</strong></article>
            <template v-if="store.importPreview.template_type === 'ap_switch_port_point_table'">
              <article><span>带归属区间</span><strong>{{ store.importPreview.statistics?.section_rows || 0 }}</strong></article>
              <article><span>无归属区间</span><strong>{{ store.importPreview.statistics?.without_section_rows || 0 }}</strong></article>
              <article class="warning"><span>缺少里程（允许）</span><strong>{{ store.importPreview.statistics?.missing_mileage_rows || 0 }}</strong></article>
              <article class="warning"><span>无效占位行</span><strong>{{ store.importPreview.statistics?.placeholder_rows || 0 }}</strong></article>
            </template>
          </div>
          <div v-if="store.importPreview" class="preview-actions">
            <el-radio-group v-model="previewFilter" class="preview-filter"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="CREATE">新增</el-radio-button><el-radio-button value="UPDATE">更新</el-radio-button><el-radio-button value="UNCHANGED">不变</el-radio-button><el-radio-button value="WARNING">警告</el-radio-button><el-radio-button value="CONFLICT">仅显示冲突</el-radio-button><el-radio-button value="INVALID">仅显示无效</el-radio-button></el-radio-group>
            <div v-if="!locked" class="apply-controls">
              <el-button :icon="Download" :disabled="!previewProblemRows.length" @click="exportImportIssues">导出问题明细</el-button>
              <el-button type="primary" :disabled="saving || previewImportableCount <= 0" @click="handleApply">导入 {{ previewImportableCount }} 条有效数据到草稿</el-button>
            </div>
            <div v-else class="apply-controls"><el-button :icon="Download" :disabled="!previewProblemRows.length" @click="exportImportIssues">导出问题明细</el-button><el-tag type="info">解锁后可导入有效数据到草稿</el-tag></div>
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

    <el-dialog v-model="clearAllDialogVisible" title="清空当前局点全部站点与区间" width="min(620px, 92vw)" append-to-body :close-on-click-modal="false">
      <div v-if="clearAllPreview" class="preview-dialog">
        <el-alert
          title="此操作不可撤销"
          description="将删除当前局点的全部站点、区间及其排序配置。轨旁 AP、列车、设备管理中的原始设备不会被删除。此操作不可撤销。"
          type="error"
          :closable="false"
          show-icon
        />
        <div class="preview-summary clear-summary">
          <article class="danger"><span>站点数量</span><strong>{{ clearAllPreview.station_count }}</strong></article>
          <article class="danger"><span>上下行区间数量</span><strong>{{ clearAllPreview.section_count }}</strong></article>
          <article class="warning"><span>受影响的轨旁 AP 关联</span><strong>{{ clearAllPreview.affected_trackside_ap_count }}</strong></article>
        </div>
        <p class="clear-note">清空后轨旁 AP 将显示为“未关联”，不会保留已失效的站点或区间 ID。</p>
      </div>
      <template #footer>
        <el-button :disabled="clearAllLoading" @click="clearAllDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="clearAllLoading" @click="executeClearAll">确认清空全部</el-button>
      </template>
    </el-dialog>

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
          <article class="normal"><span>规范名匹配</span><strong>{{ store.stationSourcePreview.canonical_match_count }}</strong></article>
          <article class="normal"><span>建议覆盖</span><strong>{{ store.stationSourcePreview.recommended_overwrite_count || 0 }}</strong></article>
          <article class="warning"><span>建议合并</span><strong>{{ store.stationSourcePreview.recommended_merge_count || 0 }}</strong></article>
          <article class="danger"><span>冲突</span><strong>{{ store.stationSourcePreview.conflict_count }}</strong></article>
          <article class="warning"><span>待人工确认</span><strong>{{ store.stationSourcePreview.manual_review_count }}</strong></article>
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
          <template #cell-match_status="{ row }"><el-tag :type="row.match_status === 'conflict' ? 'danger' : ['exact_source_key', 'canonical_name', 'canonical_name_and_type', 'alias'].includes(row.match_status) ? 'success' : 'info'">{{ sourceMatchLabel(row.match_status) }}</el-tag></template>
          <template #cell-processing_strategy="{ row }">
            <div class="source-strategy">
              <el-select
                :model-value="stationSourceStrategy(row)"
                :disabled="locked"
                @change="(value: StationSourceProcessingStrategy) => updateStationSourceStrategy(row, value)"
              >
                <el-option
                  v-for="strategy in (row.processing_options?.length ? row.processing_options : ['manual_target', 'ignore'])"
                  :key="strategy"
                  :label="stationSourceStrategyLabel(strategy)"
                  :value="strategy"
                />
              </el-select>
              <el-select
                v-if="['overwrite_existing', 'manual_target', 'merge_duplicates'].includes(stationSourceStrategy(row))"
                v-model="stationSourceTargets[row.candidate_id]"
                placeholder="选择正式目标"
                :disabled="locked"
              >
                <el-option
                  v-for="station in stationSourceTargetOptions(row)"
                  :key="station.id"
                  :label="`${station.code || '--'} · ${station.name}`"
                  :value="station.id"
                />
              </el-select>
            </div>
          </template>
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
        <el-button :disabled="locked" @click="selectSuggestedStationSources">全选建议项</el-button>
        <el-button :disabled="locked" @click="selectStationSourcesByStrategy('overwrite_existing')">全部覆盖匹配项</el-button>
        <el-button :disabled="locked" @click="selectStationSourcesByStrategy('create')">仅新增未匹配项</el-button>
        <el-button
          type="primary"
          :disabled="locked || saving || selectedStationSourceIds.length === 0"
          @click="applyStationSourceToDraft"
        >应用到当前草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stationDeletePreflightVisible" title="站点删除依赖预检" width="min(1040px, 94vw)" append-to-body destroy-on-close>
      <el-alert
        v-if="stationDeletePreflightItems.some((item) => item.status !== 'SAFE_DELETE')"
        title="存在不能直接删除的站点"
        description="REQUIRES_MERGE 与 BLOCKED 项不会被静默跳过或加入删除草稿；请取消这些项并先完成合并或引用调整。"
        type="warning"
        :closable="false"
        show-icon
      />
      <div v-loading="stationDeletePreflightLoading" class="preflight-list">
        <article v-for="item in stationDeletePreflightItems" :key="item.station_id" :class="`preflight-${item.status.toLowerCase()}`">
          <header>
            <strong>{{ item.code || '--' }} · {{ item.station_name }}</strong>
            <el-tag :type="item.status === 'SAFE_DELETE' ? 'success' : item.status === 'REQUIRES_MERGE' ? 'warning' : 'danger'">{{ item.status }}</el-tag>
          </header>
          <p>主线顺序：{{ item.sort_order ?? '--' }}；来源：{{ item.source_kind }}；{{ item.reason }}</p>
          <p>
            引用区间 {{ item.references.section_start_count + item.references.section_end_count }}；
            轨旁 AP {{ item.references.ap_count }}；
            其他关系 {{ item.references.relation_count }}；
            端点延伸 {{ item.references.endpoint_extension_count }}；
            AP 规划 {{ item.references.plan_count }}
          </p>
        </article>
      </div>
      <template #footer>
        <el-button @click="stationDeletePreflightVisible = false">取消</el-button>
        <el-button
          type="danger"
          :disabled="!stationDeletePreflightItems.some((item) => item.status === 'SAFE_DELETE')"
          @click="applySafeStationDeletes"
        >仅标记安全项</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stationMergeDialogVisible" title="合并重复站点" width="min(980px, 94vw)" append-to-body destroy-on-close>
      <el-alert title="合并只生成一个原子草稿计划；最终保存仍执行 revision 校验、完整引用校验和单事务回滚。" type="info" :closable="false" show-icon />
      <el-form label-width="130px" class="station-resolution-form">
        <el-form-item label="保留目标">
          <el-select v-model="stationMergeTargetId" @change="handleStationCombinationTargetChange">
            <el-option v-for="station in stationMergeMembers.filter((item) => !item.id.startsWith('new:'))" :key="station.id" :label="`${station.code || '--'} · ${station.name}`" :value="station.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称取值">
          <el-select v-model="stationMergeNameSourceId"><el-option v-for="station in stationMergeMembers" :key="station.id" :label="station.name" :value="station.id" /></el-select>
        </el-form-item>
        <el-form-item label="编号取值">
          <el-select v-model="stationMergeCodeSourceId"><el-option v-for="station in stationMergeMembers" :key="station.id" :label="`${station.code || '--'} · ${station.name}`" :value="station.id" /></el-select>
        </el-form-item>
        <el-form-item label="主线顺序取值">
          <el-select v-model="stationMergeOrderSourceId" @change="handleStationCombinationOrderSourceChange"><el-option v-for="station in stationMergeMembers" :key="station.id" :label="`${station.sort_order ?? '--'} · ${station.name}`" :value="station.id" /></el-select>
        </el-form-item>
        <el-form-item label="合并选项">
          <el-checkbox v-model="stationMergeSourceInfo">合并设备来源信息</el-checkbox>
          <el-checkbox v-model="stationMergeRemarks">合并备注</el-checkbox>
        </el-form-item>
      </el-form>
      <div class="resolution-members">
        <strong>将被合并删除：</strong>
        {{ stationMergeSources.map((station) => station.name).join('、') || '--' }}
      </div>
      <div class="overwrite-diffs">
        <article v-for="diff in stationCombinationDiffRows" :key="diff.field">
          <strong>{{ diff.field }}</strong>
          <span>{{ display(diff.current) }}</span>
          <span>→</span>
          <span>{{ display(diff.proposed) }}</span>
        </article>
      </div>
      <el-alert v-for="error in stationMergeErrors" :key="error" :title="error" type="error" :closable="false" show-icon />
      <template #footer>
        <el-button @click="stationMergeDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="stationMergeErrors.length > 0" @click="applyStationCombination">应用合并到草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="stationOverwriteDialogVisible" title="来源覆盖现有站点" width="min(1040px, 94vw)" append-to-body destroy-on-close>
      <el-alert title="目标 id、node_uid、区间/AP/关系引用和人工字段默认保持不变。只有下方明确勾选的人工字段才会覆盖。" type="warning" :closable="false" show-icon />
      <div class="resolution-target">
        正式目标：<strong>{{ stationOverwriteTarget?.name || '--' }}</strong>
        <span>来源：{{ stationOverwriteCandidate?.source_station_value || stationOverwriteSourceStation?.name || '--' }}</span>
      </div>
      <div class="overwrite-diffs">
        <article v-for="diff in stationOverwriteDiffRows" :key="String(diff.field)">
          <el-checkbox
            v-if="diff.protectedManualField"
            :model-value="stationOverwriteManualFields.includes(String(diff.field))"
            @change="(checked: boolean) => stationOverwriteManualFields = checked ? [...stationOverwriteManualFields, String(diff.field)] : stationOverwriteManualFields.filter((field) => field !== diff.field)"
          >允许覆盖人工字段</el-checkbox>
          <el-tag v-else type="success">来源覆盖</el-tag>
          <strong>{{ diff.field }}</strong>
          <span>{{ display(diff.current) }}</span>
          <span>→</span>
          <span>{{ display(diff.proposed) }}</span>
        </article>
      </div>
      <template #footer>
        <el-button @click="stationOverwriteDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!stationOverwriteTarget || (!stationOverwriteCandidate && !stationOverwriteSourceStation)" @click="applyStationOverwrite">应用覆盖到草稿</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="stationConflictDrawerVisible" title="主线顺序冲突处理" size="min(760px, 96vw)" append-to-body>
      <el-alert title="每组操作只修改当前前端草稿，不会立即写入数据库。" type="info" :closable="false" show-icon />
      <div v-loading="stationConflictLoading" class="conflict-groups">
        <article v-for="group in stationConflictGroups" :key="group.group_id">
          <header><strong>{{ group.path_code }} · 顺序 {{ group.sort_order }}</strong><el-tag type="danger">{{ group.stations.length }} 项</el-tag></header>
          <p>{{ group.stations.map((station) => `${station.code || '--'} ${station.station_name}`).join(' / ') }}</p>
          <p>{{ group.reason }}</p>
          <div class="conflict-actions">
            <el-button v-for="station in group.stations" :key="station.station_id" size="small" @click="keepConflictStation(group, station.station_id)">仅保留 {{ station.station_name }} 参与方向</el-button>
            <el-button size="small" type="primary" @click="combineConflictGroup(group)">合并</el-button>
            <el-button size="small" @click="overwriteConflictGroup(group)">来源覆盖现有</el-button>
            <el-button size="small" @click="stationConflictDrawerVisible = false">手动修改顺序</el-button>
            <el-button size="small" @click="stationConflictDrawerVisible = false">暂不处理</el-button>
          </div>
        </article>
      </div>
    </el-drawer>

    <el-dialog v-model="stationTemplateDialogVisible" title="基础资料模板导入预览" width="min(1280px, 96vw)" append-to-body destroy-on-close>
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
        <el-alert
          v-if="!store.stationTemplatePreview.section_sheet_present"
          title="模板未包含区间配置"
          description="本次只预览线路和站点，不会删除或修改当前区间草稿。"
          type="info"
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
          <el-descriptions-item label="递增方向线路侧">{{ display(store.stationTemplatePreview.line_metadata.increasing_direction_line_side) }}</el-descriptions-item>
          <el-descriptions-item label="递减方向线路侧">{{ display(store.stationTemplatePreview.line_metadata.decreasing_direction_line_side) }}</el-descriptions-item>
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
        <el-divider content-position="left">线路节点</el-divider>
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
        <template v-if="store.stationTemplatePreview.section_sheet_present">
          <el-divider content-position="left">区间配置</el-divider>
          <NcDataTable
            table-id="rail-base-section-template-preview"
            route-key="/rail-transit/base-data"
            :data="stationTemplateSectionRows"
            :columns="stationTemplateSectionColumns"
            height="320px"
            empty-text="模板中没有区间配置"
          >
            <template #cell-selected="{ row }">
              <el-checkbox
                :model-value="isStationTemplateSectionRowSelected(row)"
                :disabled="isStationTemplateSectionRowDisabled(row)"
                @change="(checked: boolean) => toggleTemplateSectionRow(row, checked)"
              />
            </template>
            <template #cell-action="{ row }"><el-tag :type="row.action === 'conflict' ? 'danger' : row.action === 'create' ? 'success' : 'info'">{{ row.action }}</el-tag></template>
            <template #cell-issues="{ row }">
              <div class="row-issues">
                <el-tag v-for="issue in row.issues" :key="`section:${row.row_number}:${issue.code}`" :type="issueType(issue.severity)">{{ issue.message }}</el-tag>
                <span v-if="!row.issues.length">--</span>
              </div>
            </template>
          </NcDataTable>
        </template>
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

    <el-dialog v-model="sectionGenerationDialogVisible" title="根据站点生成区间" width="min(1380px, 96vw)" append-to-body destroy-on-close>
      <div v-if="store.sectionGenerationPreview" class="preview-dialog">
        <el-alert
          v-if="locked"
          title="请先解锁基础资料"
          description="锁定状态可以查看生成预览，但不能应用到当前草稿。"
          type="warning"
          :closable="false"
          show-icon
        />
        <el-alert
          v-if="store.sectionGenerationPreview.blocking_count"
          title="生成预览存在阻断问题"
          description="重复站序、节点身份缺失或区间冲突必须先处理。"
          type="error"
          :closable="false"
          show-icon
        />
        <div class="preview-summary section-generation-summary">
          <article class="normal"><span>新增</span><strong>{{ store.sectionGenerationPreview.create_count }}</strong></article>
          <article><span>更新</span><strong>{{ store.sectionGenerationPreview.update_count }}</strong></article>
          <article><span>不变</span><strong>{{ store.sectionGenerationPreview.unchanged_count }}</strong></article>
          <article class="danger"><span>冲突</span><strong>{{ store.sectionGenerationPreview.conflict_count }}</strong></article>
          <article class="warning"><span>已过期</span><strong>{{ store.sectionGenerationPreview.stale_count }}</strong></article>
        </div>
        <div v-if="store.sectionGenerationPreview.issues.length" class="row-issues">
          <el-tag v-for="issue in store.sectionGenerationPreview.issues" :key="`generation:${issue.code}:${issue.entity_id}:${issue.message}`" :type="issueType(issue.severity)">{{ issue.message }}</el-tag>
        </div>
        <NcDataTable
          v-loading="store.sectionGenerationLoading"
          table-id="rail-base-section-generation-preview"
          route-key="/rail-transit/base-data"
          :data="sectionGenerationRows"
          :columns="sectionGenerationColumns"
          height="460px"
          empty-text="当前站点草稿没有可生成区间"
        >
          <template #cell-selected="{ row }">
            <el-checkbox
              :model-value="isSectionGenerationSelected(row)"
              :disabled="!row.selectable || row.result === 'CONFLICT'"
              @change="(checked: boolean) => toggleSectionGenerationRow(row, checked)"
            />
          </template>
          <template #cell-result="{ row }"><el-tag :type="row.result === 'CONFLICT' ? 'danger' : row.result === 'STALE' ? 'warning' : row.result === 'CREATE' || row.result === 'UPDATE' ? 'success' : 'info'">{{ row.result }}</el-tag></template>
          <template #cell-issues="{ row }">
            <div class="row-issues">
              <el-tag v-for="issue in row.issues" :key="`${row.item_id}:${issue.code}`" :type="issueType(issue.severity)">{{ issue.message }}</el-tag>
              <span v-if="!row.issues.length">--</span>
            </div>
          </template>
        </NcDataTable>
      </div>
      <template #footer>
        <el-button @click="sectionGenerationDialogVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="locked || saving || selectedSectionGenerationIds.length === 0 || Boolean(store.sectionGenerationPreview?.blocking_count)"
          @click="applySectionGenerationToDraft"
        >应用到当前草稿</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.rail-base-data { display: flex; width: 100%; height: 100%; max-width: none; min-width: 0; min-height: 0; flex-direction: column; margin: 0; overflow: hidden; }
.page-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 18px 0; }
.toolbar-actions, .edit-toolbar, .connection-editor { display: flex; align-items: center; gap: 10px; }
.toolbar-actions { flex-wrap: wrap; justify-content: flex-end; }
.edit-toolbar { flex-wrap: wrap; justify-content: flex-end; margin: 8px 0 12px; }
.selection-count { color: var(--nc-text-secondary); font-size: 12px; white-space: nowrap; }
.connection-editor .el-select { width: 92px; }
.connection-editor .el-input-number { width: 120px; }
.page-toolbar h2 { margin: 0; color: var(--nc-text-primary); }
.page-toolbar p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.page-error { margin-bottom: 14px; }
.refresh-error-details { margin-top: 8px; }
.refresh-error-details summary { cursor: pointer; }
.refresh-error-details ul { display: grid; gap: 6px; margin: 8px 0 0; padding-left: 18px; }
.refresh-error-details li { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.refresh-error-details small { width: 100%; overflow-wrap: anywhere; color: var(--nc-text-secondary); }
.validation-list { margin: 6px 0 0; padding-left: 20px; }
.conflict-summary ul { margin: 6px 0 10px; padding-left: 20px; }
.content-card { display: flex; min-width: 0; min-height: 0; flex: 1; padding: 0 18px 18px; overflow: hidden; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 10px; }
.content-card > :deep(.el-tabs) { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; }
.content-card > :deep(.el-tabs > .el-tabs__header) { flex: none; }
.content-card > :deep(.el-tabs > .el-tabs__content) { min-width: 0; min-height: 0; flex: 1; overflow: hidden; }
.content-card > :deep(.el-tabs > .el-tabs__content > .el-tab-pane) { width: 100%; height: 100%; overflow: auto; }
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
 .clear-summary { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
 .clear-note { margin: 0; color: var(--nc-text-secondary); line-height: 1.7; }
.template-summary { grid-template-columns: repeat(5, minmax(120px, 1fr)); }
.preview-filter { margin-bottom: 12px; }
.preview-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.apply-controls { display: flex; align-items: center; gap: 12px; }
.operation-table, .change-table { margin-top: 16px; }
.issue-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.row-issues { display: flex; flex-wrap: wrap; gap: 5px; }
.preview-dialog { display: grid; gap: 12px; }
.source-meta { display: flex; flex-wrap: wrap; gap: 8px; }
.source-strategy { display: grid; gap: 6px; min-width: 160px; }
.preflight-list, .conflict-groups { display: grid; gap: 10px; max-height: 58vh; margin-top: 12px; overflow: auto; }
.preflight-list article, .conflict-groups article { padding: 12px; border: 1px solid var(--nc-border); border-radius: 8px; background: var(--nc-bg-muted); }
.preflight-list header, .conflict-groups header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.preflight-list p, .conflict-groups p { margin: 7px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.preflight-blocked { border-color: var(--nc-danger) !important; }
.preflight-requires_merge { border-color: var(--nc-warning) !important; }
.station-resolution-form { margin-top: 14px; }
.station-resolution-form :deep(.el-select) { width: min(520px, 100%); }
.resolution-members, .resolution-target { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; color: var(--nc-text-secondary); }
.overwrite-diffs { display: grid; gap: 7px; max-height: 52vh; overflow: auto; }
.overwrite-diffs article { display: grid; grid-template-columns: 150px 180px minmax(120px, 1fr) 30px minmax(120px, 1fr); gap: 8px; align-items: center; padding: 8px; border-bottom: 1px solid var(--nc-divider); }
.conflict-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.inline-file-button { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; color: var(--nc-text-primary); background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 6px; cursor: pointer; }
.inline-file-button input { display: none; }
.compact-pair { display: grid; grid-template-columns: minmax(58px, 0.7fr) minmax(115px, 1.3fr); gap: 8px; align-items: center; min-width: 190px; }
.section-mileage-editor { display: grid; grid-template-columns: minmax(78px, 1fr) auto minmax(78px, 1fr) auto; gap: 6px; align-items: center; min-width: 310px; }
.section-mileage-editor :deep(.el-input-number) { width: 100%; }
.inline-checks { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.facility-tags { display: flex; flex-wrap: wrap; gap: 4px; min-width: 160px; }
.terminal-extension-editor { display: grid; grid-template-columns: auto minmax(100px, 1fr) 130px minmax(110px, 1fr); gap: 6px; align-items: center; min-width: 420px; }
.terminal-extension-editor .el-input-number { width: 130px; }
.section-generation-summary { grid-template-columns: repeat(5, minmax(120px, 1fr)); }
.field-error :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--nc-danger) inset; }
@media (max-width: 1360px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .source-summary, .template-summary, .section-generation-summary { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
  .filter-bar { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 900px) {
  .rail-base-data { height: auto; min-height: 100%; overflow: visible; }
  .content-card { min-height: 55dvh; flex: none; overflow: visible; }
  .content-card > :deep(.el-tabs > .el-tabs__content) { overflow: visible; }
  .content-card > :deep(.el-tabs > .el-tabs__content > .el-tab-pane) { height: auto; overflow: visible; }
  .page-toolbar { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { justify-content: flex-start; }
  .summary-grid, .source-summary, .template-summary, .section-generation-summary { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .filter-bar { grid-template-columns: 1fr; }
}
</style>
