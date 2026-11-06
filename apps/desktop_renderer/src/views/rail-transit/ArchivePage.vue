<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listGroundHistory, startGroundHistoryExport } from '../../api/groundUnattended'
import { useUserSelectedExport } from '../../composables/useUserSelectedExport'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import type { GroundHistoryFilters, GroundHistoryRecord } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'
const { Delete, Download, FolderOpened, NcDataTable, t, groundStatusLabel, archives, archiveTableHost, archiveTableMaxHeight, archiveColumns, showArchive, removeArchive, downloadArchiveSummary, downloadArchiveZip, openArchiveDirectory, statusType, activeTab, pageVisible, pageActivated, quickContextRevision, trains, selectedRunId, syslogFilter, syslogTimeRange } = useGroundContext()
const { submitExportAfterDestinationSelected, hasActiveExportAction } = useUserSelectedExport()
const historyTypes = [
  ['run', 'ground.history.run', '运行'], ['train', 'ground.history.train', '列车'],
  ['heartbeat', 'ground.history.heartbeat', '心跳'], ['quick_ping', 'ground.history.quick_ping', '快速 Ping'],
  ['syslog_raw', 'ground.history.syslog_raw', '原始 Syslog 文件'], ['syslog_parsed', 'ground.history.syslog_parsed', '解析 Syslog'],
  ['ac_snapshot', 'ground.history.ac_snapshot', 'AC 快照'], ['deep', 'ground.history.deep', '深度采集'], ['timeline', 'ground.history.timeline', '时间轴'],
]
const typeLabel = (type: string) => { const entry = historyTypes.find((item) => item[0] === type); return entry ? t(entry[1], entry[2]) : type }
const filters = reactive({ sort_order: 'desc' as 'asc' | 'desc', data_type: '', run_id: '', train_id: '', mr_id: '', mr_role: '', event_type: '' })
const timeRange = ref<Date[]>([])
const rows = ref<GroundHistoryRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(100)
const sources = ref<Record<string, string>>({})
const selected = ref<GroundHistoryRecord | null>(null)
const detailOpen = ref(false)
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const active = computed(() => activeTab.value === 'archives' && pageVisible.value && pageActivated.value)
const missingSources = computed(() => Object.entries(sources.value).filter(([, state]) => state !== 'AVAILABLE').map(([type]) => typeLabel(type)).join(', '))
const historyColumns = computed(() => [
  { key: 'ts', label: t('ground.history.time', '时间'), minWidth: 200 },
  { key: 'data_type', label: t('ground.history.type', '类型'), width: 145 },
  { key: 'run_id', label: t('ground.history.run_id', '运行 / 任务 ID'), minWidth: 190 },
  { key: 'train_id', label: t('ground.history.train', '列车'), minWidth: 130 },
  { key: 'mr_id', label: 'MR UUID', minWidth: 150 }, { key: 'mr_role', label: 'CT / CW', width: 90 },
  { key: 'status', label: t('ground.history.status', '状态'), width: 130 },
  { key: 'summary', label: t('ground.history.summary', '摘要'), minWidth: 250 },
  { key: 'actions', label: t('common.actions', '操作'), width: 100, fixed: 'right' as const },
])
const mrOptions = computed(() => trains.value.filter((train) => !filters.train_id || train.train_id === filters.train_id).flatMap((train) => train.endpoints.filter((endpoint) => endpoint.mr_id).map((endpoint) => ({ value: endpoint.mr_id, label: `${train.train_no || train.train_id} / ${endpoint.endpoint} / ${endpoint.mr_name || endpoint.mr_id}` }))))
let generation = 0
let controller: AbortController | undefined
function currentFilters(): GroundHistoryFilters {
  return { ...filters, start_at: timeRange.value?.[0]?.toISOString() || '', end_at: timeRange.value?.[1]?.toISOString() || '' }
}
async function loadHistory(): Promise<void> {
  const current = ++generation
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  try {
    const result = await listGroundHistory({ ...currentFilters(), page: page.value, page_size: pageSize.value }, { signal: request.signal })
    if (current !== generation || request.signal.aborted) return
    rows.value = result.items; total.value = result.total; sources.value = result.sources; error.value = ''
  } catch (reason) {
    if (current === generation && !request.signal.aborted) error.value = reason instanceof Error ? reason.message : String(reason)
  } finally { if (current === generation) loading.value = false }
}
function searchHistory(): void { page.value = 1; void loadHistory() }
function showHistory(row: GroundHistoryRecord): void { selected.value = row; detailOpen.value = true }
async function exportHistory(): Promise<void> {
  if (!isFeatureEnabled('capability.ground_unattended.history_export')) return
  const snapshot = { ...currentFilters() } as Record<string, string>
  exporting.value = true
  try {
    await submitExportAfterDestinationSelected({
      action: 'rail.ground_history', suggestedName: `ground_history_${new Date().toISOString().slice(0, 10)}.csv`,
      context: snapshot, submit: () => startGroundHistoryExport(snapshot), taskId: (task) => task.task_id,
    })
  } catch (reason) { ElMessage.error(reason instanceof Error ? reason.message : String(reason)) }
  finally { exporting.value = false }
}
function openRawQuery(): void {
  if (!selected.value) return
  const row = selected.value
  selectedRunId.value = row.run_id
  syslogFilter.trainId = row.train_id; syslogFilter.mrRole = row.mr_role ? [row.mr_role] : []
  Object.assign(syslogFilter, { mrName: '', sourceIp: '', systemName: '', facility: '', severity: [], identityStatus: [], eventType: [], eventFamily: [], commandSource: [], physicalState: [], correlationStatus: [], correlationConfidence: [], peerName: '', dataSource: [], keyword: '', startTime: '', endTime: '', page: 1 })
  syslogTimeRange.value = timeRange.value.length === 2 ? [timeRange.value[0], timeRange.value[1]] : null
  detailOpen.value = false; activeTab.value = 'syslog'
}
watch([active, quickContextRevision], ([visible], [, previousRevision]) => {
  ++generation; controller?.abort(); loading.value = false
  if (previousRevision !== undefined && previousRevision !== quickContextRevision.value) {
    rows.value = []; total.value = 0; selected.value = null; detailOpen.value = false; page.value = 1
    Object.assign(filters, { sort_order: 'desc', data_type: '', run_id: '', train_id: '', mr_id: '', mr_role: '', event_type: '' }); timeRange.value = []
  }
  if (visible) void loadHistory()
}, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort() })
</script>

<template>
<section class="ground-subpage">
        <h3>{{ t('ground.history.workbench', '历史查询工作台') }}</h3>
        <div class="toolbar history-filters">
          <el-select v-model="filters.data_type" clearable :placeholder="t('ground.history.all_types', '全部数据类型')"><el-option v-for="item in historyTypes" :key="item[0]" :value="item[0]" :label="t(item[1], item[2])" /></el-select>
          <el-input v-model="filters.run_id" clearable :placeholder="t('ground.history.run_id', '运行 / 任务 ID')" />
          <el-select v-model="filters.train_id" clearable filterable :placeholder="t('ground.history.all_trains', '全部列车')"><el-option v-for="train in trains" :key="train.train_id" :value="train.train_id" :label="train.train_no || train.train_id" /></el-select>
          <el-select v-model="filters.mr_id" clearable filterable allow-create default-first-option placeholder="MR UUID"><el-option v-for="mr in mrOptions" :key="mr.value" :value="mr.value" :label="mr.label" /></el-select>
          <el-select v-model="filters.mr_role" clearable placeholder="CT / CW"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
          <el-input v-model="filters.event_type" clearable :placeholder="t('ground.history.event_type', '事件类型（精确值）')" />
          <el-date-picker v-model="timeRange" type="datetimerange" :start-placeholder="t('ground.history.start', '开始时间')" :end-placeholder="t('ground.history.end', '结束时间')" />
          <el-select v-model="filters.sort_order" :aria-label="t('ground.history.sort', '时间排序')" @change="searchHistory"><el-option value="desc" :label="t('ground.history.newest', '最新在前')" /><el-option value="asc" :label="t('ground.history.oldest', '最早在前')" /></el-select>
          <el-button :loading="loading" @click="searchHistory">{{ t('common.search', '查询') }}</el-button>
          <el-button v-if="isFeatureVisible('capability.ground_unattended.history_export')" :loading="exporting" :disabled="!isFeatureEnabled('capability.ground_unattended.history_export') || hasActiveExportAction('rail.ground_history')" @click="exportHistory">{{ t('ground.history.export_all', '导出筛选结果（全量）') }}</el-button>
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <el-alert v-if="missingSources" :title="`${t('ground.history.unavailable', '缺少历史索引')}: ${missingSources}`" type="warning" :closable="false" />
        <p class="history-note">{{ t('ground.history.raw_note', '原始 Syslog 按文件登记，详情显示条数、修订号与 SHA-256；逐条报文使用原始日志查询。') }}</p>
        <NcDataTable :data="rows" :columns="historyColumns" table-id="ground-history" route-key="rail-ground-unattended" row-key="record_id" max-height="440" compact>
          <template #cell-data_type="{ row }">{{ typeLabel(row.data_type) }}</template>
          <template #cell-actions="{ row }"><el-button size="small" text type="primary" @click="showHistory(row)">{{ t('common.view', '查看') }}</el-button></template>
        </NcDataTable>
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[50, 100, 200, 500]" :total="total" layout="total, sizes, prev, pager, next" @current-change="loadHistory" @size-change="searchHistory" />
        <el-drawer v-model="detailOpen" :title="t('ground.history.details', '历史记录详情')" size="min(760px, 96vw)" append-to-body>
          <template v-if="selected"><p>{{ typeLabel(selected.data_type) }} · {{ selected.ts }}</p><el-button v-if="selected.data_type === 'syslog_raw'" @click="openRawQuery">{{ t('ground.history.query_raw', '逐条查询原始日志') }}</el-button><pre class="history-details">{{ JSON.stringify(selected.details, null, 2) }}</pre></template>
        </el-drawer>
        <h3>{{ t('ground.history.archive_packages', '归档包与完整性校验') }}</h3>
        <div class="toolbar"><el-button :icon="FolderOpened" @click="openArchiveDirectory">{{ t('ground.open_archive_directory', '打开归档目录') }}</el-button></div>
        <div ref="archiveTableHost" class="table-frame"><NcDataTable :data="archives" :columns="archiveColumns" table-id="ground-archives" route-key="rail-ground-unattended" row-key="archive_id" :max-height="archiveTableMaxHeight" auto-height compact>
          <template #cell-archive_status="{ row }"><el-tag size="small" :type="statusType(row.archive_status)">{{ groundStatusLabel(row.archive_status) }}</el-tag></template>
          <template #cell-actions="{ row }"><div class="row-actions"><el-button size="small" text type="primary" @click="showArchive(row)">{{ t('common.view', '查看') }}</el-button><el-button :icon="Download" size="small" text circle :title="t('ground.history.download_zip', '下载原始 ZIP')" @click="downloadArchiveZip(row)" /><el-button size="small" text @click="downloadArchiveSummary(row)">JSON</el-button><el-button :icon="Delete" size="small" text type="danger" circle :title="t('common.delete', '删除')" @click="removeArchive(row)" /></div></template>
        </NcDataTable></div>

</section>
</template>

<style scoped src="./groundUnattended.css"></style>
<style scoped>
.history-filters{display:flex;flex-wrap:wrap;gap:8px}.history-filters .el-select,.history-filters .el-input{width:185px}.history-note{color:var(--el-text-color-secondary);margin:0;font-size:12px}.history-details{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.6}
</style>
