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
import type { OnlineMrCollectorStatus, OnlineMrRawFile } from '../../types/onlineMr'
import type { MrCommunicationStatus } from '../../types/trainCommunication'

const store = useOnlineMrStore()
const route = useRoute()
const expanded = ref<string[]>([])
const rawSource = ref('mesh_link')
const controlMrs = ref<MrCommunicationStatus[]>([])
const controlMrId = ref('')
const controlError = ref('')
const controlSiteId = ref('')
const executorTab = ref('local')

const collectorColumns: NcTableColumn<OnlineMrCollectorStatus>[] = [
  { key: 'label', label: '采集项', valueType: 'name' },
  { key: 'health_status', label: '状态', valueType: 'status', cellKind: 'tag', displayValue: collectorStatusLabel },
  { key: 'size_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'updated_at', label: '更新时间', valueType: 'datetime' },
]
const rawFileColumns: NcTableColumn<OnlineMrRawFile>[] = [
  { key: 'name', label: '采集文件', valueType: 'name', displayValue: (row) => rawFileLabel(row.name) },
  { key: 'size_bytes', label: '当前大小', valueType: 'number', displayValue: (row) => formatBytes(row.size_bytes) },
  { key: 'modified_at', label: '最近增长', valueType: 'datetime' },
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
  return ({ starting: '启动中', stopped: '已停止', completed: '已完成', failed: '失败', missing: '无数据' } as Record<string, string>)[row.status] || '等待数据'
}

function rawFileLabel(name: string): string {
  return ({
    terminal_monitor: '终端实时日志', mesh_link: '主链路信息', channel_busy: '空口负载', fping_samples: 'fping 样本',
    fping_summary: 'fping 汇总', fping_raw: 'fping 原始输出', iperf_client: 'iPerf 客户端',
    switch_history: '切换历史', collector_output: '采集器输出', wireless_status: '无线状态',
  } as Record<string, string>)[name] || name
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

      <div class="runtime-grid">
        <section class="content-section runtime-status">
          <div class="section-heading"><div><h3>当前采集状态</h3><p>更新时间超过 30 秒标记异常，超过 120 秒标记采集中断。</p></div></div>
          <NcDataTable
            table-id="online-mr-collectors"
            route-key="/rail-transit/online-mr"
            :preference-scope="store.current.session_id"
            :data="store.collectors"
            :columns="collectorColumns"
            max-height="360"
            empty-text="采集项尚未初始化"
          />
        </section>

        <section class="content-section runtime-log-growth">
          <div class="section-heading"><div><h3>当前日志增长情况</h3><p>仅显示本次活动 Session 的文件大小和最近增长时间。</p></div></div>
          <el-collapse v-model="expanded" class="log-growth-collapse">
            <el-collapse-item title="文件增长明细" name="growth">
              <NcDataTable table-id="online-mr-raw-growth" route-key="/rail-transit/online-mr" :preference-scope="store.current.session_id" :data="store.rawFiles" :columns="rawFileColumns" max-height="320" empty-text="尚未生成采集文件" />
            </el-collapse-item>
            <el-collapse-item title="原始日志动态查看" name="logs">
              <el-select v-model="rawSource" data-testid="raw-source" style="width: 240px">
                <el-option label="采集器输出" value="collector_output" />
                <el-option label="终端实时日志" value="terminal_monitor" />
                <el-option label="主链路" value="mesh_link" />
                <el-option label="无线状态" value="wireless_status" />
                <el-option label="空口负载" value="channel_busy" />
                <el-option label="iPerf 客户端" value="iperf_client" />
                <el-option label="fping v5 原始输出" value="fping_raw" />
              </el-select>
              <pre class="raw-output">{{ store.rawTail?.lines.join('\n') || '暂无数据' }}</pre>
            </el-collapse-item>
          </el-collapse>
        </section>
      </div>

      <section class="content-section">
        <div class="section-heading"><div><h3>轻量实时预览</h3><p>每 5 秒读取最新快照，不扫描完整原始日志。</p></div></div>
        <div v-if="store.preview?.available" class="preview-grid">
          <div class="preview-block"><h4>当前无线状态</h4><dl><dt>站点</dt><dd>{{ field(displayContext, 'station', 'site') }}</dd><dt>区间</dt><dd>{{ field(displayContext, 'section') }}</dd><dt>主链路</dt><dd>{{ field(link, 'master', 'peer_name', 'resolved_peer_name') }}</dd><dt>RSSI</dt><dd>{{ numberField(link, ['rssi_dbm', 'local_signal_dbm', 'local_rssi_db'], ' dBm') }}</dd><dt>Peer MAC</dt><dd>{{ field(link, 'peer_mac') }}</dd></dl></div>
          <div class="preview-block"><h4>fping</h4><dl><dt>目标</dt><dd>{{ field(fping, 'target') }}</dd><dt>最新延迟</dt><dd>{{ numberField(fpingSummary, ['last_rtt_ms'], ' ms') }}</dd><dt>丢包</dt><dd>{{ numberField(fpingSummary, ['loss_rate_percent'], '%') }}</dd><dt>平均延迟</dt><dd>{{ numberField(fpingSummary, ['avg_rtt_ms'], ' ms') }}</dd><dt>状态</dt><dd>{{ field(fping, 'status') }}</dd></dl></div>
          <div class="preview-block"><h4>iPerf 本地回环</h4><dl><dt>目标</dt><dd>{{ field(iperf, 'server_ip') }}</dd><dt>协议</dt><dd>{{ field(iperf, 'protocol') }}</dd><dt>限速</dt><dd>{{ field(iperf, 'target_bandwidth') }}</dd><dt>当前速率</dt><dd>{{ numberField(iperf, ['bitrate_mbps'], ' Mbps') }}</dd><dt>状态</dt><dd>{{ field(iperf, 'status') }}</dd></dl></div>
        </div>
        <el-empty v-else description="当前采集尚未产生轻量预览" />
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
.runtime-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 20px; min-width: 0; }
.runtime-grid .content-section { min-width: 0; }
.preview-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px; margin-top: 12px; }
.preview-block { padding: 14px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-fill-color-extra-light); }
.preview-block h4 { margin: 0 0 10px; }
.preview-block dl { display: grid; grid-template-columns: max-content minmax(0,1fr); gap: 7px 12px; margin: 0; }
.preview-block dt { color: var(--el-text-color-secondary); }
.preview-block dd { margin: 0; overflow-wrap: anywhere; text-align: right; }
.log-growth-collapse { margin-top: 12px; }
.raw-output { min-height: 160px; max-height: 360px; margin: 12px 0 0; padding: 12px; overflow: auto; background: var(--el-fill-color-darker); color: var(--el-text-color-primary); white-space: pre-wrap; }
@media (max-width: 1100px) { .runtime-grid,.preview-grid { grid-template-columns: 1fr; }.page-heading,.section-heading { align-items: flex-start; flex-direction: column; }.control-selector { flex-wrap: wrap; } }
</style>
