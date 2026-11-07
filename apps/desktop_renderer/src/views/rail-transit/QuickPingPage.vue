<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getGroundQuickPing, getGroundQuickPingSamples, listGroundQuickPing, startGroundQuickPing, stopGroundQuickPing, stopGroundQuickPingTarget } from '../../api/groundUnattended'
import type { GroundQuickPingRun, GroundQuickPingTarget, GroundTrain } from '../../types/groundUnattended'
import QuickPingChart from '../../components/ground-unattended/QuickPingChart.vue'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import { t } from '../../i18n/runtime'

const props = defineProps<{ trains: GroundTrain[]; active: boolean; mrId?: string }>()
const runs = ref<GroundQuickPingRun[]>([])
const selected = ref<GroundQuickPingRun | null>(null)
const selectedKeys = ref<string[]>([])
const trainFilter = ref('')
const roleFilter = ref('')
const addressFilter = ref('')
const targetQuery = ref('')
const activeIps = ref<Record<string, string>>({})
const historyQuery = ref('')
const historyState = ref('')
const historyRange = ref<Date[]>([])
const historyPage = ref(1)
const historyTotal = ref(0)
const historyPageSize = 50
const sampleTarget = ref('')
const sampleRange = ref<number | 'all' | 'custom'>(5)
const customSampleRange = ref<Date[]>([])
const sampleRows = ref<Array<Record<string, unknown>>>([])
const sampleCursor = ref('')
const sampleLoading = ref(false)
const sampleError = ref('')
const sampleBudgetExhausted = ref(false)
const samplePage = ref(1)
let sampleBounds: { start_time?: string; end_time?: string } = {}
const durationMode = ref<number | 'custom' | 'unlimited'>('unlimited')
const customDuration = ref(60)
const loading = ref(false)
const error = ref('')
const config = reactive({ interval_ms: 200, timeout_ms: 1000, packet_size: 64, max_in_flight: 32 })
const isRunning = (run: GroundQuickPingRun | null) => !!run && ['RUNNING', 'STOPPING'].includes(run.state)
const targetKey = (target: GroundQuickPingTarget) => `${target.mr_id}:${target.address_role}:${target.target_ip}`
const targets = computed(() => props.trains.flatMap((train) => train.endpoints.flatMap((endpoint) => {
  const base = { train_id: train.train_id, train_no: train.train_no, mr_id: endpoint.mr_id, mr_name: endpoint.mr_name, mr_role: endpoint.endpoint }
  const result: GroundQuickPingTarget[] = []
  if (endpoint.mr_id && endpoint.management_ip) result.push({ ...base, target_ip: endpoint.management_ip, address_role: 'PRIMARY' })
  if (endpoint.mr_id && endpoint.backup_management_ip) result.push({ ...base, target_ip: endpoint.backup_management_ip, address_role: 'BACKUP' })
  return result
})))
const filteredTargets = computed(() => targets.value.filter((target) =>
  (!trainFilter.value || target.train_id === trainFilter.value)
  && (!roleFilter.value || target.mr_role === roleFilter.value)
  && (!addressFilter.value || target.address_role === addressFilter.value)
  && (!targetQuery.value.trim() || `${target.mr_name} ${target.mr_id} ${target.target_ip}`.toLowerCase().includes(targetQuery.value.trim().toLowerCase()))))
const targetGroups = computed(() => {
  const groups = new Map<string, GroundQuickPingTarget[]>()
  for (const target of filteredTargets.value) {
    const label = `${target.train_no || target.train_id} / ${target.mr_role}`
    groups.set(label, [...(groups.get(label) || []), target])
  }
  return [...groups].map(([label, rows]) => ({ label, rows }))
})
const selectedTargets = computed(() => [...new Map(targets.value
  .filter((target) => selectedKeys.value.includes(targetKey(target)))
  .map((target) => [target.target_ip.trim(), target])).values()])
const occupiedBy = (target: GroundQuickPingTarget) => activeIps.value[target.target_ip.trim()] || ''
const targetDisabled = (target: GroundQuickPingTarget) => !!occupiedBy(target) || selectedTargets.value.some((selected) => selected.target_ip === target.target_ip && targetKey(selected) !== targetKey(target))
function removeTarget(target: GroundQuickPingTarget): void {
  selectedKeys.value = selectedKeys.value.filter((key) => !targets.value.some((item) => targetKey(item) === key && item.target_ip === target.target_ip))
}
const targetState = (ip: string) => selected.value?.target_runtime?.[ip]?.state || selected.value?.state || ''
const targetActive = (ip: string) => ['QUEUED', 'STARTING', 'RUNNING', 'STOPPING'].includes(targetState(ip))
const rtt = (value?: number | null) => value == null ? '—' : `${value.toFixed(2)} ms`
const runDuration = (run: GroundQuickPingRun) => {
  const start = Date.parse(run.started_at), end = Date.parse(run.ended_at || new Date().toISOString())
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—'
  const seconds = Math.floor((end - start) / 1000)
  return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
const sampleValue = (row: Record<string, unknown>, key: string): unknown => {
  const sample = row.sample
  return sample && typeof sample === 'object' ? (sample as Record<string, unknown>)[key] : undefined
}
let sampleGeneration = 0
let sampleController: AbortController | undefined
let appliedMrId = ''
let generation = 0
let pollGeneration = 0
let disposed = false
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined

async function refresh(showError = false): Promise<void> {
  const current = ++generation
  controller?.abort()
  const request = new AbortController()
  controller = request
  const selectedId = selected.value?.run_id
  try {
    const [page, detail] = await Promise.all([
      listGroundQuickPing(historyPageSize, { signal: request.signal }, {
        offset: (historyPage.value - 1) * historyPageSize, query: historyQuery.value.trim(), state: historyState.value,
        start_time: historyRange.value?.[0]?.toISOString(), end_time: historyRange.value?.[1]?.toISOString(),
      }),
      selectedId ? getGroundQuickPing(selectedId, { signal: request.signal }) : Promise.resolve(null),
    ])
    if (current !== generation) return
    activeIps.value = page.active_ips ?? {}
    runs.value = page.items
    historyTotal.value = page.total
    selected.value = detail ?? page.items.find(isRunning) ?? page.items[0] ?? null
    error.value = ''
    if (props.active && selectedId === selected.value?.run_id && isRunning(selected.value) && samplePage.value === 1 && !sampleLoading.value && sampleRange.value !== 'all' && sampleRange.value !== 'custom') void loadSamples()
  } catch (reason) {
    if (current === generation && !request.signal.aborted) {
      error.value = reason instanceof Error ? reason.message : String(reason)
      if (showError) ElMessage.error(error.value)
    }
  }
}
async function searchHistory(): Promise<void> { historyPage.value = 1; await refresh(true) }

async function loadSamples(next = false): Promise<void> {
  const run = selected.value
  if (!run || !sampleTarget.value) return
  const current = ++sampleGeneration
  sampleController?.abort()
  const request = new AbortController()
  sampleController = request
  if (!next) {
    samplePage.value = 1
    sampleCursor.value = ''
    sampleRows.value = []
    const end = new Date(run.ended_at || Date.now())
    sampleBounds = sampleRange.value === 'custom'
      ? { start_time: customSampleRange.value?.[0]?.toISOString(), end_time: customSampleRange.value?.[1]?.toISOString() }
      : sampleRange.value === 'all' ? {} : { start_time: new Date(end.getTime() - sampleRange.value * 60000).toISOString(), end_time: end.toISOString() }
    if (sampleRange.value === 'custom' && (!sampleBounds.start_time || !sampleBounds.end_time)) {
      sampleError.value = t('ground.quick.select_range', '请选择完整的曲线时间范围')
      sampleLoading.value = false
      return
    }
  }
  sampleLoading.value = true
  try {
    const result = await getGroundQuickPingSamples(run.run_id, {
      target_ip: sampleTarget.value, ...sampleBounds, limit: 1000, cursor: next ? sampleCursor.value : '',
    }, { signal: request.signal })
    if (current !== sampleGeneration || request.signal.aborted) return
    sampleRows.value = result.items
    sampleCursor.value = result.next_cursor
    sampleBudgetExhausted.value = result.scan_budget_exhausted
    if (next) samplePage.value += 1
    sampleError.value = ''
  } catch (reason) {
    if (current === sampleGeneration && !request.signal.aborted) sampleError.value = reason instanceof Error ? reason.message : String(reason)
  } finally { if (current === sampleGeneration) sampleLoading.value = false }
}
async function selectRun(run: GroundQuickPingRun): Promise<void> {
  selected.value = run
  await refresh(true)
}
async function start(): Promise<void> {
  if (!isFeatureEnabled('capability.ground_unattended.quick_ping')) return
  if (selectedTargets.value.some((target) => occupiedBy(target))) { error.value = t('ground.quick.selection_occupied', '所选 IP 已被活动任务占用，请移除后重试'); return }
  if (!selectedTargets.value.length) { ElMessage.warning(t('ground.quick.select_target', '请至少选择一个 MR 管理地址')); return }
  const duration = durationMode.value === 'unlimited' ? null : durationMode.value === 'custom' ? customDuration.value : durationMode.value
  if (duration != null && (!Number.isFinite(duration) || duration <= 0 || duration > 604800)) { ElMessage.warning(t('ground.quick.invalid_duration', '时长须大于 0 秒且不超过 7 天')); return }
  loading.value = true
  try {
    ++generation
    controller?.abort()
    const run = await startGroundQuickPing({ targets: selectedTargets.value, ...config, duration_seconds: duration })
    if (disposed) return
    selected.value = run
    await refresh(true)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); ElMessage.error(error.value) } finally { loading.value = false }
}
async function stop(): Promise<void> {
  if (!selected.value || !isRunning(selected.value)) return
  loading.value = true
  try {
    ++generation
    controller?.abort()
    const run = await stopGroundQuickPing(selected.value.run_id)
    if (disposed) return
    selected.value = run
    await refresh(true)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); ElMessage.error(error.value) } finally { loading.value = false }
}
async function stopTarget(targetIp: string): Promise<void> {
  if (!selected.value || !targetActive(targetIp)) return
  loading.value = true
  try {
    const run = await stopGroundQuickPingTarget(selected.value.run_id, targetIp)
    if (disposed) return
    selected.value = run
    await refresh(true)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : String(reason); ElMessage.error(error.value) }
  finally { loading.value = false }
}
async function poll(): Promise<void> {
  if (!props.active) return
  const current = pollGeneration
  if (!loading.value) await refresh()
  if (props.active && current === pollGeneration) timer = setTimeout(poll, 2000)
}
watch(() => props.active, (active) => {
  ++pollGeneration
  if (timer) clearTimeout(timer)
  if (active) { void poll(); if (selected.value && sampleTarget.value) void loadSamples() }
  else { ++generation; controller?.abort(); ++sampleGeneration; sampleController?.abort(); sampleLoading.value = false }
}, { immediate: true })
watch([() => props.mrId, targets], ([mrId, available]) => {
  if (!mrId || appliedMrId === mrId) return
  const matches = available.filter((target) => target.mr_id === mrId)
  if (!matches.length) return
  selectedKeys.value = matches.map(targetKey)
  trainFilter.value = matches[0]!.train_id
  roleFilter.value = matches[0]!.mr_role
  addressFilter.value = ''
  appliedMrId = mrId
}, { immediate: true })
watch(() => selected.value?.run_id, () => {
  ++sampleGeneration
  sampleController?.abort()
  sampleRows.value = []
  sampleCursor.value = ''
  sampleTarget.value = selected.value?.targets[0]?.target_ip || ''
  if (props.active && sampleTarget.value) void loadSamples()
})
watch([sampleTarget, sampleRange, customSampleRange], () => { if (props.active) void loadSamples() })
onBeforeUnmount(() => { disposed = true; ++generation; ++pollGeneration; ++sampleGeneration; controller?.abort(); sampleController?.abort(); if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="quick-ping-page">
    <header class="quick-heading"><div><h2>{{ t('ground.quick.title', '快速 Ping') }}</h2><p>{{ t('ground.quick.subtitle', '车载 MR 管理地址批量检测') }}</p></div><span>{{ selectedTargets.length }} {{ t('ground.quick.selected_ips', '已选 IP') }}</span></header>
    <div class="quick-setup">
    <div class="toolbar">
      <el-select v-model="trainFilter" clearable filterable :placeholder="t('ground.quick.all_trains', '全部列车')"><el-option v-for="train in trains" :key="train.train_id" :label="train.train_no || train.train_id" :value="train.train_id" /></el-select>
      <el-select v-model="roleFilter" clearable placeholder="CT / CW"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select>
      <el-select v-model="addressFilter" clearable :placeholder="t('ground.quick.address_roles', '主用 / 备用')"><el-option :label="t('ground.quick.primary', '主用')" value="PRIMARY" /><el-option :label="t('ground.quick.backup', '备用')" value="BACKUP" /></el-select>
      <el-input v-model="targetQuery" clearable class="target-search" :placeholder="t('ground.quick.search_mr_ip', '搜索 MR 名称、UUID 或 IP')" />
      <el-select v-model="selectedKeys" multiple collapse-tags collapse-tags-tooltip filterable class="target-select" :placeholder="t('ground.quick.select_addresses', '选择 MR 管理地址')"><el-option-group v-for="group in targetGroups" :key="group.label" :label="group.label"><el-option v-for="target in group.rows" :key="targetKey(target)" :label="`${target.train_no || target.train_id} / ${target.mr_role} / ${target.mr_name || target.mr_id} / ${target.target_ip} (${target.address_role})`" :value="targetKey(target)" :disabled="targetDisabled(target)"><span>{{ target.mr_name || target.mr_id }} / {{ target.target_ip }} ({{ target.address_role }})</span><small v-if="occupiedBy(target)" class="occupied">{{ t('ground.quick.occupied', '占用任务') }}: {{ occupiedBy(target) }}</small></el-option></el-option-group></el-select>
    </div>
    <div class="selected-targets">
      <span>{{ t('ground.quick.selected_ips', '已选 IP') }}: {{ selectedTargets.length }}</span>
      <el-tag v-for="target in selectedTargets" :key="target.target_ip" closable :type="occupiedBy(target) ? 'warning' : 'info'" @close="removeTarget(target)">{{ target.mr_name || target.mr_id }} · {{ target.target_ip }} · {{ target.address_role }}</el-tag>
      <el-button v-if="selectedTargets.length" text @click="selectedKeys = []">{{ t('ground.quick.clear_selection', '清空选择') }}</el-button>
    </div>
    <div class="toolbar parameters">
      <label>{{ t('ground.quick.interval', '间隔 ms') }} <el-input-number v-model="config.interval_ms" :min="1" :max="60000" :controls="false" /></label>
      <label>{{ t('ground.quick.timeout', '超时 ms') }} <el-input-number v-model="config.timeout_ms" :min="1" :max="60000" :controls="false" /></label>
      <label>{{ t('ground.quick.packet', '包 Bytes') }} <el-input-number v-model="config.packet_size" :min="1" :max="65507" :controls="false" /></label>
      <el-select v-model="durationMode" :placeholder="t('ground.quick.unlimited', '无限时长')" class="duration-select"><el-option :label="t('ground.quick.unlimited', '无限时长')" value="unlimited" /><el-option :label="t('ground.quick.seconds30', '30 秒')" :value="30" /><el-option :label="t('ground.quick.minute1', '1 分钟')" :value="60" /><el-option :label="t('ground.quick.minutes5', '5 分钟')" :value="300" /><el-option :label="t('ground.quick.minutes10', '10 分钟')" :value="600" /><el-option :label="t('ground.quick.custom', '自定义')" value="custom" /></el-select>
      <label v-if="durationMode === 'custom'">{{ t('ground.quick.duration_seconds', '时长（秒）') }} <el-input-number v-model="customDuration" :min="1" :max="604800" :controls="false" /></label>
      <el-button v-if="isFeatureVisible('capability.ground_unattended.quick_ping')" type="primary" :loading="loading" :disabled="!isFeatureEnabled('capability.ground_unattended.quick_ping')" @click="start">{{ t('ground.quick.start', '开始') }}</el-button>
      <el-button type="danger" plain :loading="loading" :disabled="!isRunning(selected)" @click="stop">{{ t('ground.quick.stop', '停止当前任务') }}</el-button>
      <el-button :icon="Refresh" :title="t('ground.quick.refresh', '刷新')" @click="refresh(true)" />
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </div>
    <div v-if="selected" class="detail">
      <div class="status-line"><b>{{ selected.run_id }}</b><el-tag>{{ selected.state }}</el-tag><span>{{ selected.started_at }} - {{ selected.ended_at || t('ground.quick.running', '运行中') }}</span></div>
      <el-alert v-if="selected.error" :title="selected.error" type="error" :closable="false" />
      <div class="metrics"><span>{{ t('ground.quick.counts', '发送 / 接收 / 丢包') }} <b>{{ selected.stats.sent }} / {{ selected.stats.received }} / {{ selected.stats.lost }}</b></span><span>{{ t('ground.quick.loss', '丢包率') }} <b>{{ selected.stats.loss_rate_percent.toFixed(2) }}%</b></span><span>{{ t('ground.quick.rtt', '最小 / 平均 / 最大 RTT') }} <b>{{ selected.stats.min_rtt_ms?.toFixed(2) ?? '—' }} / {{ selected.stats.avg_rtt_ms?.toFixed(2) ?? '—' }} / {{ selected.stats.max_rtt_ms?.toFixed(2) ?? '—' }} ms</b></span><span>{{ t('ground.quick.jitter', '抖动') }} <b>{{ selected.stats.jitter_ms?.toFixed(2) ?? '—' }} ms</b></span><span>{{ t('ground.quick.consecutive_loss', '连续丢包 当前 / 最大') }} <b>{{ selected.stats.current_consecutive_loss }} / {{ selected.stats.max_consecutive_loss }}</b></span></div>
      <div class="toolbar">
        <el-select v-model="sampleTarget" :placeholder="t('ground.quick.chart_ip', '曲线目标 IP')"><el-option v-for="target in selected.targets" :key="target.target_ip" :value="target.target_ip" :label="`${target.mr_role} ${target.target_ip}`" /></el-select>
        <el-select v-model="sampleRange"><el-option :value="5" :label="t('ground.quick.last5', '最后 5 分钟')" /><el-option :value="30" :label="t('ground.quick.last30', '最后 30 分钟')" /><el-option :value="60" :label="t('ground.quick.last60', '最后 1 小时')" /><el-option value="all" :label="t('ground.quick.whole_run', '完整任务范围')" /><el-option value="custom" :label="t('ground.quick.custom_range', '自定义时间范围')" /></el-select>
        <el-date-picker v-if="sampleRange === 'custom'" v-model="customSampleRange" type="datetimerange" :start-placeholder="t('ground.quick.chart_start', '曲线开始时间')" :end-placeholder="t('ground.quick.chart_end', '曲线结束时间')" />
        <el-button :loading="sampleLoading" @click="loadSamples()">{{ t('ground.quick.query_chart', '查询曲线') }}</el-button>
        <el-button :loading="sampleLoading" :disabled="!sampleCursor" @click="loadSamples(true)">{{ t('ground.quick.next_samples', '下一页样本') }}</el-button>
        <span>{{ t('ground.quick.page', '页') }} {{ samplePage }} · {{ sampleRows.length }} / 1000 {{ t('ground.quick.samples', '条样本') }}</span>
      </div>
      <el-alert v-if="sampleError" :title="sampleError" type="error" :closable="false" />
      <el-alert v-if="sampleBudgetExhausted" :title="t('ground.quick.budget', '本页达到读取预算，请继续下一页扫描所选时间范围')" type="info" :closable="false" />
      <QuickPingChart :key="`${selected.run_id}:${sampleTarget}:${sampleRange}`" :rows="sampleRows" :interval-ms="selected.config?.interval_ms || 200" :active="active" />
      <el-table :data="selected.targets" size="small" stripe><el-table-column prop="train_no" :label="t('ground.quick.train', '列车')" /><el-table-column prop="mr_role" label="CT / CW" /><el-table-column prop="mr_name" label="MR" /><el-table-column prop="target_ip" :label="t('ground.quick.management_ip', '管理 IP')" /><el-table-column prop="address_role" :label="t('ground.quick.address_role', '地址角色')" /><el-table-column :label="t('ground.quick.state', '状态')" min-width="110"><template #default="scope"><el-tag>{{ targetState(scope.row.target_ip) }}</el-tag></template></el-table-column><el-table-column :label="t('ground.quick.started', '开始时间')" min-width="190"><template #default="scope">{{ selected.target_runtime?.[scope.row.target_ip]?.started_at || '—' }}</template></el-table-column><el-table-column :label="t('ground.quick.counts', '发送 / 接收 / 丢包')"><template #default="scope">{{ selected.target_stats[scope.row.target_ip]?.sent ?? 0 }} / {{ selected.target_stats[scope.row.target_ip]?.received ?? 0 }} / {{ selected.target_stats[scope.row.target_ip]?.lost ?? 0 }}</template></el-table-column><el-table-column :label="t('ground.quick.loss', '丢包率')"><template #default="scope">{{ selected.target_stats[scope.row.target_ip]?.loss_rate_percent?.toFixed(2) ?? '—' }}%</template></el-table-column><el-table-column :label="t('ground.quick.current_rtt', '当前 RTT')"><template #default="scope">{{ rtt(selected.target_stats[scope.row.target_ip]?.current_rtt_ms) }}</template></el-table-column><el-table-column :label="t('ground.quick.average_rtt', '平均 RTT')"><template #default="scope">{{ rtt(selected.target_stats[scope.row.target_ip]?.avg_rtt_ms) }}</template></el-table-column><el-table-column :label="t('ground.quick.maximum_rtt', '最大 RTT')"><template #default="scope">{{ rtt(selected.target_stats[scope.row.target_ip]?.max_rtt_ms) }}</template></el-table-column><el-table-column :label="t('ground.quick.actions', '操作')"><template #default="scope"><el-button text type="danger" :disabled="!targetActive(scope.row.target_ip) || loading" @click="stopTarget(scope.row.target_ip)">{{ t('ground.quick.stop_ip', '停止此 IP') }}</el-button></template></el-table-column></el-table>
      <el-table :data="sampleRows" size="small" max-height="240" stripe><el-table-column prop="received_at" :label="t('ground.quick.time', '时间')" /><el-table-column prop="target_ip" :label="t('ground.quick.target_ip', '目标 IP')" /><el-table-column :label="t('ground.quick.result', '结果')"><template #default="scope">{{ sampleValue(scope.row, 'ok') ? t('ground.quick.success', '成功') : t('ground.quick.lost', '丢包') }}</template></el-table-column><el-table-column label="RTT"><template #default="scope">{{ sampleValue(scope.row, 'rtt_ms') ?? '—' }} ms</template></el-table-column></el-table>
    </div>
    <section class="history-panel"><h3>{{ t('ground.quick.history', '任务历史') }}</h3>
    <div class="toolbar">
      <el-input v-model="historyQuery" clearable :placeholder="t('ground.quick.history_query', '任务、日期、列车、MR 或 IP')" @keyup.enter="searchHistory" />
      <el-select v-model="historyState" clearable :placeholder="t('ground.quick.all_states', '全部状态')"><el-option v-for="state in ['RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED', 'TIME_LIMIT', 'INTERRUPTED']" :key="state" :label="state" :value="state" /></el-select>
      <el-date-picker v-model="historyRange" type="datetimerange" :start-placeholder="t('ground.quick.history_start', '任务开始时间下限')" :end-placeholder="t('ground.quick.history_end', '任务开始时间上限')" />
      <el-button @click="searchHistory">{{ t('ground.quick.query_history', '查询历史') }}</el-button>
    </div>
    <el-table :data="runs" size="small" stripe max-height="300"><el-table-column prop="run_id" :label="t('ground.quick.task', '任务')" min-width="210" /><el-table-column prop="state" :label="t('ground.quick.state', '状态')" width="110" /><el-table-column :label="t('ground.quick.targets', '目标')" width="80"><template #default="scope">{{ scope.row.targets.length }}</template></el-table-column><el-table-column prop="started_at" :label="t('ground.quick.started', '开始时间')" min-width="180" /><el-table-column :label="t('ground.quick.duration', '持续时间')" width="105"><template #default="scope">{{ runDuration(scope.row) }}</template></el-table-column><el-table-column :label="t('ground.quick.average_rtt', '平均 RTT')" width="105"><template #default="scope">{{ rtt(scope.row.stats.avg_rtt_ms) }}</template></el-table-column><el-table-column :label="t('ground.quick.loss', '丢包率')" width="90"><template #default="scope">{{ scope.row.stats.loss_rate_percent.toFixed(2) }}%</template></el-table-column><el-table-column :label="t('ground.quick.actions', '操作')" width="80"><template #default="scope"><el-button text type="primary" @click="selectRun(scope.row)">{{ t('ground.quick.view', '查看') }}</el-button></template></el-table-column></el-table>
    <el-pagination v-model:current-page="historyPage" :page-size="historyPageSize" :total="historyTotal" layout="total, prev, pager, next" @current-change="refresh(true)" />
    </section>
  </section>
</template>

<style scoped>
.quick-ping-page{display:flex;flex-direction:column;gap:12px;min-width:0}.quick-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.quick-heading h2{margin:0;font-size:20px}.quick-heading p{margin:4px 0 0;color:var(--el-text-color-secondary);font-size:12px}.quick-heading>span{color:var(--el-color-primary);font-size:13px}.quick-setup,.history-panel{display:flex;flex-direction:column;gap:12px;padding:16px;border:1px solid var(--el-border-color-light);border-radius:6px;background:var(--el-bg-color)}.quick-setup{order:1}.history-panel{order:2}.quick-ping-page>.detail{order:3;padding:16px;border-top:1px solid var(--el-border-color)}.toolbar,.status-line{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.toolbar .el-select{width:145px}.toolbar .target-select{width:min(520px,100%)}.toolbar .duration-select{width:130px}.parameters label{display:flex;gap:5px;align-items:center}.parameters .el-input-number{width:90px}.detail{display:flex;flex-direction:column;gap:10px}.metrics{display:flex;flex-wrap:wrap;gap:16px}.metrics span{display:flex;flex-direction:column;gap:4px;color:var(--el-text-color-secondary)}.metrics b{color:var(--el-text-color-primary)}.chart svg{display:block;width:100%;height:140px;background:var(--el-fill-color-light)}.selected-targets{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.occupied{display:block;color:var(--el-color-warning);line-height:18px}.target-search{width:230px}.quick-ping-page h3{margin:4px 0}.history-panel>.toolbar>.el-input{flex:1 1 220px;max-width:380px}.history-panel>.toolbar>.el-select{width:180px}@media(max-width:800px){.quick-setup,.history-panel{padding:12px}.target-search,.toolbar .target-select{width:100%}.quick-heading{align-items:flex-start}}
</style>
