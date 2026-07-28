<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { Download, UploadFilled } from '@element-plus/icons-vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  exportTracksideApPlan,
  getTracksideApPlan,
  getTracksideApTask,
  previewTracksideApPlan,
  previewTracksideApVlanAutoGroup,
  previewTracksideApVlanChange,
  recoverTracksideApTasks,
  tracksideApPlanDownloadRequest,
} from '../../../api/tracksideApBusiness'
import { isFeatureEnabled } from '../../../features'
import { downloadBackendResource } from '../../../platform/runtime'
import type {
  ApManagementVlanAllocation,
  ApManagementVlanGroup,
  ApManagementVlanImpact,
  ApManagementVlanPlanningMode,
  ApManagementVlanStationDetail,
  TracksideApPlan,
  TracksideApPlanDraft,
  TracksideApPlanPreview,
  TracksideApPlanPreviewRow,
  TracksideApTask,
} from '../../../types/tracksideApBusiness'
import { useConfirm } from '../../feedback/useConfirm'
import NcDataTable from '../../table/NcDataTable.vue'
import type { NcTableColumn } from '../../table/NcTableColumn'
import {
  mergeAdjacentVlanGroups,
  splitVlanGroup,
  updateVlanGroupMembers,
} from './tracksideApVlanDraft'

interface StationOption { id: string; name: string; sort_order: number | null; ap_count?: number }
const props = withDefaults(defineProps<{ locked: boolean; saving: boolean; stations?: StationOption[] }>(), { stations: () => [] })
const emit = defineEmits<{ change: [draft: TracksideApPlanDraft, dirty: boolean] }>()
const storageKey = 'netconsole.trackside-ap-plan.last-task'
const router = useRouter()
const { confirm } = useConfirm()
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const plan = ref<TracksideApPlan | null>(null)
const selectedGroups = ref<ApManagementVlanGroup[]>([])
const loading = ref(false)
const error = ref('')
const dirty = ref(false)
const task = ref<TracksideApTask | null>(null)
const importInput = ref<HTMLInputElement | null>(null)
const duplicateStrategy = ref<'replace' | 'skip' | 'error'>('replace')
const importPreview = ref<TracksideApPlanPreview | null>(null)
const importPreviewVisible = ref(false)
const impactPreview = ref<ApManagementVlanImpact | null>(null)
const impactVisible = ref(false)
const activeView = ref<'groups' | 'stations'>('groups')
const memberEditorVisible = ref(false)
const allocationVisible = ref(false)
const editingGroupId = ref('')
const editingMemberIds = ref<string[]>([])
const editingSectionName = ref('')
const groupVlanEditBaseline = ref<TracksideApPlanDraft | null>(null)
let pollTimer: number | undefined
type ExportKind = 'template' | 'current'
interface PendingDownload { taskId: string; kind: ExportKind }
const pendingDownload = ref<PendingDownload | null>(null)
const downloadingArtifact = ref(false)
const taskKinds = new Map<string, ExportKind>()
const autoDownloadedTaskIds = new Set<string>()

const groupColumns: NcTableColumn<ApManagementVlanGroup>[] = [
  { key: 'selection', label: '', type: 'selection', valueType: 'selection', width: 46, fixed: 'left', hideable: false },
  { key: 'sequence', label: '组序号', valueType: 'number', width: 82, fixed: 'left' },
  { key: 'group_name', label: 'VLAN 组名称', valueType: 'name', width: 170 },
  { key: 'start_station_name', label: '起始站', valueType: 'name', width: 140 },
  { key: 'end_station_name', label: '结束站', valueType: 'name', width: 140 },
  { key: 'station_count', label: '站点数', valueType: 'number', width: 88 },
  { key: 'ap_count', label: 'AP 总数', valueType: 'number', width: 95 },
  { key: 'management_vlan', label: '管理 VLAN', valueType: 'number', width: 110 },
  { key: 'validation_status', label: '校验', valueType: 'status', width: 90 },
  { key: 'notes', label: '备注', valueType: 'description', width: 180, align: 'left', alignmentReason: 'long-text' },
]
const stationColumns: NcTableColumn<ApManagementVlanStationDetail>[] = [
  { key: 'station_name', label: '站点', valueType: 'name', fixed: 'left', width: 150 },
  { key: 'ap_count', label: 'AP 数', valueType: 'number', width: 85 },
  { key: 'group_name', label: 'VLAN 组', valueType: 'name', width: 170 },
  { key: 'management_vlan', label: '管理 VLAN（继承）', valueType: 'number', width: 150 },
  { key: 'source', label: '来源', valueType: 'status', width: 135 },
  { key: 'notes', label: '备注', valueType: 'description', width: 190, align: 'left', alignmentReason: 'long-text' },
]
const previewColumns: NcTableColumn<TracksideApPlanPreviewRow>[] = [
  { key: 'row_number', label: '行', valueType: 'number' },
  { key: 'status', label: '状态', valueType: 'status' },
  { key: 'key', label: 'VLAN 组/站点', valueType: 'name' },
  { key: 'message', label: '说明', valueType: 'description', align: 'left', alignmentReason: 'long-text' },
]
const allocationColumns: NcTableColumn<ApManagementVlanAllocation>[] = [
  { key: 'station_name', label: '站点', valueType: 'name', width: 140 },
  { key: 'section_name', label: '区间', valueType: 'name', width: 170 },
  { key: 'ap_name', label: 'AP 名称', valueType: 'name', width: 180 },
  { key: 'point_code', label: '点位编号', valueType: 'name', width: 140 },
  { key: 'planned_ip', label: '既有 AP IP（参考）', valueType: 'ip', width: 165 },
  { key: 'group_source', label: '有效组来源', valueType: 'status', width: 145 },
  { key: 'ap_override_group', label: 'AP 级覆盖', valueType: 'actions', width: 190 },
]

const canPreviewImport = computed(() => !props.saving)
const canApplyImport = computed(() => !props.locked && !props.saving)
const canWrite = canApplyImport
const taskRunning = computed(() => Boolean(task.value && !terminalStates.has(task.value.status)))
const draft = computed<TracksideApPlanDraft | null>(() => plan.value && ({
  planning: plan.value.planning,
  groups: plan.value.groups,
  assignments: plan.value.assignments,
  allocations: plan.value.allocations,
}))
const modeLabels: Record<ApManagementVlanPlanningMode, string> = {
  line_single: '全线统一 VLAN',
  station_independent: '每站独立 VLAN',
  station_grouped: '按站点分组 VLAN',
}
const sourceLabels: Record<string, string> = {
  vlan_group_inherited: 'VLAN 组继承',
  station_inherited: 'VLAN 组继承',
  ap_override: 'AP 单独指定',
  section_default: '区间默认组',
  interval_start_default: '区间起点默认组',
  legacy: '站点历史配置',
  legacy_station: '站点历史配置',
  unassigned: '未配置',
  existing_ap: '既有 AP 信息',
  reference_only: '仅 VLAN 归属',
}
const editingGroup = computed(() => plan.value?.groups.find(
  (group) => group.group_id === editingGroupId.value,
) || null)
const editingAllocations = computed(() => plan.value?.allocations.filter(
  (row) => row.group_id === editingGroupId.value,
) || [])
const sectionNames = computed(() => [...new Set(
  plan.value?.allocations.map((row) => row.section_name).filter(Boolean) || [],
)].sort((left, right) => left.localeCompare(right, 'zh-CN')))
const orderedStations = computed(() => [...props.stations].sort(
  (left, right) => (left.sort_order ?? Number.MAX_SAFE_INTEGER)
    - (right.sort_order ?? Number.MAX_SAFE_INTEGER)
    || left.name.localeCompare(right.name, 'zh-CN'),
))

function failure(reason: unknown, fallback: string): string { return reason instanceof Error ? reason.message : fallback }
function deepCopy<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
function sourceLabel(value: string): string { return sourceLabels[value] || '未配置' }
function stopPolling(): void { if (pollTimer !== undefined) window.clearTimeout(pollTimer); pollTimer = undefined }
function rememberTask(value: TracksideApTask | null): void {
  task.value = value
  if (value) localStorage.setItem(storageKey, value.task_id)
  else localStorage.removeItem(storageKey)
}
function refreshLocalStatistics(): void {
  if (!plan.value) return
  for (const [index, group] of plan.value.groups.entries()) {
    group.sequence = index
    group.station_count = group.members.length
    group.start_station_name = group.members[0]?.station_name || ''
    group.end_station_name = group.members.at(-1)?.station_name || ''
    group.ap_count = group.members.reduce((total, member) => total + member.ap_count, 0)
  }
}
function publishDirty(): void {
  if (!draft.value) return
  refreshLocalStatistics()
  dirty.value = true
  emit('change', deepCopy(draft.value), true)
}

async function loadPlan(force = false): Promise<boolean> {
  if (dirty.value && !force) {
    const accepted = await confirm({ type: 'WARNING', title: '未保存修改', message: '刷新会丢弃尚未保存的轨旁 AP 管理 VLAN 分组，是否继续？', confirmText: '放弃修改并刷新' })
    if (!accepted) return false
  }
  loading.value = true
  error.value = ''
  try {
    plan.value = await getTracksideApPlan()
    dirty.value = false
    selectedGroups.value = []
    if (draft.value) emit('change', deepCopy(draft.value), false)
    return true
  } catch (reason) {
    error.value = failure(reason, '轨旁 AP 管理 VLAN 规划加载失败')
    return false
  } finally { loading.value = false }
}

async function applyServerPreview(
  proposed: TracksideApPlanDraft,
  title: string,
): Promise<boolean> {
  loading.value = true
  error.value = ''
  try {
    const preview = await previewTracksideApVlanChange(proposed)
    impactPreview.value = preview.impact
    impactVisible.value = true
    const accepted = await confirm({
      type: preview.impact.conflict_count ? 'DANGER' : 'WARNING',
      title,
      message: `将影响 ${preview.impact.affected_station_count} 个站点、${preview.impact.affected_ap_count} 个 AP，管理 VLAN 变化 ${preview.impact.vlan_change_count} 个。`,
      confirmText: '应用预览结果',
    })
    if (accepted) {
      plan.value = preview.plan
      selectedGroups.value = []
      publishDirty()
      return true
    }
    return false
  } catch (reason) {
    error.value = failure(reason, 'VLAN 分组调整预览失败')
    return false
  }
  finally { loading.value = false }
}

function beginGroupVlanEdit(): void {
  if (!groupVlanEditBaseline.value && draft.value) {
    groupVlanEditBaseline.value = deepCopy(draft.value)
  }
}

async function commitGroupVlanEdit(): Promise<void> {
  if (!plan.value || !draft.value || !groupVlanEditBaseline.value) return
  const proposed = deepCopy(draft.value)
  const baseline = groupVlanEditBaseline.value
  groupVlanEditBaseline.value = null
  plan.value = {
    ...plan.value,
    planning: baseline.planning,
    groups: baseline.groups,
    assignments: baseline.assignments,
    allocations: baseline.allocations,
  }
  await applyServerPreview(proposed, '修改管理 VLAN 影响预览')
}

async function regroup(mode = plan.value?.planning.planning_mode): Promise<void> {
  if (!canWrite.value || !plan.value || !draft.value || !mode) return
  loading.value = true
  error.value = ''
  try {
    const preview = await previewTracksideApVlanAutoGroup({
      planning_mode: mode,
      auto_group_station_count: plan.value.planning.auto_group_station_count,
      current: deepCopy(draft.value),
    })
    impactPreview.value = preview.impact
    impactVisible.value = true
    const accepted = await confirm({
      type: preview.impact.conflict_count ? 'DANGER' : 'WARNING',
      title: '规划方式影响预览',
      message: `${modeLabels[mode]}将生成 ${preview.plan.groups.length} 个 VLAN 组，影响 ${preview.impact.affected_station_count} 个站点和 ${preview.impact.affected_ap_count} 个 AP；不会生成、校验或修改 AP IP。`,
      confirmText: '确认应用',
    })
    if (accepted) {
      plan.value = preview.plan
      publishDirty()
    }
  } catch (reason) { error.value = failure(reason, '自动分组预览失败') }
  finally { loading.value = false }
}

async function splitGroup(): Promise<void> {
  if (!draft.value || selectedGroups.value.length !== 1) return
  const source = selectedGroups.value[0]
  if (source.members.length < 2) {
    ElMessage.warning('至少包含两个站点的组才能拆分')
    return
  }
  const proposed = splitVlanGroup(
    draft.value,
    source.group_id,
    Math.ceil(source.members.length / 2),
    `group-${Date.now()}`,
  )
  await applyServerPreview(proposed, '拆分 VLAN 组影响预览')
}

async function mergeGroups(): Promise<void> {
  if (!draft.value || selectedGroups.value.length !== 2) return
  const ordered = [...selectedGroups.value].sort((left, right) => left.sequence - right.sequence)
  if (ordered[1].sequence !== ordered[0].sequence + 1) {
    ElMessage.warning('只能合并相邻 VLAN 组')
    return
  }
  let proposed: TracksideApPlanDraft
  try {
    proposed = mergeAdjacentVlanGroups(
      draft.value,
      ordered[0].group_id,
      ordered[1].group_id,
    )
  } catch (reason) {
    ElMessage.warning(failure(reason, 'VLAN 组合并失败'))
    return
  }
  await applyServerPreview(proposed, '合并 VLAN 组影响预览')
}

function addEmptyGroup(): void {
  if (!canWrite.value || !plan.value) return
  const sequence = plan.value.groups.length
  const groupId = `group-${Date.now()}-${sequence}`
  plan.value.groups.push({
    group_id: groupId,
    line_id: plan.value.planning.line_id,
    group_code: `G${String(sequence + 1).padStart(3, '0')}`,
    group_name: `VLAN 组 ${sequence + 1}`,
    sequence,
    management_vlan: null,
    legacy_management_vlans: '',
    network_address: '',
    prefix_length: null,
    subnet_mask: '',
    default_gateway: '',
    ap_start_ip: '',
    ap_end_ip: '',
    address_allocation_strategy: plan.value.planning.address_allocation_strategy,
    notes: '',
    created_at: '',
    updated_at: '',
    members: [],
    start_station_name: '',
    end_station_name: '',
    station_count: 0,
    ap_count: 0,
    address_capacity: 0,
    used_address_count: 0,
    validation_status: 'error',
    issues: [],
  })
  editingGroupId.value = groupId
  editingMemberIds.value = []
  memberEditorVisible.value = true
  publishDirty()
}

function openMemberEditor(): void {
  if (!canWrite.value || selectedGroups.value.length !== 1) return
  editingGroupId.value = selectedGroups.value[0].group_id
  editingMemberIds.value = selectedGroups.value[0].members.map(
    (member) => member.station_id,
  )
  memberEditorVisible.value = true
}

async function applyMemberEditor(): Promise<void> {
  if (!draft.value || !editingGroup.value) return
  const selected = new Set(editingMemberIds.value)
  const proposed = updateVlanGroupMembers(
    draft.value,
    editingGroup.value.group_id,
    orderedStations.value
      .filter((station) => selected.has(station.id))
      .map((station) => ({
        station_id: station.id,
        station_name: station.name,
        station_sequence: station.sort_order ?? 0,
        ap_count: station.ap_count ?? 0,
      })),
  )
  memberEditorVisible.value = false
  await applyServerPreview(proposed, '调整 VLAN 组边界影响预览')
}

async function deleteEmptyGroup(): Promise<void> {
  if (!draft.value || selectedGroups.value.length !== 1) return
  const target = selectedGroups.value[0]
  if (target.members.length) {
    ElMessage.warning('只能删除没有站点成员的空组')
    return
  }
  const proposed = deepCopy(draft.value)
  proposed.groups = proposed.groups
    .filter((group) => group.group_id !== target.group_id)
    .map((group, sequence) => ({ ...group, sequence }))
  await applyServerPreview(proposed, '删除空 VLAN 组影响预览')
}

function showStations(): void {
  activeView.value = 'stations'
}

function showApReferences(): void {
  if (selectedGroups.value.length !== 1) return
  editingGroupId.value = selectedGroups.value[0].group_id
  editingSectionName.value = editingAllocations.value.find(
    (row) => row.section_name,
  )?.section_name || sectionNames.value[0] || ''
  allocationVisible.value = true
}

function assignmentGroupId(
  targetId: string,
  assignmentType: 'section_default' | 'ap_override',
): string {
  return plan.value?.assignments.find(
    (row) => row.target_id === targetId && row.assignment_type === assignmentType,
  )?.group_id || ''
}

function assignmentDraft(
  targetId: string,
  assignmentType: 'section_default' | 'ap_override',
  groupId?: string,
): TracksideApPlanDraft | null {
  if (!draft.value) return null
  const proposed = deepCopy(draft.value)
  proposed.assignments = proposed.assignments.filter((row) => (
    assignmentType === 'ap_override'
      ? row.target_id !== targetId
      : !(row.target_id === targetId && row.assignment_type === assignmentType)
  ))
  if (groupId) {
    proposed.assignments.push({
      assignment_id: `assignment:${assignmentType}:${targetId}`,
      assignment_type: assignmentType,
      target_id: targetId,
      group_id: groupId,
      source: assignmentType,
      updated_at: '',
    })
  }
  return proposed
}

async function applySectionGroup(groupId?: string): Promise<void> {
  if (!editingSectionName.value) return
  const proposed = assignmentDraft(
    `section:${editingSectionName.value}`,
    'section_default',
    groupId,
  )
  if (proposed) await applyServerPreview(proposed, '调整区间默认 VLAN 组影响预览')
}

async function applyApGroup(
  row: ApManagementVlanAllocation,
  groupId?: string,
): Promise<void> {
  const proposed = assignmentDraft(row.ap_id, 'ap_override', groupId)
  if (proposed) await applyServerPreview(proposed, '调整 AP 级 VLAN 组覆盖影响预览')
}

function poll(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      const latest = await getTracksideApTask(task.value!.task_id)
      error.value = ''
      await handleTaskUpdate(latest)
      poll()
    } catch (reason) { error.value = failure(reason, '轨旁 AP 规划任务状态读取失败') }
  }, 1000)
}
async function exportPlan(template: boolean): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const created = await exportTracksideApPlan(template, !template && dirty.value && draft.value ? deepCopy(draft.value) : undefined)
    const kind: ExportKind = template ? 'template' : 'current'
    taskKinds.set(created.task_id, kind)
    pendingDownload.value = { taskId: created.task_id, kind }
    await handleTaskUpdate(created)
    poll()
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
  try { importPreview.value = await previewTracksideApPlan(file, duplicateStrategy.value); importPreviewVisible.value = true }
  catch (reason) { error.value = failure(reason, '轨旁 AP 规划导入预览失败') }
  finally { loading.value = false }
}
function applyImportPreview(): void {
  if (!importPreview.value?.can_apply || !importPreview.value.result_plan || !canApplyImport.value) return
  plan.value = importPreview.value.result_plan
  importPreviewVisible.value = false
  publishDirty()
  ElMessage.success('导入预览已应用到 VLAN 分组编辑区，请使用页面右上角“保存”提交')
}
function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}
async function downloadArtifact(): Promise<void> { if (task.value) await downloadCompletedTask(task.value, false) }
async function downloadCompletedTask(current: TracksideApTask, automatic: boolean): Promise<void> {
  if (current.status !== 'COMPLETED') return
  if (automatic && autoDownloadedTaskIds.has(current.task_id)) return
  if (!current.available || !current.artifact_id) {
    if (automatic) error.value = '轨旁 AP 规划任务已完成，但没有可下载的 Artifact'
    else ElMessage.error('轨旁 AP 规划文件暂不可下载')
    return
  }
  if (automatic) autoDownloadedTaskIds.add(current.task_id)
  const kind = taskKinds.get(current.task_id) || 'current'
  const suggestedName = current.artifact_name || (kind === 'template' ? '轨旁AP规划模板.xlsx' : '轨旁AP规划.xlsx')
  downloadingArtifact.value = true
  try {
    const result = await downloadBackendResource(tracksideApPlanDownloadRequest(current.artifact_id, suggestedName))
    if (result.status === 'saved') ElMessage.success(`已保存 ${suggestedName}`)
    else if (result.status === 'started') ElMessage.success(`浏览器已开始下载 ${suggestedName}`)
    else if (result.status === 'cancelled') {
      ElMessage.info('下载已取消')
      if (automatic) error.value = '自动下载已取消，可使用“下载文件”重试'
    } else if (result.status === 'failed') {
      const message = result.error || '轨旁 AP 规划文件下载失败'
      ElMessage.error(message)
      if (automatic) error.value = `${message}，可使用“下载文件”重试`
    }
  } catch (reason) {
    const message = failure(reason, '轨旁 AP 规划文件下载失败')
    ElMessage.error(message)
    if (automatic) error.value = `${message}，可使用“下载文件”重试`
  } finally { downloadingArtifact.value = false }
}
async function handleTaskUpdate(value: TracksideApTask): Promise<void> {
  rememberTask(value)
  const pending = pendingDownload.value
  if (!pending || pending.taskId !== value.task_id || !terminalStates.has(value.status)) return
  pendingDownload.value = null
  if (value.status === 'COMPLETED') await downloadCompletedTask(value, true)
  else if (value.status === 'FAILED') error.value = value.error_message || '轨旁 AP 规划导出失败'
  else if (value.status === 'CANCELLED') error.value = '轨旁 AP 规划导出已取消'
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

watch(() => props.stations, (stations) => {
  if (!plan.value || !stations.length) return
  const byId = new Map(stations.map((station) => [station.id, station]))
  const byName = new Map(stations.map((station) => [station.name.toLocaleLowerCase(), station]))
  let changed = false
  for (const group of plan.value.groups) {
    group.members = group.members.filter((member) => {
      const station = byId.get(member.station_id) || byName.get(member.station_name.toLocaleLowerCase())
      if (!station) { changed = true; return false }
      if (member.station_name !== station.name || member.station_sequence !== (station.sort_order ?? 0)) changed = true
      member.station_id = station.id
      member.station_name = station.name
      member.station_sequence = station.sort_order ?? 0
      member.ap_count = station.ap_count ?? member.ap_count
      return true
    })
  }
  if (changed && canWrite.value) publishDirty()
}, { deep: true })

defineExpose({ reload: loadPlan })
onMounted(() => { void Promise.all([loadPlan(true), recoverTasks()]) })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="planning-tab">
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false"><el-button link @click="recoverTasks">恢复任务状态</el-button></el-alert>
    <div class="planning-mode">
      <span class="label">AP 管理 VLAN 规划方式</span>
      <el-select :model-value="plan?.planning.planning_mode" :disabled="!canWrite || loading" style="width:190px" @change="(value: ApManagementVlanPlanningMode) => regroup(value)">
        <el-option label="全线统一 VLAN" value="line_single" />
        <el-option label="每站独立 VLAN" value="station_independent" />
        <el-option label="按站点分组 VLAN" value="station_grouped" />
      </el-select>
      <template v-if="plan?.planning.planning_mode === 'station_grouped'">
        <span>自动每组</span>
        <el-select v-model="plan.planning.auto_group_station_count" :disabled="!canWrite" style="width:82px">
          <el-option v-for="count in 4" :key="count" :label="`${count} 站`" :value="count" />
        </el-select>
        <el-button :disabled="!canWrite || taskRunning" @click="regroup()">自动分组预览</el-button>
      </template>
      <el-tag v-if="plan" :type="plan.valid ? 'success' : 'danger'">{{ plan.valid ? '规划有效' : `${plan.issues.filter((item) => item.blocking).length} 个阻断问题` }}</el-tag>
      <el-tag v-if="plan?.unassigned_station_count" type="danger">未分配站点 {{ plan.unassigned_station_count }}</el-tag>
      <span class="revision">revision {{ plan?.planning.revision ?? 0 }}</span>
    </div>
    <div class="toolbar">
      <el-select v-model="duplicateStrategy" aria-label="重复策略" style="width:150px"><el-option label="重复时覆盖" value="replace" /><el-option label="重复时跳过" value="skip" /><el-option label="重复时报错" value="error" /></el-select>
      <input ref="importInput" class="hidden" type="file" accept=".xlsx,.csv" @change="chooseImport">
      <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(true)">下载模板</el-button>
      <el-button :icon="UploadFilled" :disabled="!canPreviewImport || taskRunning" @click="importInput?.click()">导入并预览</el-button>
      <el-button :icon="Download" :disabled="!isFeatureEnabled('web.rail_trackside_ap_plan_export') || taskRunning" @click="exportPlan(false)">导出当前</el-button>
      <el-button :disabled="!canWrite || selectedGroups.length !== 1 || taskRunning" @click="splitGroup">拆分 VLAN 组</el-button>
      <el-button :disabled="!canWrite || selectedGroups.length !== 2 || taskRunning" @click="mergeGroups">合并相邻组</el-button>
      <el-button :disabled="!canWrite || taskRunning" @click="addEmptyGroup">新增空组</el-button>
      <el-button :disabled="!canWrite || selectedGroups.length !== 1 || taskRunning" @click="openMemberEditor">调整成员/边界</el-button>
      <el-button :disabled="!canWrite || selectedGroups.length !== 1 || selectedGroups[0]?.members.length !== 0 || taskRunning" @click="deleteEmptyGroup">删除空组</el-button>
      <el-button :disabled="!plan" @click="showStations">查看站点</el-button>
      <el-button :disabled="selectedGroups.length !== 1" @click="showApReferences">查看 AP/参考信息</el-button>
      <span class="dirty">{{ dirty ? '有未保存修改' : `已加载 ${plan?.groups.length ?? 0} 个 VLAN 组` }}</span>
    </div>
    <el-tabs v-model="activeView">
      <el-tab-pane label="VLAN 组视图" name="groups">
        <div class="table-scroll">
          <NcDataTable v-loading="loading" table-id="rail-base-trackside-ap-vlan-groups" route-key="/rail-transit/base-data" :data="plan?.groups || []" :columns="groupColumns" border height="calc(100vh - 465px)" empty-text="暂无 VLAN 分组；解锁后选择规划方式生成" @selection-change="(value: ApManagementVlanGroup[]) => selectedGroups = value">
            <template #cell-sequence="{ row }">{{ row.sequence + 1 }}</template>
            <template #cell-group_name="{ row }"><el-input v-if="canWrite" v-model="row.group_name" @input="publishDirty" /><span v-else>{{ row.group_name }}</span></template>
            <template #cell-management_vlan="{ row }"><el-input-number v-if="canWrite" v-model="row.management_vlan" :min="1" :max="4094" controls-position="right" @focus="beginGroupVlanEdit" @change="commitGroupVlanEdit" /><span v-else>{{ row.management_vlan ?? '--' }}</span></template>
            <template #cell-notes="{ row }"><el-input v-if="canWrite" v-model="row.notes" @input="publishDirty" /><span v-else>{{ row.notes || '--' }}</span></template>
          </NcDataTable>
        </div>
      </el-tab-pane>
      <el-tab-pane label="按站点查看（继承值）" name="stations">
        <div class="table-scroll">
          <NcDataTable table-id="rail-base-trackside-ap-vlan-stations" route-key="/rail-transit/base-data" :data="plan?.station_details || []" :columns="stationColumns" border height="calc(100vh - 465px)" empty-text="暂无站点 VLAN 归属">
            <template #cell-source="{ row }">{{ sourceLabel(row.source) }}</template>
          </NcDataTable>
        </div>
      </el-tab-pane>
    </el-tabs>
    <el-alert v-if="plan?.issues.length" :title="plan.issues.map((item) => item.message).join('；')" :type="plan.valid ? 'warning' : 'error'" :closable="false" />
    <el-alert v-if="task" :title="`${task.status} · ${task.message || task.task_id}`" :type="task.error_message ? 'error' : 'info'" :closable="false"><el-button v-if="task.available && task.artifact_id" link type="primary" :loading="downloadingArtifact" @click="downloadArtifact">下载文件</el-button><el-button link @click="openTaskWindow">打开任务中心</el-button></el-alert>
    <el-dialog v-model="importPreviewVisible" title="导入预览" width="960px" destroy-on-close>
      <div v-if="importPreview" class="preview">
        <el-descriptions :column="5" border><el-descriptions-item label="总行数">{{ importPreview.total_count }}</el-descriptions-item><el-descriptions-item label="有效">{{ importPreview.valid_count }}</el-descriptions-item><el-descriptions-item label="重复">{{ importPreview.duplicate_count }}</el-descriptions-item><el-descriptions-item label="错误">{{ importPreview.error_count }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ importPreview.file_sha256.slice(0, 12) }}…</el-descriptions-item></el-descriptions>
        <NcDataTable table-id="rail-base-trackside-ap-plan-import-preview" route-key="/rail-transit/base-data" :data="importPreview.rows" :columns="previewColumns" border height="360" :show-column-settings="false" />
        <el-alert v-if="!importPreview.can_apply" title="预览存在阻断错误，请修正文件或更换重复策略后重新导入" type="error" :closable="false" />
      </div>
      <template #footer><el-button @click="importPreviewVisible = false">取消</el-button><el-button type="primary" :disabled="!importPreview?.can_apply || !canApplyImport" @click="applyImportPreview">应用到编辑区</el-button></template>
    </el-dialog>
    <el-dialog v-model="impactVisible" title="规划影响预览" width="760px">
      <el-descriptions v-if="impactPreview" :column="3" border>
        <el-descriptions-item label="原 VLAN 组">{{ impactPreview.old_group_count }}</el-descriptions-item>
        <el-descriptions-item label="新 VLAN 组">{{ impactPreview.new_group_count }}</el-descriptions-item>
        <el-descriptions-item label="受影响站点">{{ impactPreview.affected_station_count }}</el-descriptions-item>
        <el-descriptions-item label="受影响 AP">{{ impactPreview.affected_ap_count }}</el-descriptions-item>
        <el-descriptions-item label="VLAN 变化">{{ impactPreview.vlan_change_count }}</el-descriptions-item>
        <el-descriptions-item label="冲突/提示">{{ impactPreview.conflict_count }} / {{ impactPreview.warning_count }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
    <el-dialog v-model="memberEditorVisible" :title="`调整 ${editingGroup?.group_name || 'VLAN 组'} 成员/边界`" width="680px">
      <el-alert title="站点按正式顺序保存；从其他组选择站点会将其移动到当前组，Backend 预览会阻断遗漏、重复和不连续范围。" type="info" :closable="false" />
      <el-select v-model="editingMemberIds" multiple filterable style="width:100%" placeholder="选择连续站点">
        <el-option v-for="station in orderedStations" :key="station.id" :label="station.name" :value="station.id" />
      </el-select>
      <template #footer><el-button @click="memberEditorVisible = false">取消</el-button><el-button type="primary" :disabled="!canWrite" @click="applyMemberEditor">生成影响预览</el-button></template>
    </el-dialog>
    <el-dialog v-model="allocationVisible" :title="`${editingGroup?.group_name || 'VLAN 组'} · AP 与 IP 参考信息`" width="980px">
      <el-alert title="IP 仅为既有资料的只读参考；本规划不生成、不校验、不修改 AP IP。有效 VLAN 组来源依次为 AP 级覆盖、明确归属站点、区间默认组和区间起点默认。" type="info" :closable="false" />
      <el-descriptions v-if="editingGroup" :column="3" border>
        <el-descriptions-item label="网络地址（参考）">{{ editingGroup.network_address || '--' }}</el-descriptions-item>
        <el-descriptions-item label="掩码/前缀（参考）">{{ editingGroup.subnet_mask || (editingGroup.prefix_length == null ? '--' : `/${editingGroup.prefix_length}`) }}</el-descriptions-item>
        <el-descriptions-item label="网关（参考）">{{ editingGroup.default_gateway || '--' }}</el-descriptions-item>
        <el-descriptions-item label="AP 起始地址（参考）">{{ editingGroup.ap_start_ip || '--' }}</el-descriptions-item>
        <el-descriptions-item label="AP 结束地址（参考）">{{ editingGroup.ap_end_ip || '--' }}</el-descriptions-item>
      </el-descriptions>
      <div v-if="sectionNames.length" class="assignment-toolbar">
        <span>区间默认组</span>
        <el-select v-model="editingSectionName" filterable style="width:220px">
          <el-option v-for="sectionName in sectionNames" :key="sectionName" :label="sectionName" :value="sectionName" />
        </el-select>
        <el-select
          :model-value="assignmentGroupId(`section:${editingSectionName}`, 'section_default')"
          clearable
          placeholder="按区间起点继承（默认）"
          style="width:240px"
          :disabled="!canWrite"
          @change="(groupId?: string) => applySectionGroup(groupId)"
        >
          <el-option v-for="group in plan?.groups || []" :key="group.group_id" :label="group.group_name" :value="group.group_id" />
        </el-select>
      </div>
      <div class="table-scroll">
        <NcDataTable table-id="rail-base-trackside-ap-vlan-allocations" route-key="/rail-transit/base-data" :data="editingAllocations" :columns="allocationColumns" border height="420" empty-text="当前 VLAN 组暂无 AP 参考信息">
          <template #cell-planned_ip="{ row }">{{ row.planned_ip || '--' }}</template>
          <template #cell-group_source="{ row }">{{ sourceLabel(row.group_source) }}</template>
          <template #cell-ap_override_group="{ row }">
            <el-select
              :model-value="assignmentGroupId(row.ap_id, 'ap_override')"
              clearable
              placeholder="继承"
              :disabled="!canWrite"
              @change="(groupId?: string) => applyApGroup(row, groupId)"
            >
              <el-option v-for="group in plan?.groups || []" :key="group.group_id" :label="group.group_name" :value="group.group_id" />
            </el-select>
          </template>
        </NcDataTable>
      </div>
    </el-dialog>
  </section>
</template>

<style scoped>
.planning-tab,.preview{display:flex;flex-direction:column;gap:12px;min-width:0}.planning-mode,.toolbar,.assignment-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.planning-mode .label{font-weight:600}.revision{color:var(--nc-text-secondary)}.dirty{margin-left:auto;color:var(--nc-text-secondary)}.hidden{display:none}.table-scroll{min-width:0;overflow-x:auto}.table-scroll :deep(.nc-data-table){min-width:1120px}@media(max-width:900px){.dirty{margin-left:0}}
</style>
