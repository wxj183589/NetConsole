<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import OnlineMrAgentControlPanel from '../../components/OnlineMrAgentControlPanel.vue'
import OnlineMrLocalControl from '../../components/OnlineMrLocalControl.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { getTrainCommunicationSummary, listTrainCommunications } from '../../api/trainCommunication'
import { useOnlineMrStore } from '../../stores/onlineMr'
import type { OnlineMrCollectorStatus, OnlineMrRawFile, OnlineMrRawTail } from '../../types/onlineMr'
import type { MrCommunicationStatus } from '../../types/trainCommunication'

const store = useOnlineMrStore()
const route = useRoute()
const expanded = ref<string[]>([])
const rawSource = ref('terminal_monitor')
const controlMrs = ref<MrCommunicationStatus[]>([])
const controlMrId = ref('')
const controlError = ref('')
const controlSiteId = ref('')
const executorTab = ref('local')

interface OnlineMrRuntimeStatusRow extends OnlineMrCollectorStatus {
  current_size_bytes: number
  recent_growth_at: string | null
  action_source: string
  row_kind: 'collector' | 'raw_file'
  issue: string
}

const rawSourceByCollector: Record<string, string> = {
  terminal_monitor: 'terminal_monitor',
  mesh_link: 'mesh_link',
  channel_busy: 'channel_busy',
  ap_radio_statistics: 'ap_radio_statistics',
  wireless_status: 'wireless_status',
  interface_rate: 'interface_rate',
  switch_history: 'switch_history',
  fping_v5: 'fping_raw',
  iperf_client: 'iperf_client',
}
const extraRawRows = new Set(['fping_samples', 'fping_summary', 'collector_output'])
const otherRawSourceOptions = [
  { label: '终端实时日志', value: 'terminal_monitor' },
  { label: '无线状态', value: 'wireless_status' },
  { label: '空口负载', value: 'channel_busy' },
  { label: '主链路切换历史', value: 'switch_history' },
  { label: 'iPerf 客户端', value: 'iperf_client' },
  { label: 'fping 样本', value: 'fping_samples' },
  { label: 'fping 汇总', value: 'fping_summary' },
  { label: '采集器输出', value: 'collector_output' },
]

const collectorColumns: NcTableColumn<OnlineMrRuntimeStatusRow>[] = [
  { key: 'label', label: '采集项', valueType: 'name' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag', displayValue: collectorStatusLabel },
  { key: 'current_size_bytes', label: '当前大小', valueType: 'number', displayValue: (row) => formatBytes(row.current_size_bytes) },
  { key: 'recent_growth_at', label: '最近增长', valueType: 'datetime' },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime' },
  { key: 'health_status', label: '健康状态', valueType: 'status', cellKind: 'tag', displayValue: runtimeHealthLabel },
  { key: 'issue', label: '异常说明', valueType: 'text', displayValue: (row) => row.issue || '—' },
  { key: 'action', label: '操作', valueType: 'text', hideable: false },
]
const controlMr = computed(() => controlMrs.value.find((item) => item.mr_id === controlMrId.value) || null)
const link = computed(() => store.preview?.link || {})
const displayContext = computed(() => store.preview?.display_context || {})
const fping = computed(() => store.preview?.fping || {})
const fpingSummary = computed(() => {
  const value = fping.value.summary
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
})
const iperf = computed(() => store.preview?.iperf || {})
const hasPreviewLink = computed(() => Object.values(link.value).some((value) => value !== undefined && value !== null && value !== ''))
const meshRawHasData = computed(() => store.rawFiles.some((item) => item.name === 'mesh_link' && item.exists && item.size_bytes > 0))
const previewWarning = computed(() => store.preview?.available && !hasPreviewLink.value && meshRawHasData.value
  ? (store.preview.message || '主链路原始日志已有数据，但未识别 Active 主链路，请检查 preview parser。')
  : '')
const runtimeRows = computed<OnlineMrRuntimeStatusRow[]>(() => {
  const rawByRelative = new Map(store.rawFiles.map((item) => [item.relative_name, item]))
  const rawByName = new Map(store.rawFiles.map((item) => [item.name, item]))
  const rows: OnlineMrRuntimeStatusRow[] = store.collectors.map((collector) => {
    const raw = rawByRelative.get(collector.raw_file) || rawByName.get(rawSourceByCollector[collector.name] || '')
    return {
      ...collector,
      current_size_bytes: raw?.size_bytes ?? collector.size_bytes,
      recent_growth_at: raw?.modified_at || collector.updated_at,
      action_source: rawSourceByCollector[collector.name] || '',
      row_kind: 'collector' as const,
      issue: runtimeIssue(collector),
    }
  })
  const represented = new Set(rows.map((row) => row.action_source).filter(Boolean))
  for (const raw of store.rawFiles) {
    if (!extraRawRows.has(raw.name) || represented.has(raw.name)) continue
    const health = rawHealth(raw)
    rows.push({
      name: `raw_${raw.name}`,
      label: rawFileLabel(raw.name),
      status: raw.exists ? raw.size_bytes > 0 ? 'running' : 'starting' : 'missing',
      enabled: true,
      raw_file: raw.relative_name,
      exists: raw.exists,
      size_bytes: raw.size_bytes,
      error: '',
      started_at: null,
      ended_at: null,
      updated_at: raw.modified_at,
      health_status: health,
      stale_seconds: staleSeconds(raw.modified_at),
      current_size_bytes: raw.size_bytes,
      recent_growth_at: raw.modified_at,
      action_source: raw.name,
      row_kind: 'raw_file',
      issue: rawIssue(raw, health),
    })
  }
  return rows
})

watch(expanded, (sections) => {
  const logsExpanded = sections.includes('logs')
  store.setRawExpanded(logsExpanded)
  if (logsExpanded) store.setRawSource(rawSource.value)
})
watch(rawSource, (source) => {
  if (expanded.value.includes('logs')) store.setRawSource(source)
})

function field(value: Record<string, unknown>, ...names: string[]): string {
  for (const name of names) {
    const candidate = value[name]
    if (candidate !== undefined && candidate !== null && candidate !== '') return String(candidate)
  }
  return '—'
}

function iperfRateLimit(value: Record<string, unknown>): string {
  if (String(value.protocol || '').toUpperCase() !== 'TCP') return field(value, 'target_bandwidth')
  const candidate = value.target_bandwidth
  if (candidate === undefined || candidate === null || candidate === '' || candidate === 0 || candidate === '0' || candidate === '0M') return '不限速'
  const text = String(candidate)
  return text.endsWith('M') ? `${text.slice(0, -1)} Mbps` : text
}

function numberField(value: Record<string, unknown>, names: string[], suffix: string): string {
  for (const name of names) {
    const candidate = value[name]
    if (candidate !== undefined && candidate !== null && candidate !== '') return `${candidate}${suffix}`
  }
  return '—'
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function collectorStatusLabel(row: OnlineMrCollectorStatus): string {
  if (!row.enabled) return '未启用'
  if (row.health_status === 'stale') return '异常'
  if (row.health_status === 'interrupted') return '采集中断'
  if (row.health_status === 'normal') return '采集中'
  if (row.status.startsWith('failed')) return row.exit_code !== undefined && row.exit_code !== null ? `失败 / Exit ${row.exit_code}` : '失败'
  return ({ starting: '启动中', stopped: '已停止', completed: '已完成', failed: '失败', missing: '无数据' } as Record<string, string>)[row.status] || '等待数据'
}

function runtimeHealthLabel(row: OnlineMrRuntimeStatusRow): string {
  return ({ normal: '正常', stale: '疑似异常', interrupted: '采集中断', unknown: '—' } as Record<string, string>)[row.health_status] || '—'
}

function runtimeIssue(row: OnlineMrCollectorStatus): string {
  if (row.exit_code !== undefined && row.exit_code !== null && row.exit_code !== 0) {
    const detail = row.last_error || row.stderr_tail || '进程异常退出'
    return `FAILED / Exit ${row.exit_code} / ${detail}`
  }
  if (row.error) return row.error
  if (!row.enabled) return '未启用'
  if (row.health_status === 'stale') return '超过 30 秒未增长'
  if (row.health_status === 'interrupted') return '超过 120 秒未增长'
  if (row.status === 'missing') return '尚未生成数据'
  return ''
}

function trafficStatus(value: Record<string, unknown>): string {
  const status = String(value.status || '—')
  const exitCode = value.exit_code
  if (exitCode !== undefined && exitCode !== null && Number(exitCode) !== 0) return `${status} / Exit ${exitCode}`
  const lastData = value.last_data_at
  return lastData ? `${status} / 最后数据 ${String(lastData)}` : status
}

function rawFileLabel(name: string): string {
  return ({
    terminal_monitor: '终端实时日志', mesh_link: '主链路信息', channel_busy: '空口负载', fping_samples: 'fping 样本',
    fping_summary: 'fping 汇总', fping_raw: 'fping 原始输出', iperf_client: 'iPerf 客户端',
    switch_history: '切换历史', collector_output: '采集器输出', wireless_status: '无线状态',
  } as Record<string, string>)[name] || name
}

function rawHealth(raw: OnlineMrRawFile): OnlineMrRuntimeStatusRow['health_status'] {
  if (!store.active || !raw.exists) return 'unknown'
  const seconds = staleSeconds(raw.modified_at)
  if (seconds === null) return 'unknown'
  if (seconds > 120) return 'interrupted'
  if (seconds > 30) return 'stale'
  return 'normal'
}

function rawIssue(raw: OnlineMrRawFile, health: string): string {
  if (!raw.exists) return '尚未生成数据'
  if (health === 'stale') return '超过 30 秒未增长'
  if (health === 'interrupted') return '超过 120 秒未增长'
  return ''
}

function staleSeconds(value: string | null): number | null {
  if (!value) return null
  const timestamp = Date.parse(value.replace(' ', 'T'))
  if (Number.isNaN(timestamp)) return null
  return Math.max(0, (Date.now() - timestamp) / 1000)
}

function ensureLogsOpen(): void {
  if (!expanded.value.includes('logs')) expanded.value = [...expanded.value, 'logs']
}

function showRaw(row: OnlineMrRuntimeStatusRow): void {
  if (row.action_source && !['mesh_link', 'fping_raw'].includes(row.action_source)) rawSource.value = row.action_source
  ensureLogsOpen()
  store.setRawExpanded(true)
  void store.refreshRawTail()
}

function tailText(value: OnlineMrRawTail | null): string {
  return value?.lines.length ? value.lines.join('\n') : value?.message || '暂无数据'
}

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
}

async function loadControlMrs(): Promise<void> {
  try {
    const [summary, page] = await Promise.all([
      getTrainCommunicationSummary(),
      listTrainCommunications({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' }),
    ])
    controlSiteId.value = summary.site_id
    controlMrs.value = page.items.flatMap((train) => train.mrs)
    const requestedMr = typeof route.query.mr_id === 'string' ? route.query.mr_id : ''
    const requestedDevice = typeof route.query.device_id === 'string' ? route.query.device_id : ''
    controlMrId.value = controlMrs.value.find((item) => item.mr_id === requestedMr)?.mr_id
      || controlMrs.value.find((item) => String(item.device_id) === requestedDevice)?.mr_id
      || controlMrId.value
      || controlMrs.value[0]?.mr_id
      || ''
    controlError.value = ''
  } catch (cause) {
    controlError.value = cause instanceof Error ? cause.message : '正式 MR 列表加载失败'
  }
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibility)
  await loadControlMrs()
  store.startPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})
</script>

<template>
  <div class="online-mr-web" v-loading="store.loading">
    <header class="page-heading">
      <div>
        <p class="eyebrow">轨道交通</p>
        <h2>车载 MR 实时收集</h2>
        <p>仅展示当前正在运行的实时采集任务；历史 Session、日志下载和分析报告统一进入“车载 MR 收集分析”。</p>
      </div>
      <el-button :icon="Refresh" @click="store.refreshOverview">刷新当前任务</el-button>
    </header>

    <section class="content-section collection-control">
      <div class="section-heading">
        <div><h3>采集控制</h3><p>从基础资料选择正式 MR；连接凭据由后端设备库受控读取。</p></div>
        <div class="control-selector">
          <el-select v-model="controlMrId" filterable placeholder="选择列车 MR" style="width: 330px">
            <el-option v-for="mr in controlMrs" :key="mr.mr_id" :label="`${mr.train_name} · ${mr.mr_role} · ${mr.mr_name}`" :value="mr.mr_id" />
          </el-select>
          <el-button :icon="Refresh" @click="loadControlMrs">刷新 MR</el-button>
        </div>
      </div>
      <el-alert v-if="controlError" :title="controlError" type="error" :closable="false" show-icon />
      <el-tabs v-if="controlMr && controlSiteId" v-model="executorTab" type="border-card">
        <el-tab-pane label="LOCAL 本地执行" name="local">
          <OnlineMrLocalControl :site-id="controlSiteId" :mr="controlMr" @refresh="store.refreshOverview" />
        </el-tab-pane>
        <el-tab-pane label="AGENT 远程执行" name="agent">
          <OnlineMrAgentControlPanel :site-id="controlSiteId" :mr="controlMr" />
        </el-tab-pane>
      </el-tabs>
      <el-empty v-else description="当前局点没有已登记且绑定设备的 MR" />
    </section>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon />
    <el-empty v-if="!store.current && !store.loading" description="当前无实时采集任务，请选择列车启动采集" class="current-empty" />

    <template v-if="store.current">
      <section class="content-section current-session">
        <div class="section-heading">
          <div><h3>当前 Session</h3><p>{{ store.current.device_name || store.current.mr_name }}</p></div>
          <NcStatusTag :status="store.current.status" />
        </div>
        <el-descriptions :column="4" border>
          <el-descriptions-item label="列车 / MR">{{ store.current.mr_name }}</el-descriptions-item>
          <el-descriptions-item label="Session">{{ store.current.session_id }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ store.current.started_at || '—' }}</el-descriptions-item>
          <el-descriptions-item label="运行时间">{{ (store.current.duration_minutes || 0).toFixed(1) }} 分钟</el-descriptions-item>
          <el-descriptions-item label="Task 状态">{{ store.current.task_status || '—' }}</el-descriptions-item>
          <el-descriptions-item label="采集阶段">{{ store.current.phase || '—' }}</el-descriptions-item>
          <el-descriptions-item label="执行端">{{ store.current.executor_kind || '—' }}</el-descriptions-item>
          <el-descriptions-item label="数据更新时间">{{ store.preview?.updated_at || '—' }}</el-descriptions-item>
        </el-descriptions>
      </section>

      <section class="content-section realtime-core-status">
        <div class="section-heading"><div><h3>实时核心状态</h3><p>无线链路、fping 与 iPerf 使用后端实时快照。</p></div></div>
        <el-alert v-if="previewWarning" :title="previewWarning" type="warning" show-icon :closable="false" />
        <div v-if="store.preview?.available" class="preview-grid">
          <div class="preview-block"><h4>当前无线状态</h4><dl><dt>站点</dt><dd>{{ field(displayContext, 'station', 'site') }}</dd><dt>区间</dt><dd>{{ field(displayContext, 'section') }}</dd><dt>主链路 AP</dt><dd>{{ field(link, 'ap_name', 'master_ap', 'master', 'peer_name', 'resolved_peer_name') }}</dd><dt>AP MAC</dt><dd>{{ field(link, 'ap_mac') }}</dd><dt>Peer MAC</dt><dd>{{ field(link, 'peer_mac') }}</dd><dt>RSSI</dt><dd>{{ numberField(link, ['rssi_dbm'], ' dBm') }}</dd><dt>接口</dt><dd>{{ field(link, 'interface') }}</dd><dt>链路状态</dt><dd>{{ field(link, 'link_state', 'status') }}</dd><dt>在线时长</dt><dd>{{ field(link, 'online_time') }}</dd></dl></div>
          <div class="preview-block"><h4>fping</h4><dl><dt>目标</dt><dd>{{ field(fping, 'target') }}</dd><dt>最新延迟</dt><dd>{{ numberField(fpingSummary, ['last_rtt_ms'], ' ms') }}</dd><dt>丢包</dt><dd>{{ numberField(fpingSummary, ['loss_rate_percent'], '%') }}</dd><dt>平均延迟</dt><dd>{{ numberField(fpingSummary, ['avg_rtt_ms'], ' ms') }}</dd><dt>状态</dt><dd>{{ trafficStatus(fping) }}</dd></dl></div>
          <div class="preview-block"><h4>iPerf 本地回环</h4><dl><dt>目标</dt><dd>{{ field(iperf, 'server_ip') }}</dd><dt>协议</dt><dd>{{ field(iperf, 'protocol') }}</dd><dt>限速</dt><dd>{{ iperfRateLimit(iperf) }}</dd><dt>当前速率</dt><dd>{{ numberField(iperf, ['bitrate_mbps'], ' Mbps') }}</dd><dt>实际平均</dt><dd>{{ numberField(iperf, ['average_bitrate_mbps'], ' Mbps') }}</dd><dt>状态</dt><dd>{{ trafficStatus(iperf) }}</dd></dl></div>
        </div>
        <el-empty v-else description="当前采集尚未产生轻量预览" />
      </section>

      <section class="content-section runtime-status">
        <div class="section-heading"><div><h3>当前采集状态</h3><p>状态、文件大小、最近增长和异常说明统一显示；超过 30 秒标记疑似异常，超过 120 秒标记采集中断。</p></div></div>
        <NcDataTable
          table-id="online-mr-collectors"
          route-key="/rail-transit/online-mr"
          :preference-scope="store.current.session_id"
          :data="runtimeRows"
          :columns="collectorColumns"
          row-key="name"
          max-height="420"
          empty-text="采集项尚未初始化"
        >
          <template #cell-action="{ row }">
            <el-button v-if="row.action_source" link type="primary" size="small" @click="showRaw(row)">查看日志</el-button>
            <span v-else>—</span>
          </template>
        </NcDataTable>
      </section>

      <section class="content-section runtime-log-viewer">
        <div class="section-heading"><div><h3>原始日志动态查看</h3><p>主链路和 fping v5 原始输出固定并列 tail；其他日志可单独切换查看。</p></div></div>
        <el-collapse v-model="expanded" class="raw-log-collapse">
          <el-collapse-item title="主链路 + fping 实时对照" name="logs">
            <div class="raw-compare-grid">
              <div class="raw-panel">
                <div class="raw-panel-heading"><h4>主链路原始日志</h4><el-button link type="primary" @click="store.refreshRawTail">刷新</el-button></div>
                <pre class="raw-output">{{ tailText(store.meshRawTail) }}</pre>
              </div>
              <div class="raw-panel">
                <div class="raw-panel-heading"><h4>fping v5 原始输出</h4><el-button link type="primary" @click="store.refreshRawTail">刷新</el-button></div>
                <pre class="raw-output">{{ tailText(store.fpingRawTail) }}</pre>
              </div>
            </div>
            <div class="other-log-viewer">
              <el-select v-model="rawSource" data-testid="raw-source" style="width: 240px">
                <el-option v-for="item in otherRawSourceOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <pre class="raw-output other-raw-output">{{ tailText(store.otherRawTail || store.rawTail) }}</pre>
            </div>
          </el-collapse-item>
        </el-collapse>
      </section>

    </template>
  </div>
</template>

<style scoped>
.online-mr-web { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.page-heading,.section-heading,.control-selector { display: flex; align-items: center; gap: 12px; }
.page-heading,.section-heading { justify-content: space-between; }
.page-heading h2,.section-heading h3 { margin: 0 0 4px; }
.page-heading p,.section-heading p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; }
.content-section { padding: 16px 0; border-top: 1px solid var(--el-border-color-light); }
.collection-control { padding-top: 0; border-top: 0; }
.collection-control :deep(.el-tabs) { margin-top: 12px; }
.current-empty { min-height: 220px; border-top: 1px solid var(--el-border-color-light); }
.preview-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; margin-top: 12px; }
.preview-block { padding: 14px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-fill-color-extra-light); }
.preview-block h4 { margin: 0 0 10px; }
.preview-block dl { display: grid; grid-template-columns: max-content minmax(0,1fr); gap: 7px 12px; margin: 0; }
.preview-block dt { color: var(--el-text-color-secondary); }
.preview-block dd { margin: 0; overflow-wrap: anywhere; text-align: right; }
.raw-log-collapse { margin-top: 12px; }
.raw-compare-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; min-width: 0; }
.raw-panel { min-width: 0; padding: 12px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-fill-color-extra-light); }
.raw-panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.raw-panel-heading h4 { margin: 0; font-size: 14px; }
.other-log-viewer { margin-top: 12px; }
.raw-output { min-height: 140px; max-height: 260px; margin: 10px 0 0; padding: 12px; overflow: auto; background: var(--el-fill-color-darker); color: var(--el-text-color-primary); white-space: pre-wrap; }
.other-raw-output { max-height: 220px; }
@media (max-width: 1100px) { .preview-grid,.raw-compare-grid { grid-template-columns: 1fr; }.page-heading,.section-heading { align-items: flex-start; flex-direction: column; }.control-selector { flex-wrap: wrap; } }
</style>
