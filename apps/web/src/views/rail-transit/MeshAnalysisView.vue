<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import MeshRssiChart from '../../components/mesh-analysis/MeshRssiChart.vue'
import {
  getMeshAlignment, getMeshAnalysisSession, getMeshAnalysisSummary, getMeshChannelBusy, getMeshRawTail,
  getMeshRssi, getMeshTimeline, listMeshAnalysisSessions, listMeshAnomalies, listMeshApStatistics,
  listMeshArtifacts, listMeshLinks, listMeshSwitchEvents, meshArtifactDownloadUrl,
} from '../../api/meshAnalysis'
import type {
  MeshAlignment, MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshApStatistics, MeshArtifact,
  MeshChannelBusy, MeshLinkDetail, MeshRawTail, MeshRssi, MeshSessionDetail, MeshSwitchEvent, MeshTimelineItem,
} from '../../types/meshAnalysis'

const router = useRouter()
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const summary = ref<MeshAnalysisSummary | null>(null)
const sessions = ref<MeshAnalysisSession[]>([])
const total = ref(0)
const selected = ref<MeshSessionDetail | null>(null)
const links = ref<MeshLinkDetail[]>([])
const linkTotal = ref(0)
const timeline = ref<MeshTimelineItem[]>([])
const switches = ref<MeshSwitchEvent[]>([])
const rssi = ref<MeshRssi | null>(null)
const channelBusy = ref<MeshChannelBusy[]>([])
const anomalies = ref<MeshAnomaly[]>([])
const anomalyTotal = ref(0)
const apStatistics = ref<MeshApStatistics[]>([])
const alignment = ref<MeshAlignment | null>(null)
const artifacts = ref<MeshArtifact[]>([])
const rawTail = ref<MeshRawTail | null>(null)
const activeTab = ref('links')
const filters = reactive({ query: '', mr_role: '', has_warning: '' as '' | 'true' | 'false', page: 1, page_size: 50 })
const linkFilters = reactive({ query: '', link_role: '', page: 1, page_size: 100, sort_order: 'asc' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let failureCount = 0

const cards = computed(() => summary.value ? [
  ['分析会话', summary.value.session_count], ['列车 / MR', `${summary.value.train_count} / ${summary.value.mr_count}`],
  ['链路记录', summary.value.link_record_count], ['主 / 备链路', `${summary.value.active_link_count} / ${summary.value.standby_link_count}`],
  ['切换事件', summary.value.switch_event_count], ['短时建链', summary.value.short_link_count],
  ['乒乓切换', summary.value.pingpong_count], ['未匹配 AP', summary.value.unmatched_ap_count],
] : [])

onMounted(async () => { await refreshOverview(); scheduleRefresh() })
onBeforeUnmount(() => { if (refreshTimer) clearTimeout(refreshTimer); refreshTimer = null })

function scheduleRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = setTimeout(async () => {
    if (document.visibilityState === 'visible') await refreshOverview(true)
    scheduleRefresh()
  }, failureCount >= 3 ? 90_000 : 30_000)
}

async function refreshOverview(silent = false): Promise<void> {
  if (loading.value) return
  loading.value = !silent
  try {
    const [nextSummary, page] = await Promise.all([
      getMeshAnalysisSummary(),
      listMeshAnalysisSessions({ ...filters, has_warning: filters.has_warning === '' ? null : filters.has_warning === 'true' }),
    ])
    summary.value = nextSummary
    sessions.value = page.items
    total.value = page.total
    error.value = ''
    failureCount = 0
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : 'Mesh 分析结果加载失败'
    failureCount += 1
  } finally { loading.value = false }
}

async function openSession(row: MeshAnalysisSession): Promise<void> {
  detailLoading.value = true
  rawTail.value = null
  try {
    const id = row.session_id
    const [detail, linkPage, timelineData, switchPage, rssiData, busyData, anomalyPage, apPage, alignmentData, artifactRows] = await Promise.all([
      getMeshAnalysisSession(id), listMeshLinks(id, linkFilters), getMeshTimeline(id), listMeshSwitchEvents(id), getMeshRssi(id),
      getMeshChannelBusy(id), listMeshAnomalies(id), listMeshApStatistics(id), getMeshAlignment(id), listMeshArtifacts(id),
    ])
    selected.value = detail
    links.value = linkPage.items; linkTotal.value = linkPage.total
    timeline.value = timelineData.items
    switches.value = switchPage.items
    rssi.value = rssiData
    channelBusy.value = busyData.items
    anomalies.value = anomalyPage.items; anomalyTotal.value = anomalyPage.total
    apStatistics.value = apPage.items
    alignment.value = alignmentData
    artifacts.value = artifactRows
    error.value = ''
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '分析详情加载失败' }
  finally { detailLoading.value = false }
}

async function reloadLinks(page = linkFilters.page): Promise<void> {
  if (!selected.value) return
  linkFilters.page = page
  const result = await listMeshLinks(selected.value.session.session_id, linkFilters)
  links.value = result.items; linkTotal.value = result.total
}

async function loadRawTail(sourceId: string, available: boolean): Promise<void> {
  if (!selected.value || !available) return
  rawTail.value = await getMeshRawTail(selected.value.session.session_id, sourceId)
}

function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatBytes(value: number): string { if (!value) return '0 B'; if (value < 1024) return `${value} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB` }
function severityType(value: string): 'error' | 'warning' | 'info' { return value === 'error' || value === 'critical' ? 'error' : value === 'warning' ? 'warning' : 'info' }
</script>

<template>
  <section class="mesh-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT / READ ONLY</p><h1>Mesh 原始日志分析</h1><p>复用既有结构化结果与正式规则；不重解析、不生成报告、不修改原始数据。</p></div>
      <el-button :loading="loading" @click="refreshOverview()">刷新结果</el-button>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <div class="summary-grid">
      <article v-for="card in cards" :key="String(card[0])" class="metric-card"><span>{{ card[0] }}</span><strong>{{ card[1] }}</strong></article>
    </div>

    <div class="content-card" v-loading="loading">
      <div class="toolbar">
        <el-input v-model="filters.query" clearable placeholder="搜索列车、MR 或来源文件" @keyup.enter="filters.page = 1; refreshOverview()" />
        <el-select v-model="filters.mr_role" clearable placeholder="MR 角色"><el-option label="CT" value="CT" /><el-option label="TC" value="TC" /><el-option label="CW" value="CW" /></el-select>
        <el-select v-model="filters.has_warning" clearable placeholder="数据告警"><el-option label="有告警" value="true" /><el-option label="无告警" value="false" /></el-select>
        <el-button type="primary" @click="filters.page = 1; refreshOverview()">查询</el-button>
      </div>
      <el-table :data="sessions" border stripe height="340" empty-text="暂无已持久化 Mesh 分析来源" @row-dblclick="openSession">
        <el-table-column prop="analysis_time" label="分析时间" width="175" />
        <el-table-column prop="train_name" label="列车" width="100" />
        <el-table-column prop="mr_name" label="MR" min-width="145" />
        <el-table-column prop="mr_role" label="角色" width="70" />
        <el-table-column prop="source_type" label="来源" width="125" />
        <el-table-column prop="original_filename" label="原始日志" min-width="260" show-overflow-tooltip />
        <el-table-column prop="link_record_count" label="链路记录" width="110" />
        <el-table-column label="主 / 备" width="125"><template #default="{ row }">{{ row.active_link_count }} / {{ row.standby_link_count }}</template></el-table-column>
        <el-table-column prop="event_count" label="事件" width="90" />
        <el-table-column prop="data_integrity" label="完整性" width="95" />
        <el-table-column label="告警" width="80"><template #default="{ row }"><el-tag :type="row.warning_count ? 'warning' : 'success'">{{ row.warning_count }}</el-tag></template></el-table-column>
        <el-table-column prop="report_count" label="报告" width="75" />
        <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openSession(row)">查看</el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><span>共 {{ total }} 个来源</span><el-pagination :current-page="filters.page" :page-size="filters.page_size" layout="prev, pager, next" :total="total" @current-change="(page: number) => { filters.page = page; refreshOverview() }" /></div>
    </div>

    <div v-if="selected" class="content-card detail-card" v-loading="detailLoading">
      <div class="detail-heading">
        <div><h2>{{ selected.session.mr_name }}</h2><p>{{ selected.session.original_filename }} · {{ selected.session.first_sample_time }} — {{ selected.session.last_sample_time }}</p></div>
        <div class="jump-actions">
          <el-button @click="router.push({ path: '/rail-transit/train-communication', query: { train: selected?.session.train_name } })">在线列车通信</el-button>
          <el-button @click="router.push('/rail-transit/online-mr')">Online MR</el-button>
          <el-button @click="router.push('/ac-management/mesh-links')">AC Mesh-Link</el-button>
          <el-button v-if="selected.session.task_id" @click="router.push({ path: '/tasks', query: { task: selected?.session.task_id } })">任务中心</el-button>
        </div>
      </div>
      <el-alert v-for="warning in selected.warnings" :key="warning.code" :title="warning.message" :type="severityType(warning.severity)" :closable="false" show-icon />

      <el-tabs v-model="activeTab">
        <el-tab-pane label="链路明细" name="links">
          <div class="toolbar"><el-input v-model="linkFilters.query" clearable placeholder="Peer AP / MAC / 站点" /><el-select v-model="linkFilters.link_role" clearable placeholder="链路角色"><el-option label="主链路" value="ACTIVE" /><el-option label="备份链路" value="STANDBY" /></el-select><el-button @click="reloadLinks(1)">筛选</el-button></div>
          <el-table :data="links" border stripe height="430"><el-table-column prop="timestamp" label="时间" width="185" fixed="left" /><el-table-column prop="local_radio" label="Mesh Radio" width="105" /><el-table-column prop="peer_ap_name" label="Peer AP" min-width="160" /><el-table-column prop="peer_ap_mac" label="Peer MAC" width="145" /><el-table-column prop="link_role" label="角色" width="90" /><el-table-column label="RSSI" width="90"><template #default="{ row }">{{ display(row.rssi) }}</template></el-table-column><el-table-column prop="station" label="站点" width="130" /><el-table-column prop="section" label="区间" width="150" /><el-table-column prop="mileage" label="里程" width="120" /><el-table-column prop="line_side" label="方向" width="95" /><el-table-column prop="event_type" label="事件" width="120" /><el-table-column prop="duration_ms" label="上报时长(ms)" width="130" /><el-table-column prop="match_method" label="匹配方式" min-width="180" /><el-table-column prop="warning" label="数据告警" min-width="150" /></el-table>
          <div class="pagination"><span>共 {{ linkTotal }} 条</span><el-pagination :current-page="linkFilters.page" :page-size="linkFilters.page_size" layout="prev, pager, next" :total="linkTotal" @current-change="reloadLinks" /></div>
        </el-tab-pane>

        <el-tab-pane label="主链路时间线" name="timeline"><el-table :data="timeline" border height="430"><el-table-column prop="start_time" label="开始" width="185" /><el-table-column prop="end_time" label="结束" width="185" /><el-table-column prop="duration_seconds" label="持续(s)" width="100" /><el-table-column prop="peer_ap_name" label="Peer AP" min-width="160" /><el-table-column prop="peer_ap_mac" label="Peer MAC" width="145" /><el-table-column label="RSSI min / avg / max" width="185"><template #default="{ row }">{{ display(row.rssi_min) }} / {{ display(row.rssi_avg) }} / {{ display(row.rssi_max) }}</template></el-table-column><el-table-column prop="station" label="站点" width="130" /><el-table-column prop="section" label="区间" min-width="150" /></el-table></el-tab-pane>

        <el-tab-pane label="切换事件" name="switches"><el-table :data="switches" border height="430"><el-table-column prop="timestamp" label="时间" width="185" /><el-table-column prop="event_type" label="事件" width="130" /><el-table-column prop="from_ap_name" label="原 AP" min-width="150" /><el-table-column prop="to_ap_name" label="目标 AP" min-width="150" /><el-table-column label="RSSI 前 / 后" width="135"><template #default="{ row }">{{ display(row.before_rssi) }} / {{ display(row.after_rssi) }}</template></el-table-column><el-table-column prop="duration_ms" label="耗时(ms)" width="100" /><el-table-column label="短时" width="75"><template #default="{ row }">{{ row.is_short_link ? '是' : '否' }}</template></el-table-column><el-table-column label="乒乓" width="75"><template #default="{ row }">{{ row.is_pingpong ? '是' : '否' }}</template></el-table-column><el-table-column prop="station" label="站点" width="130" /></el-table></el-tab-pane>

        <el-tab-pane label="RSSI" name="rssi"><template v-if="rssi"><div class="mini-summary"><span>最近 <strong>{{ display(rssi.statistics.latest_rssi) }}</strong></span><span>最小 <strong>{{ display(rssi.statistics.min_rssi) }}</strong></span><span>平均 <strong>{{ display(rssi.statistics.avg_rssi) }}</strong></span><span>最大 <strong>{{ display(rssi.statistics.max_rssi) }}</strong></span><span>样本 <strong>{{ rssi.statistics.sample_count }}</strong></span><span>缺失 <strong>{{ rssi.statistics.missing_sample_count }}</strong></span></div><MeshRssiChart :points="rssi.points" /><p class="hint">{{ rssi.downsampled ? `已由后端从 ${rssi.total_points} 点降采样` : '展示全部结构化样本' }}；空值保持为空，不用 0 补齐。</p></template></el-tab-pane>

        <el-tab-pane label="空口繁忙度" name="busy"><el-table :data="channelBusy" border height="430"><el-table-column prop="timestamp" label="时间" width="185" /><el-table-column prop="local_radio" label="Radio" width="80" /><el-table-column label="CtlBusy" width="95"><template #default="{ row }">{{ display(row.ctl_busy) }}</template></el-table-column><el-table-column label="TxBusy" width="95"><template #default="{ row }">{{ display(row.tx_busy) }}</template></el-table-column><el-table-column label="RxBusy" width="95"><template #default="{ row }">{{ display(row.rx_busy) }}</template></el-table-column><el-table-column prop="peer_ap_name" label="Peer AP" min-width="160" /><el-table-column prop="station" label="站点" width="140" /><el-table-column prop="source_type" label="结构化来源" width="160" /></el-table></el-tab-pane>

        <el-tab-pane :label="`异常摘要 (${anomalyTotal})`" name="anomalies"><el-table :data="anomalies" border height="430"><el-table-column label="级别" width="90"><template #default="{ row }"><el-tag :type="severityType(row.severity)">{{ row.severity }}</el-tag></template></el-table-column><el-table-column prop="anomaly_type" label="类型" width="140" /><el-table-column prop="start_time" label="开始" width="185" /><el-table-column prop="end_time" label="结束" width="185" /><el-table-column prop="peer_ap_name" label="AP" min-width="150" /><el-table-column prop="description" label="说明" min-width="260" /><el-table-column prop="evidence_reference" label="证据引用" min-width="160" /></el-table></el-tab-pane>

        <el-tab-pane label="AP 统计" name="aps"><el-table :data="apStatistics" border height="430"><el-table-column prop="peer_ap_name" label="AP" min-width="160" /><el-table-column prop="peer_ap_mac" label="MAC" width="145" /><el-table-column prop="station" label="站点" width="130" /><el-table-column prop="section" label="区间" min-width="145" /><el-table-column prop="link_up_count" label="主链记录" width="105" /><el-table-column prop="link_down_count" label="备链记录" width="105" /><el-table-column prop="switch_in_count" label="切入" width="75" /><el-table-column prop="switch_out_count" label="切出" width="75" /><el-table-column label="平均 / 最小 RSSI" width="150"><template #default="{ row }">{{ display(row.avg_rssi) }} / {{ display(row.min_rssi) }}</template></el-table-column><el-table-column prop="match_status" label="匹配" width="90" /></el-table></el-tab-pane>

        <el-tab-pane label="fping / iPerf 对齐" name="alignment"><el-alert v-if="alignment?.message" :title="alignment.message" type="info" :closable="false" /><el-table :data="alignment?.items || []" border height="400" empty-text="暂无可对齐的结构化流量数据"><el-table-column prop="timestamp" label="时间" width="185" /><el-table-column prop="peer_ap_name" label="Peer AP" min-width="150" /><el-table-column label="RSSI" width="90"><template #default="{ row }">{{ display(row.rssi) }}</template></el-table-column><el-table-column label="fping RTT" width="110"><template #default="{ row }">{{ display(row.fping_rtt_ms, ' ms') }}</template></el-table-column><el-table-column label="丢包" width="95"><template #default="{ row }">{{ display(row.fping_loss_percent, '%') }}</template></el-table-column><el-table-column label="iPerf" width="110"><template #default="{ row }">{{ display(row.iperf_mbps, ' Mbps') }}</template></el-table-column><el-table-column prop="station" label="站点" width="130" /></el-table></el-tab-pane>

        <el-tab-pane label="报告与来源" name="artifacts">
          <h3>已有报告与文件</h3><el-table :data="artifacts" border><el-table-column prop="artifact_type" label="类型" width="140" /><el-table-column prop="name" label="文件名" min-width="260" /><el-table-column label="大小" width="110"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column><el-table-column prop="modified_at" label="生成时间" width="175" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-link v-if="row.downloadable" type="primary" :href="meshArtifactDownloadUrl(selected!.session.session_id, row.artifact_id)">下载</el-link></template></el-table-column></el-table>
          <h3>原始数据来源</h3><el-table :data="selected.sources" border><el-table-column prop="name" label="来源文件" min-width="260" /><el-table-column prop="source_type" label="来源类型" width="150" /><el-table-column label="状态" width="100"><template #default="{ row }">{{ row.exists ? '可用' : '缺失' }}</template></el-table-column><el-table-column label="大小" width="110"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column><el-table-column label="只读片段" width="110"><template #default="{ row }"><el-button link type="primary" :disabled="!row.tail_available" @click="loadRawTail(row.source_id, row.tail_available)">查看 tail</el-button></template></el-table-column></el-table>
          <el-alert v-if="rawTail?.message" :title="rawTail.message" type="info" :closable="false" /><pre v-if="rawTail?.available">{{ rawTail.lines.join('\n') }}</pre>
        </el-tab-pane>
      </el-tabs>
    </div>
  </section>
</template>

<style scoped>
.mesh-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.detail-heading,.jump-actions,.toolbar,.pagination,.mini-summary{display:flex;align-items:center;gap:12px}.page-heading,.detail-heading,.pagination{justify-content:space-between}.page-heading h1,.detail-heading h2{margin:2px 0 6px}.page-heading p,.detail-heading p,.hint{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.summary-grid{display:grid;grid-template-columns:repeat(8,minmax(105px,1fr));gap:10px}.metric-card,.content-card{background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px}.metric-card{padding:13px}.metric-card span{color:var(--el-text-color-secondary);font-size:12px}.metric-card strong{display:block;margin-top:6px;font-size:22px}.content-card{padding:14px 16px;overflow:hidden}.toolbar,.jump-actions,.mini-summary{flex-wrap:wrap}.toolbar{margin-bottom:12px}.toolbar .el-input{width:300px}.toolbar .el-select{width:130px}.pagination{padding-top:12px;color:var(--el-text-color-secondary)}.detail-card .el-alert{margin:10px 0}.mini-summary{padding:10px 0}.mini-summary span{padding:9px 12px;border-radius:8px;background:var(--el-fill-color-light)}.hint{font-size:12px}h3{margin:16px 0 8px}pre{max-height:360px;overflow:auto;padding:12px;background:#111827;color:#d1d5db;border-radius:8px;font:12px/1.6 Consolas,monospace}@media(max-width:1450px){.summary-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}}@media(max-width:900px){.summary-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.page-heading,.detail-heading{align-items:flex-start;flex-direction:column}}
</style>
