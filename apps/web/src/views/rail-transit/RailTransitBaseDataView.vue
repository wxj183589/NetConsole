<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, UploadFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'

import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { useRailTransitBaseDataStore } from '../../stores/railTransitBaseData'
import type {
  DataQualityEntityGroup,
  DataQualityIssue,
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

const store = useRailTransitBaseDataStore()
const router = useRouter()
const { confirm } = useConfirm()
const activeTab = ref('overview')
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
]
const apColumns: NcTableColumn<TracksideAp>[] = [
  { key: 'name', label: 'AP 名称 / 点位', valueType: 'name', minWidth: 170, fixed: 'left', displayValue: (row) => row.name || row.point_code || '--' },
  { key: 'mac', label: 'AP MAC', valueType: 'mac', minWidth: 150 },
  { key: 'management_ip', label: '管理 IP', valueType: 'ip', minWidth: 125, displayValue: (row) => display(row.management_ip) },
  { key: 'station', label: '站点', minWidth: 130, displayValue: (row) => display(row.station) },
  { key: 'section', label: '区间', minWidth: 170, displayValue: (row) => display(row.section) },
  { key: 'mileage', label: '里程', valueType: 'mileage', minWidth: 120, displayValue: (row) => row.mileage.normalized || row.mileage.raw || '--' },
  { key: 'line_side', label: '线路方向', width: 110, displayValue: (row) => display(row.line_side) },
  { key: 'fit_ap_status', label: 'FIT-AP 状态', valueType: 'status', width: 120 },
  { key: 'mesh_related_name', label: '关联 MR', minWidth: 150 },
  { key: 'optical_status', label: '光衰', valueType: 'status', width: 105 },
  { key: 'source_file', label: '数据来源', align: 'left', alignmentReason: 'path', minWidth: 150, showOverflowTooltip: true },
  { key: 'issues', label: '问题', valueType: 'status', width: 90 },
  { key: 'actions', label: '跳转', valueType: 'actions', width: 190, fixed: 'right', hideable: false },
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

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  store.startPolling()
  void store.refreshImportGovernance().catch(() => undefined)
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
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
  if (!applyConfirmed.value) return
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
  router.push({ path: '/ac-management/mesh-links', query: { peer_ap_name: ap.name } })
}
function openMrMesh(mr: VehicleMr): void {
  router.push({ path: '/ac-management/mesh-links', query: { mr_name: mr.name } })
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
      :title="store.canApplyImport() ? '轨道交通基础资料受控维护' : '轨道交通基础资料只读视图'"
      :description="store.canApplyImport() ? '写入仅对当前明确授权的数据范围生效，应用前必须逐项核对差异并确认。' : '本页只查询当前局点资料；导入默认仅做预览校验，写入未授权。'"
      :type="store.canApplyImport() ? 'warning' : 'info'"
      :closable="false"
      show-icon
    />

    <div class="page-toolbar">
      <div>
        <h2>轨道交通基础资料</h2>
        <p>{{ store.summary?.site_name || '当前局点' }} · {{ store.summary?.line_name || '线路未填写' }} · {{ store.summary?.project_type || '项目类型未填写' }}</p>
      </div>
      <el-button :icon="Refresh" :loading="store.loading" @click="store.manualRefresh">刷新只读数据</el-button>
    </div>
    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />

    <div class="content-card">
      <el-tabs v-model="activeTab">
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

        <el-tab-pane label="站点与区间" name="locations">
          <el-tabs v-model="locationTab" type="card">
            <el-tab-pane label="站点" name="stations">
              <NcDataTable table-id="rail-base-stations" route-key="/rail-transit/base-data" :data="store.stations" :columns="stationColumns" height="calc(100vh - 365px)" empty-text="暂无站点资料" />
            </el-tab-pane>
            <el-tab-pane label="区间" name="sections">
              <NcDataTable table-id="rail-base-sections" route-key="/rail-transit/base-data" :data="store.sections" :columns="sectionColumns" height="calc(100vh - 365px)" empty-text="暂无区间资料" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP" name="aps">
          <div class="filter-bar">
            <el-input v-model="store.apFilters.query" clearable placeholder="AP 名称 / 点位 / MAC / IP" @keyup.enter="store.applyApFilters" />
            <el-input v-model="store.apFilters.station" clearable placeholder="归属站点" />
            <el-input v-model="store.apFilters.section" clearable placeholder="归属区间" />
            <el-select v-model="store.apFilters.line_side" clearable placeholder="线路方向"><el-option label="左线" value="左线" /><el-option label="右线" value="右线" /><el-option label="出段线" value="出段线" /><el-option label="入段线" value="入段线" /></el-select>
            <el-select v-model="store.apFilters.has_issue" clearable placeholder="数据质量"><el-option label="只看异常" :value="true" /><el-option label="只看正常" :value="false" /></el-select>
            <el-button type="primary" @click="store.applyApFilters">应用筛选</el-button>
          </div>
          <NcDataTable table-id="rail-base-trackside-aps" route-key="/rail-transit/base-data" :data="store.aps" :columns="apColumns" height="calc(100vh - 430px)" empty-text="暂无轨旁 AP 扩展资料">
            <template #cell-fit_ap_status="{ row }"><el-tag :type="stateType(row.runtime.fit_ap_status)">{{ row.runtime.fit_ap_status }}</el-tag></template>
            <template #cell-mesh_related_name="{ row }">{{ display(row.runtime.mesh_related_name) }}</template>
            <template #cell-optical_status="{ row }"><el-tag :type="stateType(row.runtime.optical_status)">{{ row.runtime.optical_status }}</el-tag></template>
            <template #cell-issues="{ row }"><el-tag v-if="row.issue_count" :type="issueType(row.highest_issue_severity)">{{ row.issue_count }}</el-tag><span v-else>--</span></template>
            <template #cell-actions="{ row }"><el-button link type="primary" @click="openApAc(row)">FIT-AP</el-button><el-button link type="primary" @click="openApMesh(row)">Mesh-Link</el-button></template>
          </NcDataTable>
          <el-pagination background layout="total, prev, pager, next, sizes" :total="store.apTotal" :current-page="store.apFilters.page" :page-size="store.apFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setApPage" @size-change="(size: number) => { store.apFilters.page_size = size; store.applyApFilters() }" />
        </el-tab-pane>

        <el-tab-pane label="列车与车载 MR" name="vehicles">
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
                <el-button type="primary" @click="store.applyMrFilters">应用筛选</el-button>
              </div>
              <NcDataTable table-id="rail-base-vehicle-mrs" route-key="/rail-transit/base-data" :data="store.mrs" :columns="mrColumns" height="calc(100vh - 430px)" empty-text="暂无车载 MR 资料">
                <template #cell-mesh_status="{ row }"><el-tag :type="stateType(row.runtime.mesh_status)">{{ row.runtime.mesh_status }}</el-tag></template>
                <template #cell-actions="{ row }"><el-button link type="primary" @click="openMrMesh(row)">Mesh-Link</el-button><el-button link type="primary" @click="openMrSession(row)">Online MR</el-button></template>
              </NcDataTable>
              <el-pagination background layout="total, prev, pager, next, sizes" :total="store.mrTotal" :current-page="store.mrFilters.page" :page-size="store.mrFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setMrPage" @size-change="(size: number) => { store.mrFilters.page_size = size; store.applyMrFilters() }" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="数据质量问题" name="issues">
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

        <el-tab-pane label="导入预览" name="preview">
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
            <div v-if="store.canApplyImport()" class="apply-controls">
              <el-checkbox v-model="applyConfirmed">我已核对差异、冲突和目标局点</el-checkbox>
              <el-button type="primary" :loading="store.applyLoading" :disabled="!applyConfirmed || previewBlocked" @click="handleApply">应用导入</el-button>
            </div>
            <el-tag v-else type="info">写入未授权，仅可预览</el-tag>
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

        <el-tab-pane label="导入审计" name="operations">
          <el-alert title="审计记录只保存文件摘要、字段差异和操作结果，不保存上传原文件。" type="info" :closable="false" show-icon />
          <NcDataTable table-id="rail-base-import-operations" route-key="/rail-transit/base-data" :data="store.importOperations" :columns="operationColumns" class="operation-table" empty-text="暂无导入操作">
            <template #cell-actions="{ row }">
                <el-button link type="primary" @click="store.selectImportOperation(row.operation_id)">查看变更</el-button>
                <el-button
                  v-if="store.importPolicies?.rollback_enabled && store.canApplyImport() && row.status === 'APPLIED'"
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
.page-toolbar h2 { margin: 0; color: var(--nc-text-primary); }
.page-toolbar p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.page-error { margin-bottom: 14px; }
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
</style>
