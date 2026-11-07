<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { t } from '../../i18n/runtime'
import { useGroundContext } from './useGroundUnattended'
import { listGroundDeepTasks, listGroundDeepCollectionRecords } from '../../api/groundUnattended'
import type { GroundDeepCollector, GroundDeepCollectionRecord, GroundDeepTaskPage } from '../../types/groundUnattended'
import { NcDataTable, type NcTableColumn } from '../../components/table'

const { profile, selectedRunId, activeTab, groundStatusLabel, bytes, openDeepSession } = useGroundContext()
const page = ref<GroundDeepTaskPage>({ items: [], total: 0, page: 1, page_size: 50, statistics: {} })
const filter = reactive({ train_id: '', mr_role: '', state: '', query: '', page: 1, page_size: 50, ascending: false })
const range = ref<[Date, Date] | null>(null)
const filtersOpen = ref(true); const autoRefresh = ref(true); const loading = ref(false); const issue = ref('')
const selected = ref<GroundDeepCollector | null>(null); const drawer = ref(false); const tab = ref('progress'); const logs = ref<GroundDeepCollectionRecord[]>([])
const category = ref('ALL'); const keyword = ref(''); const paused = ref(false); const logLoading = ref(false); const logIssue = ref('')
const observedAt = ref(Date.now())
let cursor = ''; let disposed = false; let listController: AbortController | undefined; let logController: AbortController | undefined; let generation = 0; let logGeneration = 0
const stats = computed(() => [['task_count','采集任务'],['running','运行中'],['completed','已最终化'],['failed','失败'],['partial','部分结果']].map(([key,label]) => ({ key, label: t(`ground.deep.stat_${key}`, label), value: page.value.statistics[key] ?? '—' })))
const items = computed(() => selected.value?.items ?? [])
const taskName = (task: GroundDeepCollector) => `${task.train_no || task.train_id} / ${task.mr_role} / ${task.mr_id}`
const columns = computed<NcTableColumn<GroundDeepCollector>[]>(() => [
  { key: 'selection', label: '', type: 'selection', width: 48, fixed: 'left', hideable: false },
  { key: 'operation_id', label: t('ground.deep.task', '任务名称'), minWidth: 210, fixed: 'left', displayValue: taskName },
  { key: 'train_no', label: t('ground.deep.train', '列车'), displayValue: row => row.train_no || row.train_id, fixed: 'left' }, { key: 'mr_role', label: t('ground.deep.role', 'CT/CW'), width: 80 },
  { key: 'mr_id', label: t('ground.deep.device', 'MR 设备'), minWidth: 160 }, { key: 'management_ip', label: t('ground.deep.ip', '管理 IP'), valueType: 'ip' },
  { key: 'source_state', label: t('ground.deep.state', '任务状态'), valueType: 'status' }, { key: 'progress', label: t('ground.deep.progress', '综合采集进度'), minWidth: 220 },
  { key: 'items', label: t('ground.deep.items', '采集项目'), minWidth: 220 },
  { key: 'duration', label: t('ground.deep.duration', '运行时长'), displayValue: row => duration(row.started_at, row.ended_at) },
  { key: 'bytes_written', label: t('ground.deep.bytes', '数据量'), displayValue: row => bytes(row.bytes_written) }, { key: 'started_at', label: t('ground.deep.start', '开始时间'), valueType: 'datetime', sortable: 'custom' },
  { key: 'actions', label: t('ground.deep.actions', '操作'), fixed: 'right', width: 80, hideable: false },
])
function active(task: GroundDeepCollector) { return ['STARTING','RUNNING','FINALIZING'].includes(task.source_state || task.state) }
function summary(task: GroundDeepCollector) {
  const all = task.items ?? []
  const running = all.filter(item => /running|starting|collecting/i.test(item.status)).length
  const failed = all.filter(item => /failed|error|missing/i.test(item.status)).length
  return t('ground.deep.item_summary', '{total} 项 · {running} 运行 · {failed} 异常')
    .replace('{total}', String(all.length)).replace('{running}', String(running)).replace('{failed}', String(failed))
}
function duration(start?: string, end?: string) {
  if (!start) return '—'
  const elapsed = (end ? Date.parse(end) : observedAt.value) - Date.parse(start)
  if (!Number.isFinite(elapsed) || elapsed < 0) return '—'
  const seconds = Math.floor(elapsed / 1000)
  return `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
async function load(silent = false) {
  if (silent && listController) return
  listController?.abort(); const controller = new AbortController(); listController = controller; const current = ++generation; if (!silent) loading.value = true
  try {
    const value = await listGroundDeepTasks({ ...filter, run_id: selectedRunId.value, start_at: range.value?.[0]?.toISOString() || '', end_at: range.value?.[1]?.toISOString() || '' }, { signal: controller.signal })
    if (disposed || current !== generation) return
    page.value = value; observedAt.value = Date.now(); issue.value = ''
    const updated = value.items.find(row => row.operation_id === selected.value?.operation_id); if (updated) selected.value = updated
  } catch (error) { if (!disposed && !controller.signal.aborted && current === generation) issue.value = error instanceof Error ? error.message : String(error) }
  finally { if (current === generation) { loading.value = false; listController = undefined } }
}
function query() { filter.page = 1; void load() }
function reset() { Object.assign(filter, { train_id:'', mr_role:'', state:'', query:'', page:1, ascending:false }); range.value = null; void load() }
function sort(event: { order: string | null }) { filter.ascending = event.order === 'ascending'; query() }
async function copyLogs() {
  try {
    await navigator.clipboard.writeText(logs.value.map(row => `${row.timestamp} [${row.source}] ${row.text}`).join('\n'))
    ElMessage.success(t('ground.deep.copied', '已复制当前已加载日志'))
  } catch { ElMessage.error(t('ground.deep.copy_failed', '复制失败，请检查剪贴板权限')) }
}
function show(task: GroundDeepCollector) { logController?.abort(); logController = undefined; logGeneration++; logLoading.value = false; selected.value = task; drawer.value = true; tab.value = 'progress'; logs.value = []; cursor = ''; logIssue.value = '' }
async function loadLogs(reset = false) {
  const task = selected.value; if (!task?.operation_id || !drawer.value || (paused.value && !reset)) return
  if (!reset && logController) return
  if (reset) { logController?.abort(); logs.value = []; cursor = '' }
  const controller = new AbortController(); logController = controller; const current = ++logGeneration; logLoading.value = true
  try {
    const result = await listGroundDeepCollectionRecords({ run_id: task.run_id, train_id: task.train_id, mr_id: task.mr_id, mr_role: task.mr_role, operation_id: task.operation_id, category: category.value, keyword: keyword.value, cursor, limit: 250 }, { signal: controller.signal })
    if (disposed || current !== logGeneration || task.operation_id !== selected.value?.operation_id) return
    selected.value = result.collector; cursor = result.next_cursor
    const seen = new Set(logs.value.map(row => `${row.source}:${row.sequence}`)); logs.value = [...logs.value, ...result.records.filter(row => !seen.has(`${row.source}:${row.sequence}`))].slice(-2000); logIssue.value = ''
  } catch (error) { if (!controller.signal.aborted && current === logGeneration) logIssue.value = error instanceof Error ? error.message : String(error) }
  finally { if (current === logGeneration) { logLoading.value = false; logController = undefined } }
}
watch([selectedRunId, activeTab], () => { listController?.abort(); generation++; listController = undefined; loading.value = false; drawer.value = false; selected.value = null; logs.value = []; cursor = ''; if (activeTab.value === 'deep') { filter.page = 1; void load() } }, { immediate: true })
watch(tab, value => { if (value === 'logs') void loadLogs() })
watch([category, keyword], () => { if (tab.value === 'logs') void loadLogs(true) })
watch(drawer, value => { if (!value) { logController?.abort(); logGeneration++; logController = undefined; logLoading.value = false } })
const timer = window.setInterval(() => { if (activeTab.value !== 'deep' || document.hidden) return; if (autoRefresh.value) void load(true); if (drawer.value && tab.value === 'logs' && !paused.value) void loadLogs() }, 4000)
onBeforeUnmount(() => { disposed = true; listController?.abort(); logController?.abort(); window.clearInterval(timer) })
</script>

<template>
  <section class="ground-subpage deep-page">
    <el-alert v-if="profile && !profile.deep_collection_master_enabled" :title="t('ground.v2.deep_lightweight', '当前为轻量模式：深度采集已关闭，历史记录仍可查看。')" type="info" :closable="false" show-icon />
    <div class="deep-stats"><article v-for="card in stats" :key="card.key"><span>{{ card.label }}</span><strong>{{ card.value }}</strong></article></div>
    <p class="scope-note">{{ t('ground.deep.scope', '统计范围：所选运行全部已创建的 AP/MR 主任务。持续采样没有可计算的完成百分比；停止不等于成功。') }}</p>
    <div class="toolbar"><el-button @click="filtersOpen = !filtersOpen">{{ t('ground.deep.filters', '筛选条件') }}</el-button><el-checkbox v-model="autoRefresh">{{ t('ground.v2.auto_refresh', '自动刷新') }}</el-checkbox><el-button :loading="loading" @click="load()">{{ t('common.refresh', '刷新') }}</el-button></div>
    <div v-show="filtersOpen" class="deep-filters"><el-input v-model="filter.train_id" clearable :placeholder="t('ground.deep.train_id', '列车 ID')" /><el-select v-model="filter.mr_role" clearable placeholder="CT/CW"><el-option v-for="role in ['CT','CW']" :key="role" :value="role" :label="role" /></el-select><el-select v-model="filter.state" clearable :placeholder="t('ground.deep.state', '任务状态')"><el-option v-for="state in ['STARTING','RUNNING','FINALIZING','COMPLETED','PARTIAL','FAILED']" :key="state" :value="state" :label="groundStatusLabel(state)" /></el-select><el-input v-model="filter.query" clearable :placeholder="t('ground.deep.search', '列车 / MR / 任务 ID / 管理 IP')" @keyup.enter="query" /><el-date-picker v-model="range" type="datetimerange" /><el-button type="primary" @click="query">{{ t('ground.v2.query', '查询') }}</el-button><el-button @click="reset">{{ t('common.reset', '重置') }}</el-button></div>
    <el-alert v-if="issue" :title="issue" type="error" :closable="false" />
    <NcDataTable v-loading="loading" :data="page.items" :columns="columns" table-id="ground-deep-ap:v2" route-key="rail-ground-unattended" row-key="operation_id" compact @sort-change="sort" @row-click="show">
      <template #cell-source_state="{ row }"><el-tag>{{ groundStatusLabel(row.source_state || row.state) }}</el-tag></template><template #cell-progress="{ row }"><div class="task-progress"><span>{{ summary(row) }}</span><small v-if="active(row)" class="running-indicator">{{ t('ground.deep.continuous', '持续采样 · 无百分比') }}</small></div></template><template #cell-items="{ row }"><div class="item-tags"><el-tag v-for="item in (row.items || []).slice(0, 3)" :key="item.name" :type="/failed|error|missing/i.test(item.status) ? 'danger' : /completed|finished|success/i.test(item.status) ? 'success' : 'info'" size="small">{{ item.label }} · {{ groundStatusLabel(item.status) }}</el-tag><small v-if="(row.items?.length || 0) > 3">+{{ row.items.length - 3 }}</small></div></template><template #cell-actions="{ row }"><el-button text type="primary" @click.stop="show(row)">{{ t('ground.details', '详情') }}</el-button></template>
    </NcDataTable><el-pagination v-model:current-page="filter.page" v-model:page-size="filter.page_size" :total="page.total" layout="total, sizes, prev, pager, next" @current-change="load()" @size-change="query" />
    <el-drawer v-model="drawer" :title="`${selected?.train_no || selected?.train_id || ''} / ${selected?.mr_role || ''}`" size="min(900px, 94vw)"><template v-if="selected">
      <el-descriptions :column="2" border><el-descriptions-item :label="t('ground.deep.target', '实际采集目标')">{{ selected.mr_id }} / {{ selected.management_ip || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.deep.state', '任务状态')">{{ groundStatusLabel(selected.state) }}</el-descriptions-item><el-descriptions-item :label="t('ground.deep.collected', '采集数据量')">{{ bytes(selected.bytes_written) }}</el-descriptions-item><el-descriptions-item :label="t('ground.deep.session', '会话')">{{ selected.collector_session_id || '—' }}</el-descriptions-item></el-descriptions>
      <el-tabs v-model="tab"><el-tab-pane :label="t('ground.deep.overall', '综合进度')" name="progress"><div class="progress-summary"><strong>{{ groundStatusLabel(selected.source_state || selected.state) }}</strong><span>{{ summary(selected) }}</span><span>{{ bytes(selected.bytes_written) }}</span><span>{{ duration(selected.started_at, selected.ended_at) }}</span></div><p v-if="selected.state_reason">{{ selected.state_reason }}</p><p class="scope-note">{{ t('ground.deep.continuous_note', '各项目为持续采样；数据量反映实际落盘量，不代表完成比例。') }}</p><div v-for="item in items" :key="item.name" class="child-progress"><strong>{{ item.label }}</strong><span :class="{ error: /failed|error|missing/i.test(item.status) }">{{ groundStatusLabel(item.status) }}</span><span>{{ bytes(item.size_bytes) }}</span><small v-if="item.error" class="error">{{ item.error }}</small></div><el-empty v-if="!items.length" :description="t('ground.deep.no_items', '尚无可读取的采集项目状态')" /></el-tab-pane>
      <el-tab-pane :label="t('ground.deep.items', '采集项目')" name="items"><el-table :data="items" size="small"><el-table-column prop="label" :label="t('ground.deep.items', '采集项目')" /><el-table-column prop="status" :label="t('ground.deep.status', '状态')"><template #default="{ row }">{{ groundStatusLabel(row.status) }}</template></el-table-column><el-table-column prop="size_bytes" :label="t('ground.deep.bytes', '数据量')"><template #default="{ row }">{{ bytes(row.size_bytes) }}</template></el-table-column><el-table-column prop="started_at" :label="t('ground.deep.start', '开始时间')" /><el-table-column prop="ended_at" :label="t('ground.deep.end', '结束时间')" /><el-table-column :label="t('ground.deep.duration', '运行时长')"><template #default="{ row }">{{ duration(row.started_at, row.ended_at) }}</template></el-table-column><el-table-column prop="updated_at" :label="t('ground.deep.updated', '最近更新')" /><el-table-column prop="error" :label="t('ground.deep.error', '错误')" /></el-table></el-tab-pane>
      <el-tab-pane :label="t('ground.deep.logs', '实时日志')" name="logs"><div class="toolbar"><el-select v-model="category"><el-option v-for="value in ['ALL','WMESH','RSSI','RADIO','STATUS','RAW_OUTPUT']" :key="value" :value="value" :label="value" /></el-select><el-input v-model="keyword" clearable :placeholder="t('ground.deep.keyword', '关键字')" /><el-checkbox v-model="paused">{{ t('ground.deep.pause', '暂停刷新') }}</el-checkbox><el-button :loading="logLoading" @click="loadLogs()">{{ t('ground.deep.refresh', '刷新') }}</el-button><el-button :disabled="!logs.length" @click="copyLogs">{{ t('ground.deep.copy_logs', '复制已加载日志') }}</el-button></div><el-alert v-if="logIssue" :title="logIssue" type="error" :closable="false" /><p class="scope-note">{{ t('ground.deep.log_budget', '日志按来源增量读取，最多保留最近 2000 条；完整文件可从会话查看。') }}</p><pre class="deep-logs">{{ logs.map(row => `${row.timestamp} [${row.source}] ${row.text}`).join('\n') || t('ground.deep.no_logs', '暂无可读取日志') }}</pre></el-tab-pane>
      <el-tab-pane :label="t('ground.deep.files', '采集文件')" name="files"><el-table :data="items" size="small"><el-table-column prop="label" :label="t('ground.deep.items', '采集项目')" /><el-table-column prop="raw_file" :label="t('ground.deep.raw', '原始文件')" /><el-table-column prop="exists" :label="t('ground.deep.exists', '文件存在')"><template #default="{ row }">{{ row.exists ? t('ground.deep.available', '可读取') : t('ground.deep.unavailable', '缺失或尚未产生') }}</template></el-table-column><el-table-column prop="size_bytes" :label="t('ground.deep.bytes', '数据量')"><template #default="{ row }">{{ bytes(row.size_bytes) }}</template></el-table-column></el-table><el-button :disabled="!selected.collector_session_id" @click="openDeepSession(selected.collector_session_id)">{{ t('ground.deep.open_session', '打开会话查看文件') }}</el-button></el-tab-pane>
      <el-tab-pane :label="t('ground.deep.config', '实际配置')" name="config"><el-descriptions :column="1" border><el-descriptions-item label="Ping IP">{{ selected.fping_target_ip || '—' }}</el-descriptions-item><el-descriptions-item :label="t('ground.deep.ping_interval', 'Ping 间隔')">{{ selected.fping_interval_ms || '—' }} ms</el-descriptions-item><el-descriptions-item :label="t('ground.deep.ping_timeout', 'Ping 超时')">{{ selected.fping_timeout_ms || '—' }} ms</el-descriptions-item><el-descriptions-item :label="t('ground.deep.ping_packet', 'Ping 包大小')">{{ selected.fping_packet_size || '—' }}</el-descriptions-item></el-descriptions></el-tab-pane></el-tabs>
    </template></el-drawer>
  </section>
</template>
<style scoped src="./groundUnattended.css"></style>
<style scoped>
.deep-page{display:grid;gap:10px;padding-bottom:16px}.deep-stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.deep-stats article{display:grid;gap:6px;min-width:0;background:var(--el-bg-color);padding:12px 14px;border:1px solid var(--el-border-color-light);border-radius:6px}.deep-stats span,.scope-note,.task-progress small{color:var(--el-text-color-secondary);font-size:12px}.deep-stats strong{font-size:22px;color:var(--el-text-color-primary)}.scope-note{margin:0;line-height:1.5}.deep-filters{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:10px 0;border-top:1px solid var(--el-border-color-lighter)}.deep-filters :deep(.el-input),.deep-filters :deep(.el-select),.deep-filters :deep(.el-date-editor){width:100%}.deep-filters :deep(.el-date-editor){grid-column:span 2}.task-progress{display:grid;gap:4px}.running-indicator{color:var(--el-color-primary)!important}.item-tags{display:flex;gap:4px;flex-wrap:wrap}.progress-summary{display:flex;align-items:center;flex-wrap:wrap;gap:14px;padding:12px;background:var(--el-fill-color-light);border-radius:4px;font-size:13px}.progress-summary strong{color:var(--el-color-primary)}.child-progress{display:grid;grid-template-columns:minmax(120px,2fr) minmax(100px,1fr) minmax(90px,1fr);gap:12px;padding:12px 0;border-bottom:1px solid var(--el-border-color-light)}.child-progress .error{grid-column:1/-1;color:var(--el-color-danger)}.deep-logs{max-height:55vh;min-height:200px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--el-fill-color-light);padding:12px}@media(max-width:1000px){.deep-filters{grid-template-columns:repeat(2,minmax(0,1fr))}.deep-stats{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:650px){.deep-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.child-progress{grid-template-columns:minmax(0,1fr) auto}}
</style>
