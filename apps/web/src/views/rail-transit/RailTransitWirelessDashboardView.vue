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
import type { WirelessDashboard } from '../../types/wirelessDashboard'
import type { MrCommunicationStatus } from '../../types/trainCommunication'

const router = useRouter()
const data = ref<WirelessDashboard | null>(null)
const loading = ref(false)
const error = ref('')
const failureCount = ref(0)
const lastRefreshAt = ref('')
const due = { infrastructure: 0, mesh: 0, alerts: 0, freshness: 0, analysis: 0, agents: 0 }
let timer: ReturnType<typeof setTimeout> | undefined

const summaryCards = computed(() => {
  const s = data.value?.summary
  return [
    ['FIT-AP', s?.ap_total ?? 0, ''], ['在线 AP', s?.online_aps ?? 0, 'good'], ['离线 AP', s?.offline_aps ?? 0, 'warning'],
    ['未认证 AP', s?.unauthenticated_aps ?? 0, 'warning'], ['光衰异常', s?.optical_anomalies ?? 0, 'danger'],
    ['列车 / MR', `${s?.registered_trains ?? 0} / ${s?.registered_mrs ?? 0}`, ''],
    ['MR 在线 / 离线 / 过期', `${s?.online_mrs ?? 0} / ${s?.offline_mrs ?? 0} / ${s?.stale_mrs ?? 0}`, ''],
    ['运行中采集', s?.active_online_mr_sessions ?? 0, 'good'], ['Agent 在线', `${s?.online_agents ?? 0} / ${s?.agent_total ?? 0}`, ''],
    ['运行中任务', s?.running_tasks ?? 0, ''], ['Mesh 分析会话', s?.mesh_analysis_sessions ?? 0, ''],
    ['告警', `${s?.critical_alerts ?? 0} / ${s?.warning_alerts ?? 0}`, 'danger'],
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
    const core = await Promise.all([
      getWirelessDashboardSummary(), getWirelessDashboardTrains(), getWirelessDashboardRecentOperations(),
    ])
    data.value.summary = core[0]; data.value.trains = core[1]; data.value.recent_operations = core[2]
    const optional: Promise<void>[] = []
    if (now >= due.infrastructure || now >= due.mesh) optional.push(getWirelessDashboardInfrastructure().then((value) => {
      if (now >= due.infrastructure) { data.value!.infrastructure.ac = value.ac; data.value!.infrastructure.optical_anomalies = value.optical_anomalies; due.infrastructure = now + 30_000 }
      if (now >= due.mesh) { data.value!.infrastructure.mesh_link = value.mesh_link; data.value!.infrastructure.current_links = value.current_links; due.mesh = now + 5_000 }
    }))
    if (now >= due.alerts) optional.push(getWirelessDashboardAlerts().then((value) => { data.value!.alerts = value; due.alerts = now + 5_000 }))
    if (now >= due.freshness) optional.push(getWirelessDashboardFreshness().then((value) => { data.value!.freshness = value; due.freshness = now + 5_000 }))
    if (now >= due.analysis) optional.push(getWirelessDashboardAnalysis().then((value) => { data.value!.analysis = value; due.analysis = now + 30_000 }))
    if (now >= due.agents) optional.push(getWirelessDashboardAgents().then((value) => { data.value!.agents = value; due.agents = now + 10_000 }))
    await Promise.all(optional)
    failureCount.value = 0; error.value = ''; lastRefreshAt.value = new Date().toISOString()
  } catch (reason) {
    failureCount.value += 1
    error.value = `刷新失败，保留上次数据：${reason instanceof Error ? reason.message : '未知错误'}`
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
          <span>AP 在线 <b>{{ data?.infrastructure.ac.online_aps ?? 0 }}</b></span><span>AP 离线 <b>{{ data?.infrastructure.ac.offline_aps ?? 0 }}</b></span>
          <span>光衰异常 <b>{{ data?.infrastructure.ac.optical_anomalies ?? 0 }}</b></span><span>活动链路 <b>{{ data?.infrastructure.mesh_link.active_links ?? 0 }}</b></span>
        </div>
        <el-table :data="data?.infrastructure.current_links || []" size="small" max-height="285" empty-text="暂无 Mesh-Link 快照">
          <el-table-column prop="mr_name" label="车载 MR" min-width="125" /><el-table-column prop="peer_ap_name" label="当前轨旁 AP" min-width="145" />
          <el-table-column prop="mesh_interface" label="Mesh 接口" width="100" /><el-table-column label="RSSI" width="85"><template #default="{ row }">{{ display(row.rssi, ' dBm') }}</template></el-table-column>
          <el-table-column label="站点 / 区间" min-width="145"><template #default="{ row }">{{ [row.station, row.section].filter(Boolean).join(' / ') || '无数据' }}</template></el-table-column>
        </el-table>
      </article>

      <article class="panel">
        <div class="panel-title"><div><h2>在线列车通信</h2><p>CT / TC 独立展示，不合并两端状态</p></div><el-button link type="primary" @click="go('/rail-transit/train-communication')">查看全部列车</el-button></div>
        <el-table :data="data?.trains.items || []" size="small" max-height="355" empty-text="暂无列车资料">
          <el-table-column prop="train_no" label="列车" width="70" />
          <el-table-column label="MR-CT" min-width="140"><template #default="{ row }"><template v-if="mrRole(row, 'CT')"><el-tag size="small" :type="statusType(mrRole(row, 'CT')!.communication_status)">{{ mrRole(row, 'CT')!.communication_status }}</el-tag> {{ mrRole(row, 'CT')!.peer_ap_name || '无 Peer AP' }}</template><span v-else>无数据</span></template></el-table-column>
          <el-table-column label="MR-TC" min-width="140"><template #default="{ row }"><template v-if="mrRole(row, 'TC')"><el-tag size="small" :type="statusType(mrRole(row, 'TC')!.communication_status)">{{ mrRole(row, 'TC')!.communication_status }}</el-tag> {{ mrRole(row, 'TC')!.peer_ap_name || '无 Peer AP' }}</template><span v-else>无数据</span></template></el-table-column>
          <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusType(row.communication_status)">{{ row.communication_status }}</el-tag></template></el-table-column>
        </el-table>
      </article>
    </div>

    <div class="two-columns">
      <article class="panel">
        <div class="panel-title"><div><h2>告警与异常</h2><p>仅复用已有状态和分析结果，不在浏览器推断</p></div><span>{{ data?.alerts.total ?? 0 }} 条</span></div>
        <el-table :data="data?.alerts.items || []" size="small" max-height="350" empty-text="当前没有既有告警">
          <el-table-column label="级别" width="78"><template #default="{ row }"><el-tag :type="statusType(row.severity)">{{ row.severity }}</el-tag></template></el-table-column>
          <el-table-column prop="title" label="对象" min-width="150" /><el-table-column prop="message" label="已有结论" min-width="250" show-overflow-tooltip />
          <el-table-column label="操作" width="70"><template #default="{ row }"><el-button v-if="row.detail_path" link type="primary" @click="go(row.detail_path)">详情</el-button></template></el-table-column>
        </el-table>
      </article>
      <article class="panel">
        <div class="panel-title"><div><h2>数据时效</h2><p>展示各数据源自己的状态和更新时间</p></div></div>
        <el-table :data="data?.freshness.items || []" size="small" max-height="350">
          <el-table-column prop="label" label="数据源" min-width="145" /><el-table-column label="状态" width="95"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template></el-table-column>
          <el-table-column label="更新时间" min-width="170"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column><el-table-column label="数据年龄" width="100"><template #default="{ row }">{{ row.age_seconds === null ? '无数据' : `${row.age_seconds}s` }}</template></el-table-column>
        </el-table>
      </article>
    </div>

    <div class="three-columns">
      <article class="panel"><div class="panel-title"><div><h2>最近任务</h2><p>任务中心现有记录</p></div><el-button link type="primary" @click="go('/tasks')">任务中心</el-button></div><ul class="record-list"><li v-for="task in data?.recent_operations.tasks.slice(0, 8)" :key="task.id" @click="go(`/tasks?task=${task.id}`)"><span>{{ task.name }}</span><el-tag size="small" :type="statusType(task.status)">{{ task.status }}</el-tag><small>{{ formatTime(task.updated_time) }}</small></li></ul><el-empty v-if="!data?.recent_operations.tasks.length" description="暂无任务" :image-size="50" /></article>
      <article class="panel"><div class="panel-title"><div><h2>最近采集会话</h2><p>LOCAL / Agent 导入会话</p></div><el-button link type="primary" @click="go('/rail-transit/online-mr')">实时展示</el-button></div><ul class="record-list"><li v-for="session in data?.recent_operations.sessions.slice(0, 8)" :key="session.session_id" @click="go(`/rail-transit/online-mr?session_id=${session.session_id}`)"><span>{{ session.mr_name || session.device_name }}</span><el-tag size="small" :type="statusType(session.status)">{{ session.status }}</el-tag><small>{{ formatTime(session.started_at) }}</small></li></ul><el-empty v-if="!data?.recent_operations.sessions.length" description="暂无会话" :image-size="50" /></article>
      <article class="panel"><div class="panel-title"><div><h2>Mesh 离线分析</h2><p>既有解析结果摘要</p></div><el-button link type="primary" @click="go('/rail-transit/mesh-analysis')">分析详情</el-button></div><div class="analysis-grid"><span>会话 <b>{{ data?.analysis.summary.session_count ?? 0 }}</b></span><span>链路记录 <b>{{ data?.analysis.summary.link_record_count ?? 0 }}</b></span><span>切换 <b>{{ data?.analysis.summary.switch_event_count ?? 0 }}</b></span><span>短时建链 <b>{{ data?.analysis.summary.short_link_count ?? 0 }}</b></span><span>乒乓 <b>{{ data?.analysis.summary.pingpong_count ?? 0 }}</b></span><span>未匹配 AP <b>{{ data?.analysis.summary.unmatched_ap_count ?? 0 }}</b></span></div></article>
    </div>

    <article class="panel"><div class="panel-title"><div><h2>Agent 状态</h2><p>仅使用 Controller 已缓存状态，不主动连接 Agent</p></div><el-button link type="primary" @click="go('/agents')">Agent 控制中心</el-button></div><el-table :data="data?.agents.items || []" size="small" empty-text="当前局点未登记 Agent"><el-table-column prop="name" label="Agent" min-width="140" /><el-table-column prop="base_url" label="地址" min-width="180" /><el-table-column label="状态" width="95"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status }}</el-tag></template></el-table-column><el-table-column prop="version" label="版本" width="120" /><el-table-column label="最后检查" min-width="175"><template #default="{ row }">{{ formatTime(row.last_checked_at) }}</template></el-table-column><el-table-column prop="last_error_message" label="错误摘要" min-width="180" show-overflow-tooltip /></el-table></article>
  </section>
</template>

<style scoped>
.dashboard-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.heading-actions,.source-strip,.panel-title{display:flex;align-items:center;gap:12px}.page-heading,.panel-title{justify-content:space-between}.page-heading h1,.panel-title h2{margin:2px 0 6px}.page-heading p,.panel-title p{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.source-strip{flex-wrap:wrap;padding:10px 14px;background:var(--el-fill-color-light);border-radius:10px;font-size:13px}.summary-grid{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px}.metric-card,.panel{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--el-text-color-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:23px}.metric-card.good strong{color:var(--el-color-success)}.metric-card.warning strong{color:var(--el-color-warning)}.metric-card.danger strong{color:var(--el-color-danger)}.two-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.three-columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.panel{padding:14px 16px;overflow:hidden}.panel-title{margin-bottom:12px}.mini-grid,.analysis-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px}.mini-grid span,.analysis-grid span{padding:9px;background:var(--el-fill-color-light);border-radius:8px;color:var(--el-text-color-secondary)}.mini-grid b,.analysis-grid b{display:block;margin-top:4px;color:var(--el-text-color-primary);font-size:18px}.record-list{list-style:none;margin:0;padding:0}.record-list li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 8px;padding:9px 0;border-bottom:1px solid var(--el-border-color-lighter);cursor:pointer}.record-list li span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.record-list small{grid-column:1/-1;color:var(--el-text-color-secondary)}@media(max-width:1400px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}.three-columns{grid-template-columns:1fr 1fr}.three-columns .panel:last-child{grid-column:1/-1}}@media(max-width:1000px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.two-columns,.three-columns{grid-template-columns:1fr}.three-columns .panel:last-child{grid-column:auto}.page-heading{align-items:flex-start;flex-direction:column}.mini-grid,.analysis-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
