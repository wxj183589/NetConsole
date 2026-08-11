<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  getWirelessDashboard,
  getWirelessDashboardAgents,
  getWirelessDashboardAlerts,
  getWirelessDashboardAnalysis,
  getWirelessDashboardFreshness,
  getWirelessDashboardInfrastructure,
  getWirelessDashboardRecentOperations,
  getWirelessDashboardSummary,
  getWirelessDashboardTrains,
} from '../../api/wirelessDashboard'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcColumnValueType, NcTableColumn } from '../../components/table/NcTableColumn'
import type { AcMeshLinkRecord } from '../../types/acMeshLink'
import type { AgentItem } from '../../types/agent'
import type { MrCommunicationStatus, TrainCommunicationRow } from '../../types/trainCommunication'
import type {
  WirelessDashboard,
  WirelessDashboardAlert,
  WirelessDashboardFreshnessItem,
} from '../../types/wirelessDashboard'

const router = useRouter()
const data = ref<WirelessDashboard | null>(null)
const loading = ref(false)
const error = ref('')
const failureCount = ref(0)
const lastRefreshAt = ref('')
const due = { infrastructure: 0, mesh: 0, alerts: 0, freshness: 0, analysis: 0, agents: 0 }
let timer: ReturnType<typeof setTimeout> | undefined

function dashboardColumn<Row extends object>(
  key: string,
  label: string,
  valueType: NcColumnValueType = 'text',
  options: Partial<NcTableColumn<Row>> = {},
): NcTableColumn<Row> {
  return { key, label, valueType, ...options }
}

const meshLinkColumns: NcTableColumn<AcMeshLinkRecord>[] = [
  dashboardColumn('mr_name', '车载 MR', 'name', { minWidth: 125 }),
  dashboardColumn('peer_ap_name', '当前轨旁 AP', 'name', { minWidth: 145 }),
  dashboardColumn('mesh_interface', 'Mesh 接口', 'port', { width: 100 }),
  dashboardColumn('rssi', 'RSSI', 'number', { width: 85 }),
  dashboardColumn('location', '站点 / 区间', 'text', { minWidth: 145 }),
]

const trainColumns: NcTableColumn<TrainCommunicationRow>[] = [
  dashboardColumn('train_no', '列车', 'name', { width: 70 }),
  dashboardColumn('mr_ct', 'MR-CT', 'status', { minWidth: 140 }),
  dashboardColumn('mr_tc', 'MR-TC', 'status', { minWidth: 140 }),
  dashboardColumn('communication_status', '状态', 'status', { width: 90, cellKind: 'tag' }),
]

const alertColumns: NcTableColumn<WirelessDashboardAlert>[] = [
  dashboardColumn('severity', '级别', 'status', { width: 78, cellKind: 'tag' }),
  dashboardColumn('title', '对象', 'name', { minWidth: 150 }),
  dashboardColumn('message', '已有结论', 'description', { minWidth: 250, align: 'left', alignmentReason: 'long-text' }),
  dashboardColumn('actions', '操作', 'actions', { width: 70, cellKind: 'actions', actionLabels: ['详情'] }),
]

const freshnessColumns: NcTableColumn<WirelessDashboardFreshnessItem>[] = [
  dashboardColumn('label', '数据源', 'name', { minWidth: 145 }),
  dashboardColumn('status', '状态', 'status', { width: 95, cellKind: 'tag' }),
  dashboardColumn('updated_at', '更新时间', 'datetime', { minWidth: 170 }),
  dashboardColumn('age_seconds', '数据年龄', 'duration', { width: 100 }),
]

const agentColumns: NcTableColumn<AgentItem>[] = [
  dashboardColumn('name', 'Agent', 'name', { minWidth: 140 }),
  dashboardColumn('base_url', '地址', 'description', { minWidth: 180, align: 'left', alignmentReason: 'path' }),
  dashboardColumn('status', '状态', 'status', { width: 95, cellKind: 'tag' }),
  dashboardColumn('version', '版本', 'text', { width: 120 }),
  dashboardColumn('last_checked_at', '最后检查', 'datetime', { minWidth: 175 }),
  dashboardColumn('last_error_message', '错误摘要', 'error', { minWidth: 180, align: 'left', alignmentReason: 'long-text' }),
]

function metric(value: number | null | undefined): number | string {
  return data.value ? (value ?? 0) : '—'
}

const summaryCards = computed(() => {
  const s = data.value?.summary
  return [
    ['FIT-AP', metric(s?.ap_total), ''], ['在线 AP', metric(s?.online_aps), 'good'], ['离线 AP', metric(s?.offline_aps), 'warning'],
    ['未认证 AP', metric(s?.unauthenticated_aps), 'warning'], ['光衰异常', metric(s?.optical_anomalies), 'danger'],
    ['列车 / MR', s ? `${s.registered_trains} / ${s.registered_mrs}` : '—', ''],
    ['MR 在线 / 离线 / 过期', s ? `${s.online_mrs} / ${s.offline_mrs} / ${s.stale_mrs}` : '—', ''],
    ['运行中采集', metric(s?.active_online_mr_sessions), 'good'], ['Agent 在线', s ? `${s.online_agents} / ${s.agent_total}` : '—', ''],
    ['运行中任务', metric(s?.running_tasks), ''], ['Mesh 分析会话', metric(s?.mesh_analysis_sessions), ''],
    ['告警', s ? `${s.critical_alerts} / ${s.warning_alerts}` : '—', 'danger'],
  ] as const
})
const active = computed(() => (data.value?.summary.active_online_mr_sessions ?? 0) > 0 || (data.value?.summary.running_tasks ?? 0) > 0)

function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatTime(value: string | null | undefined): string { return value ? value.replace('T', ' ').replace(/Z$/, '') : '无数据' }
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const normalized = value.toLowerCase()
  if (['online', 'normal', 'fresh', 'available', 'completed'].includes(normalized)) return 'success'
  if (['critical', 'failed', 'error'].includes(normalized)) return 'danger'
  if (['warning', 'stale', 'offline'].includes(normalized)) return 'warning'
  return 'info'
}
function mrRole(row: { mrs: MrCommunicationStatus[] }, role: string): MrCommunicationStatus | undefined {
  return row.mrs.find((item) => item.mr_role.toUpperCase() === role)
}
function schedule(): void {
  clearTimeout(timer)
  if (document.visibilityState !== 'visible') return
  const interval = failureCount.value >= 3 ? 30_000 : active.value ? 2_000 : 10_000
  timer = setTimeout(() => void refreshSections(), interval)
}
async function initialLoad(): Promise<void> {
  if (loading.value) return
  loading.value = true
  try {
    data.value = await getWirelessDashboard()
    error.value = ''
    failureCount.value = 0
    lastRefreshAt.value = new Date().toISOString()
    const now = Date.now()
    due.infrastructure = now + 30_000; due.mesh = now + 5_000; due.alerts = now + 5_000; due.freshness = now + 5_000; due.analysis = now + 30_000; due.agents = now + 10_000
  } catch (reason) {
    failureCount.value += 1
    error.value = reason instanceof Error ? reason.message : '无线看板加载失败'
  } finally {
    loading.value = false
    schedule()
  }
}
async function refreshSections(): Promise<void> {
  if (loading.value || document.visibilityState !== 'visible' || !data.value) return schedule()
  loading.value = true
  const now = Date.now()
  try {
    const requests: Array<{ label: string; request: Promise<void> }> = [
      { label: '汇总指标', request: getWirelessDashboardSummary().then((value) => { data.value!.summary = value }) },
      { label: '列车通信', request: getWirelessDashboardTrains().then((value) => { data.value!.trains = value }) },
      { label: '最近任务与会话', request: getWirelessDashboardRecentOperations().then((value) => { data.value!.recent_operations = value }) },
    ]
    if (now >= due.infrastructure || now >= due.mesh) requests.push({ label: '基础设施与 Mesh-Link', request: getWirelessDashboardInfrastructure().then((value) => {
      if (now >= due.infrastructure) { data.value!.infrastructure.ac = value.ac; data.value!.infrastructure.optical_anomalies = value.optical_anomalies; due.infrastructure = now + 30_000 }
      if (now >= due.mesh) { data.value!.infrastructure.mesh_link = value.mesh_link; data.value!.infrastructure.current_links = value.current_links; due.mesh = now + 5_000 }
    }) })
    if (now >= due.alerts) requests.push({ label: '告警', request: getWirelessDashboardAlerts().then((value) => { data.value!.alerts = value; due.alerts = now + 5_000 }) })
    if (now >= due.freshness) requests.push({ label: '数据时效', request: getWirelessDashboardFreshness().then((value) => { data.value!.freshness = value; due.freshness = now + 5_000 }) })
    if (now >= due.analysis) requests.push({ label: 'Mesh 离线分析', request: getWirelessDashboardAnalysis().then((value) => { data.value!.analysis = value; due.analysis = now + 30_000 }) })
    if (now >= due.agents) requests.push({ label: 'Agent 状态', request: getWirelessDashboardAgents().then((value) => { data.value!.agents = value; due.agents = now + 10_000 }) })
    const results = await Promise.allSettled(requests.map((item) => item.request))
    const failed = results.flatMap((result, index) => result.status === 'rejected'
      ? [`${requests[index]!.label}（${result.reason instanceof Error ? result.reason.message : '未知错误'}）`]
      : [])
    const successCount = results.length - failed.length
    if (successCount) {
      failureCount.value = 0
      lastRefreshAt.value = new Date().toISOString()
    } else {
      failureCount.value += 1
    }
    error.value = failed.length
      ? `${successCount ? '部分看板数据刷新失败' : '看板刷新失败'}，已保留最后成功数据。失败项目：${failed.join('、')}`
      : ''
  } finally {
    loading.value = false
    schedule()
  }
}
function handleVisibility(): void {
  clearTimeout(timer)
  if (document.visibilityState === 'visible') void refreshSections()
}
function go(path: string): void { if (path) void router.push(path) }

onMounted(() => { document.addEventListener('visibilitychange', handleVisibility); void initialLoad() })
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', handleVisibility); clearTimeout(timer) })
</script>

<template>
  <section class="dashboard-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · READ ONLY</p><h1>轨道交通无线综合看板</h1><p>聚合轨旁 AP、AC Mesh-Link、在线列车通信、任务、Agent 与 Mesh 离线分析；所有结论均来自既有只读服务。</p></div>
      <div class="heading-actions"><el-tag type="info">只读聚合</el-tag><el-button :loading="loading" @click="initialLoad">刷新</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" />
    <div class="source-strip"><span>局点：{{ data?.summary.site_name || '无数据' }}</span><span>数据版本：{{ data?.summary.data_version || '无数据' }}</span><span>最近刷新：{{ formatTime(lastRefreshAt) }}</span><span>{{ active ? '活动态 2 秒' : '静态 10 秒' }} · 连续失败 3 次后 30 秒</span></div>

    <div class="summary-grid">
      <article v-for="card in summaryCards" :key="card[0]" :class="['metric-card', card[2]]"><span>{{ card[0] }}</span><strong>{{ card[1] }}</strong></article>
    </div>

    <div class="two-columns">
      <article class="panel">
        <div class="panel-title"><div><h2>基础设施状态</h2><p>FIT-AP、光衰与最新 Mesh-Link 快照</p></div><el-button link type="primary" @click="go('/ac-management')">查看 AC 管理</el-button></div>
        <div class="mini-grid">
          <span>AP 在线 <b>{{ metric(data?.infrastructure.ac.online_aps) }}</b></span><span>AP 离线 <b>{{ metric(data?.infrastructure.ac.offline_aps) }}</b></span>
          <span>光衰异常 <b>{{ metric(data?.infrastructure.ac.optical_anomalies) }}</b></span><span>活动链路 <b>{{ metric(data?.infrastructure.mesh_link.active_links) }}</b></span>
        </div>
        <NcDataTable table-id="rail-wireless-dashboard-mesh-links" route-key="/rail-transit/wireless-dashboard" :data="data?.infrastructure.current_links || []" :columns="meshLinkColumns" :show-column-settings="false" :stripe="false" size="small" max-height="285" empty-text="暂无 Mesh-Link 快照">
          <template #cell-rssi="{ row }">{{ display(row.rssi, ' dBm') }}</template>
          <template #cell-location="{ row }">{{ [row.station, row.section].filter(Boolean).join(' / ') || '无数据' }}</template>
        </NcDataTable>
      </article>

      <article class="panel">
        <div class="panel-title"><div><h2>在线列车通信</h2><p>CT / TC 独立展示，不合并两端状态</p></div><el-button link type="primary" @click="go('/rail-transit/train-communication')">查看全部列车</el-button></div>
        <NcDataTable table-id="rail-wireless-dashboard-trains" route-key="/rail-transit/wireless-dashboard" :data="data?.trains.items || []" :columns="trainColumns" :show-column-settings="false" :stripe="false" size="small" max-height="355" empty-text="暂无列车资料">
          <template #cell-mr_ct="{ row }"><template v-if="mrRole(row, 'CT')"><el-tag size="small" :type="statusType(mrRole(row, 'CT')!.communication_status)">{{ mrRole(row, 'CT')!.communication_status }}</el-tag> {{ mrRole(row, 'CT')!.peer_ap_name || '无 Peer AP' }}</template><span v-else>无数据</span></template>
          <template #cell-mr_tc="{ row }"><template v-if="mrRole(row, 'TC')"><el-tag size="small" :type="statusType(mrRole(row, 'TC')!.communication_status)">{{ mrRole(row, 'TC')!.communication_status }}</el-tag> {{ mrRole(row, 'TC')!.peer_ap_name || '无 Peer AP' }}</template><span v-else>无数据</span></template>
          <template #cell-communication_status="{ row }"><el-tag :type="statusType(row.communication_status)">{{ row.communication_status }}</el-tag></template>
        </NcDataTable>
      </article>
    </div>

    <div class="two-columns">
      <article class="panel">
        <div class="panel-title"><div><h2>告警与异常</h2><p>仅复用已有状态和分析结果，不在浏览器推断</p></div><span>{{ data ? `${data.alerts.total} 条` : '—' }}</span></div>
        <NcDataTable table-id="rail-wireless-dashboard-alerts" route-key="/rail-transit/wireless-dashboard" :data="data?.alerts.items || []" :columns="alertColumns" :show-column-settings="false" :stripe="false" size="small" max-height="350" empty-text="当前没有既有告警">
          <template #cell-severity="{ row }"><el-tag :type="statusType(row.severity)">{{ row.severity }}</el-tag></template>
          <template #cell-actions="{ row }"><el-button v-if="row.detail_path" link type="primary" @click="go(row.detail_path)">详情</el-button></template>
        </NcDataTable>
      </article>
      <article class="panel">
        <div class="panel-title"><div><h2>数据时效</h2><p>展示各数据源自己的状态和更新时间</p></div></div>
        <NcDataTable table-id="rail-wireless-dashboard-freshness" route-key="/rail-transit/wireless-dashboard" :data="data?.freshness.items || []" :columns="freshnessColumns" :show-column-settings="false" :stripe="false" size="small" max-height="350">
          <template #cell-status="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template>
          <template #cell-updated_at="{ row }">{{ formatTime(row.updated_at) }}</template>
          <template #cell-age_seconds="{ row }">{{ row.age_seconds === null ? '无数据' : `${row.age_seconds}s` }}</template>
        </NcDataTable>
      </article>
    </div>

    <div class="three-columns">
      <article class="panel"><div class="panel-title"><div><h2>最近任务</h2><p>任务中心现有记录</p></div><el-button link type="primary" @click="go('/tasks')">任务中心</el-button></div><ul class="record-list"><li v-for="task in data?.recent_operations.tasks.slice(0, 8)" :key="task.id" @click="go(`/tasks?task=${task.id}`)"><span>{{ task.name }}</span><el-tag size="small" :type="statusType(task.status)">{{ task.status }}</el-tag><small>{{ formatTime(task.updated_time) }}</small></li></ul><el-empty v-if="!data?.recent_operations.tasks.length" description="暂无任务" :image-size="50" /></article>
      <article class="panel"><div class="panel-title"><div><h2>最近采集会话</h2><p>LOCAL / Agent 导入会话</p></div><el-button link type="primary" @click="go('/rail-transit/online-mr')">实时展示</el-button></div><ul class="record-list"><li v-for="session in data?.recent_operations.sessions.slice(0, 8)" :key="session.session_id" @click="go(`/rail-transit/online-mr?session_id=${session.session_id}`)"><span>{{ session.mr_name || session.device_name }}</span><el-tag size="small" :type="statusType(session.status)">{{ session.status }}</el-tag><small>{{ formatTime(session.started_at) }}</small></li></ul><el-empty v-if="!data?.recent_operations.sessions.length" description="暂无会话" :image-size="50" /></article>
      <article class="panel"><div class="panel-title"><div><h2>Mesh 离线分析</h2><p>既有解析结果摘要</p></div><el-button link type="primary" @click="go('/rail-transit/mesh-analysis')">分析详情</el-button></div><div class="analysis-grid"><span>会话 <b>{{ metric(data?.analysis.summary.session_count) }}</b></span><span>链路记录 <b>{{ metric(data?.analysis.summary.link_record_count) }}</b></span><span>切换 <b>{{ metric(data?.analysis.summary.switch_event_count) }}</b></span><span>短时建链 <b>{{ metric(data?.analysis.summary.short_link_count) }}</b></span><span>乒乓 <b>{{ metric(data?.analysis.summary.pingpong_count) }}</b></span><span>未匹配 AP <b>{{ metric(data?.analysis.summary.unmatched_ap_count) }}</b></span></div></article>
    </div>

    <article class="panel"><div class="panel-title"><div><h2>Agent 状态</h2><p>仅使用 Controller 已缓存状态，不主动连接 Agent</p></div><el-button link type="primary" @click="go('/agents')">Agent 控制中心</el-button></div><NcDataTable table-id="rail-wireless-dashboard-agents" route-key="/rail-transit/wireless-dashboard" :data="data?.agents.items || []" :columns="agentColumns" :show-column-settings="false" :stripe="false" size="small" empty-text="当前局点未登记 Agent"><template #cell-status="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template><template #cell-last_checked_at="{ row }">{{ formatTime(row.last_checked_at) }}</template></NcDataTable></article>
  </section>
</template>

<style scoped>
.dashboard-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.heading-actions,.source-strip,.panel-title{display:flex;align-items:center;gap:12px}.page-heading,.panel-title{justify-content:space-between}.page-heading h1,.panel-title h2{margin:2px 0 6px}.page-heading p,.panel-title p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.source-strip{flex-wrap:wrap;padding:10px 14px;background:var(--el-fill-color-light);border-radius:10px;font-size:13px}.summary-grid{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px}.metric-card,.panel{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--el-text-color-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:23px}.metric-card.good strong{color:var(--el-color-success)}.metric-card.warning strong{color:var(--el-color-warning)}.metric-card.danger strong{color:var(--el-color-danger)}.two-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.three-columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.panel{padding:14px 16px;overflow:hidden}.panel-title{margin-bottom:12px}.mini-grid,.analysis-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px}.mini-grid span,.analysis-grid span{padding:9px;background:var(--el-fill-color-light);border-radius:8px;color:var(--el-text-color-secondary)}.mini-grid b,.analysis-grid b{display:block;margin-top:4px;color:var(--el-text-color-primary);font-size:18px}.record-list{list-style:none;margin:0;padding:0}.record-list li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 8px;padding:9px 0;border-bottom:1px solid var(--el-border-color-lighter);cursor:pointer}.record-list li span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.record-list small{grid-column:1/-1;color:var(--el-text-color-secondary)}@media(max-width:1400px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}.three-columns{grid-template-columns:1fr 1fr}.three-columns .panel:last-child{grid-column:1/-1}}@media(max-width:1000px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.two-columns,.three-columns{grid-template-columns:1fr}.three-columns .panel:last-child{grid-column:auto}.page-heading{align-items:flex-start;flex-direction:column}.mini-grid,.analysis-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
