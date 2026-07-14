<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useTrainCommunicationStore } from '../../stores/trainCommunication'
import OnlineMrLocalControl from '../../components/OnlineMrLocalControl.vue'
import type { CommunicationStatus, MrCommunicationStatus, TrainCommunicationRow } from '../../types/trainCommunication'

const router = useRouter()
const store = useTrainCommunicationStore()
const drawerVisible = ref(false)
const activeDetailTab = ref('overview')
const rawExpanded = ref<string[]>([])

const summaryCards = computed(() => {
  const value = store.summary
  return [
    ['已登记列车', value?.registered_trains ?? 0, ''], ['已登记 MR', value?.registered_mrs ?? 0, ''],
    ['通信正常', value?.normal_trains ?? 0, 'normal'], ['告警列车', value?.warning_trains ?? 0, 'warning'],
    ['严重异常', value?.critical_trains ?? 0, 'critical'], ['数据过期', value?.stale_trains ?? 0, 'stale'],
    ['状态未知', value?.unknown_trains ?? 0, 'unknown'], ['当前 Mesh-Link', value?.current_mesh_links ?? 0, ''],
    ['运行中采集', value?.active_online_mr_sessions ?? 0, ''], ['Agent 导入会话', value?.agent_imported_sessions ?? 0, ''],
  ] as const
})

function mrByRole(row: { mrs: MrCommunicationStatus[] }, role: string): MrCommunicationStatus | undefined {
  return row.mrs.find((item) => item.mr_role.toUpperCase() === role)
}
function display(value: unknown, suffix = ''): string { return value === null || value === undefined || value === '' ? '无数据' : `${value}${suffix}` }
function formatTime(value: string | null | undefined): string { return value ? value.replace('T', ' ').replace(/\+00:00$/, '') : '无数据' }
function statusLabel(value: string): string { return ({ normal: '正常', warning: '告警', critical: '严重', stale: '过期', unknown: '未知' } as Record<string, string>)[value] || value || '未知' }
function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  return ({ normal: 'success', warning: 'warning', critical: 'danger', stale: 'warning', unknown: 'info', online: 'success', fresh: 'success' } as const)[value as CommunicationStatus] || 'info'
}
function metric(value: number | null, suffix: string): string { return value === null ? '无数据' : `${value.toFixed(1)} ${suffix}` }
async function openTrain(trainId: string): Promise<void> { drawerVisible.value = true; activeDetailTab.value = 'overview'; await store.selectTrain(trainId) }
async function openMr(mrId: string): Promise<void> { activeDetailTab.value = 'mr'; await store.selectMr(mrId) }
function handleRowDoubleClick(row: TrainCommunicationRow): void { void openTrain(row.train_id) }
function handleRawTabChange(name: string | number): void { store.setRawSource(String(name)) }
function handleRawChange(names: string | string[]): void {
  const list = Array.isArray(names) ? names : names ? [names] : []
  rawExpanded.value = list
  store.setRawExpanded(list.includes('raw'))
}
function handleVisibility(): void { store.setPageVisible(!document.hidden) }

onMounted(() => { document.addEventListener('visibilitychange', handleVisibility); store.startPolling() })
onBeforeUnmount(() => { document.removeEventListener('visibilitychange', handleVisibility); store.stopPolling() })
</script>

<template>
  <section class="communication-page">
    <header class="page-heading">
      <div><p class="eyebrow">RAIL TRANSIT · MONITOR + LOCAL CONTROL</p><h1>在线列车车地通信检测</h1><p>主体保持只读聚合；本地主程序 WebHost 可在独立安全开关开启后受控启动或正常停止 LOCAL Online MR。</p></div>
      <el-tag type="info">只读监控 + 本地受控入口</el-tag>
    </header>

    <el-alert v-if="store.error" :title="store.error" type="warning" show-icon :closable="false" />
    <div class="summary-grid">
      <article v-for="card in summaryCards" :key="card[0]" :class="['metric-card', card[2]]"><span>{{ card[0] }}</span><strong>{{ card[1] }}</strong></article>
    </div>
    <div class="source-strip">
      <span>局点：{{ store.summary?.site_id || '无数据' }}</span><span>最近更新：{{ formatTime(store.summary?.latest_updated_at) }}</span>
      <span>刷新：{{ store.hasActive ? '活动会话 2 秒' : '静态 10 秒' }}</span><span>连续失败后降频至 15 秒</span>
    </div>

    <div class="content-card">
      <div class="toolbar">
        <el-input v-model="store.filters.query" clearable placeholder="列车、MR、IP、轨旁 AP、站点或区间" @keyup.enter="store.applyFilters" />
        <el-select v-model="store.filters.communication_status" clearable placeholder="综合状态">
          <el-option v-for="item in ['normal', 'warning', 'critical', 'stale', 'unknown']" :key="item" :label="statusLabel(item)" :value="item" />
        </el-select>
        <el-input v-model="store.filters.station" clearable placeholder="站点" />
        <el-input v-model="store.filters.section" clearable placeholder="区间" />
        <el-checkbox v-model="store.filters.active_only">仅运行中采集</el-checkbox>
        <el-checkbox v-model="store.filters.agent_only">仅 Agent 会话</el-checkbox>
        <el-checkbox v-model="store.filters.optical_anomaly_only">仅光衰异常</el-checkbox>
        <el-button type="primary" @click="store.applyFilters">查询</el-button>
      </div>
      <el-table v-loading="store.loading" :data="store.trains" stripe height="calc(100vh - 470px)" empty-text="暂无已登记列车通信数据" @row-dblclick="handleRowDoubleClick">
        <el-table-column prop="train_no" label="列车" width="85" fixed="left" />
        <el-table-column label="MR-CT" min-width="150"><template #default="{ row }"><span v-if="mrByRole(row, 'CT')"><el-tag :type="statusType(mrByRole(row, 'CT')!.communication_status)" size="small">{{ statusLabel(mrByRole(row, 'CT')!.communication_status) }}</el-tag> {{ mrByRole(row, 'CT')!.peer_ap_name || '无 Peer AP' }}</span><span v-else>无数据</span></template></el-table-column>
        <el-table-column label="MR-TC" min-width="150"><template #default="{ row }"><span v-if="mrByRole(row, 'TC')"><el-tag :type="statusType(mrByRole(row, 'TC')!.communication_status)" size="small">{{ statusLabel(mrByRole(row, 'TC')!.communication_status) }}</el-tag> {{ mrByRole(row, 'TC')!.peer_ap_name || '无 Peer AP' }}</span><span v-else>无数据</span></template></el-table-column>
        <el-table-column label="当前位置" min-width="155"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ [mr.station, mr.section].filter(Boolean).join(' / ') || '无数据' }}</div></template></el-table-column>
        <el-table-column label="RSSI" width="105"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ display(mr.rssi, ' dBm') }}</div></template></el-table-column>
        <el-table-column label="fping" width="125"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ metric(mr.fping_latest_rtt_ms, 'ms') }}</div></template></el-table-column>
        <el-table-column label="丢包" width="105"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ metric(mr.fping_loss_percent, '%') }}</div></template></el-table-column>
        <el-table-column label="iPerf" width="120"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ metric(mr.iperf_latest_mbps, 'Mbps') }}</div></template></el-table-column>
        <el-table-column label="采集/执行端" min-width="130"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ mr.collection_status }} / {{ mr.executor || '无数据' }}</div></template></el-table-column>
        <el-table-column label="完整性" width="105"><template #default="{ row }"><div v-for="mr in row.mrs" :key="mr.mr_id">{{ mr.mr_role }}：{{ mr.data_integrity }}</div></template></el-table-column>
        <el-table-column label="综合状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.communication_status)">{{ statusLabel(row.communication_status) }}</el-tag></template></el-table-column>
        <el-table-column label="最近更新" width="175"><template #default="{ row }">{{ formatTime(row.last_updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openTrain(row.train_id)">详情</el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><span>共 {{ store.total }} 列车</span><el-pagination :current-page="store.filters.page" :page-size="store.filters.page_size" layout="prev, pager, next" :total="store.total" @current-change="store.setPage" /></div>
    </div>

    <el-drawer v-model="drawerVisible" title="列车通信详情" size="min(1100px, 96vw)" @closed="store.setRawExpanded(false)">
      <div v-loading="store.detailLoading">
        <template v-if="store.selectedTrain">
          <div class="detail-title"><div><h2>{{ store.selectedTrain.train.train_name }}</h2><p>{{ store.selectedTrain.site_id }} · {{ store.selectedTrain.train.mrs.length }} 台 MR · {{ formatTime(store.selectedTrain.train.last_updated_at) }}</p></div><el-tag size="large" :type="statusType(store.selectedTrain.train.communication_status)">{{ statusLabel(store.selectedTrain.train.communication_status) }}</el-tag></div>
          <el-tabs v-model="activeDetailTab">
            <el-tab-pane label="MR 状态" name="overview">
              <div class="mr-grid">
                <article v-for="mr in store.selectedTrain.train.mrs" :key="mr.mr_id" class="mr-card">
                  <div class="mr-card-title"><div><h3>{{ mr.mr_role }} · {{ mr.mr_name }}</h3><small>{{ mr.management_ip || '无 IP' }} · {{ mr.executor || '无执行端' }}</small></div><el-tag :type="statusType(mr.communication_status)">{{ statusLabel(mr.communication_status) }}</el-tag></div>
                  <dl><dt>Mesh-Link</dt><dd>{{ display(mr.mesh_link_status) }}</dd><dt>轨旁 AP</dt><dd>{{ display(mr.peer_ap_name) }}</dd><dt>Peer MAC</dt><dd>{{ display(mr.peer_ap_mac) }}</dd><dt>Mesh Radio</dt><dd>{{ display(mr.mesh_radio) }}</dd><dt>RSSI</dt><dd>{{ display(mr.rssi, ' dBm') }}</dd><dt>站点/区间</dt><dd>{{ [mr.station, mr.section].filter(Boolean).join(' / ') || '无数据' }}</dd><dt>里程/方向</dt><dd>{{ [mr.mileage, mr.line_side].filter(Boolean).join(' / ') || '无数据' }}</dd><dt>AP/光衰</dt><dd>{{ mr.ap_online_status }} / {{ mr.optical_status }}</dd></dl>
                  <div class="metric-row"><span>fping {{ metric(mr.fping_latest_rtt_ms, 'ms') }} / {{ metric(mr.fping_loss_percent, '%') }}</span><span>iPerf {{ metric(mr.iperf_latest_mbps, 'Mbps') }}</span></div>
                  <el-alert v-for="warning in mr.warnings" :key="`${warning.code}-${warning.source}`" :title="warning.message" :type="warning.severity === 'critical' ? 'error' : 'warning'" :closable="false" />
                  <el-button type="primary" plain @click="openMr(mr.mr_id)">查看采集、任务与原始片段</el-button>
                </article>
              </div>
            </el-tab-pane>
            <el-tab-pane label="MR 采集详情" name="mr">
              <template v-if="store.selectedMr">
                <OnlineMrLocalControl :site-id="store.summary?.site_id || ''" :mr="store.selectedMr.mr" />
                <div class="detail-actions">
                  <el-button @click="router.push({ path: '/ac-management/mesh-links', query: { mr_name: store.selectedMr?.mr.mr_name } })">Mesh-Link 监控</el-button>
                  <el-button @click="router.push({ path: '/rail-transit/online-mr', query: { device_id: store.selectedMr?.mr.device_id } })">Online MR 展示</el-button>
                  <el-button @click="router.push({ path: '/rail-transit/base-data', query: { mr: store.selectedMr?.mr.mr_id } })">基础资料</el-button>
                  <el-button v-if="store.selectedMr.mr.task_id" @click="router.push({ path: '/tasks', query: { task: store.selectedMr?.mr.task_id } })">任务中心</el-button>
                  <el-button v-if="store.selectedMr.mr.agent_id" @click="router.push({ path: '/agents', query: { agent: store.selectedMr?.mr.agent_id } })">Agent 控制中心</el-button>
                </div>
                <el-descriptions :column="3" border>
                  <el-descriptions-item label="Session">{{ display(store.selectedMr.mr.session_id) }}</el-descriptions-item><el-descriptions-item label="采集状态">{{ store.selectedMr.mr.collection_status }}</el-descriptions-item><el-descriptions-item label="数据完整性">{{ store.selectedMr.mr.data_integrity }}</el-descriptions-item>
                  <el-descriptions-item label="fping">{{ metric(store.selectedMr.mr.fping.latest_value, 'ms') }} / {{ metric(store.selectedMr.mr.fping.loss_percent, '%') }}</el-descriptions-item><el-descriptions-item label="iPerf">{{ metric(store.selectedMr.mr.iperf.latest_value, 'Mbps') }}</el-descriptions-item><el-descriptions-item label="数据时间">{{ formatTime(store.selectedMr.mr.collected_at) }}</el-descriptions-item>
                </el-descriptions>
                <h3>采集器</h3><el-table :data="store.selectedMr.collectors" border empty-text="暂无采集器状态"><el-table-column prop="label" label="采集器" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="size_bytes" label="原始文件字节" width="130" /><el-table-column prop="error" label="错误" /></el-table>
                <el-collapse @change="handleRawChange"><el-collapse-item title="原始采集（默认折叠，仅受控 tail）" name="raw">
                  <el-tabs :model-value="store.rawSource" @tab-change="handleRawTabChange">
                    <el-tab-pane v-for="source in store.selectedMr.raw_sources" :key="source.name" :name="source.name" :label="source.label" />
                  </el-tabs>
                  <p v-if="!store.rawTail?.exists" class="empty-text">{{ store.rawTail?.message || '文件不存在或尚未生成' }}</p><pre v-else>{{ store.rawTail.lines.join('\n') }}</pre>
                </el-collapse-item></el-collapse>
                <h3>关联任务</h3><el-table :data="store.selectedMr.tasks" border empty-text="暂无关联任务"><el-table-column prop="name" label="任务" /><el-table-column prop="status" label="状态" width="110" /><el-table-column prop="progress" label="进度" width="90" /><el-table-column prop="started_at" label="开始时间" width="175" /><el-table-column prop="ended_at" label="结束时间" width="175" /><el-table-column prop="error_summary" label="错误摘要" /></el-table>
                <h3>采集包</h3><el-table :data="store.selectedMr.packages" border empty-text="暂无采集包"><el-table-column prop="package_name" label="包名" /><el-table-column prop="executor" label="来源" width="90" /><el-table-column prop="import_status" label="导入状态" width="110" /><el-table-column prop="data_integrity" label="完整性" width="100" /><el-table-column prop="package_reference" label="安全引用" /></el-table>
              </template><el-empty v-else description="请先选择 MR" />
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.communication-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.page-heading,.source-strip,.toolbar,.pagination,.detail-title,.mr-card-title,.metric-row,.detail-actions { display: flex; align-items: center; gap: 12px; }.page-heading,.detail-title,.mr-card-title,.pagination { justify-content: space-between; }.page-heading h1,.detail-title h2,.mr-card-title h3 { margin: 2px 0 6px; }.page-heading p,.detail-title p,.mr-card-title small,.empty-text { margin: 0; color: var(--el-text-color-secondary); }.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }.summary-grid { display: grid; grid-template-columns: repeat(5,minmax(130px,1fr)); gap: 10px; }.metric-card,.content-card,.mr-card { background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 12px; }.metric-card { padding: 13px; }.metric-card span { color: var(--el-text-color-secondary); font-size: 12px; }.metric-card strong { display: block; margin-top: 6px; font-size: 24px; }.metric-card.normal strong { color: var(--el-color-success); }.metric-card.warning strong,.metric-card.stale strong { color: var(--el-color-warning); }.metric-card.critical strong { color: var(--el-color-danger); }.metric-card.unknown strong { color: var(--el-text-color-secondary); }.source-strip { flex-wrap: wrap; padding: 10px 14px; background: var(--el-fill-color-light); border-radius: 10px; font-size: 13px; }.content-card { padding: 14px 16px; overflow: hidden; }.toolbar { flex-wrap: wrap; margin-bottom: 12px; }.toolbar .el-input:first-child { width: 300px; }.toolbar .el-input,.toolbar .el-select { width: 135px; }.pagination { padding-top: 12px; color: var(--el-text-color-secondary); }.mr-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }.mr-card { padding: 16px; }.mr-card dl { display: grid; grid-template-columns: 95px 1fr; gap: 8px 10px; }.mr-card dt { color: var(--el-text-color-secondary); }.mr-card dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }.metric-row { flex-wrap: wrap; margin: 12px 0; }.mr-card .el-alert { margin: 8px 0; }.detail-actions { flex-wrap: wrap; margin-bottom: 14px; }h3 { margin: 18px 0 10px; }pre { max-height: 370px; overflow: auto; margin: 0; padding: 12px; background: #111827; color: #d1d5db; border-radius: 8px; font: 12px/1.6 Consolas,monospace; }.empty-text { padding: 14px 0; }
@media (max-width: 1300px) { .summary-grid { grid-template-columns: repeat(3,minmax(130px,1fr)); } }.mr-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }@media (max-width: 850px) { .summary-grid,.mr-grid { grid-template-columns: 1fr; }.page-heading { align-items: flex-start; flex-direction: column; } }
</style>
