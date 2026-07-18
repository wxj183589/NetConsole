<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Refresh, View } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { useAcMeshLinkStore } from '../../stores/acMeshLink'
import type { AcMeshMrStatus } from '../../types/acMeshLink'

const store = useAcMeshLinkStore()
const router = useRouter()
const activeTab = ref('mrs')
const detailVisible = ref(false)

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  store.startPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
}

function handleRawChange(value: unknown): void {
  const activeNames = Array.isArray(value) ? value.map(String) : [String(value || '')]
  store.setRawExpanded(activeNames.includes('raw'))
}

async function openMr(row: AcMeshMrStatus): Promise<void> {
  detailVisible.value = true
  await store.selectMr(row.mr_id)
}

function display(value: unknown): string {
  return value === null || value === undefined || value === '' ? '无数据' : String(value)
}

function formatTime(value: string): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '无数据'
}

function statusType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  if (['online', 'fresh', 'normal'].includes(status)) return 'success'
  if (['offline', 'critical'].includes(status)) return 'danger'
  if (['stale', 'recent', 'warning', 'unmatched'].includes(status)) return 'warning'
  return 'info'
}

function mrStatusLabel(status: string): string {
  return { online: '在线', offline: '离线', stale: '数据过期', unknown: '未知' }[status] || status || '未知'
}

function dataStatusLabel(status: string): string {
  return { fresh: '实时', recent: '准实时', stale: '已过期', error: '解析失败', unknown: '未知', no_data: '无数据' }[status] || status
}

function apStatusLabel(status: string): string {
  return { online: '在线', offline: '离线', unauthenticated: '未认证', unknown: '未知' }[status] || status || '未知'
}

function matchLabel(method: string): string {
  return { peer_mac: 'MAC 精确', peer_name: '名称精确', normalized_peer_name: '规范化名称', unmatched: '未匹配' }[method] || method
}
</script>

<template>
  <section class="mesh-page">
    <div class="page-heading">
      <div>
        <p class="eyebrow">轨道交通无线控制器资源管理</p>
        <h1>Mesh-Link 在线监控</h1>
        <p>通过任务中心执行固定只读命令采集，展示车载 MR 与轨旁 FIT-AP 的 Mesh 链路关系。</p>
      </div>
      <div class="refresh-actions">
        <el-select v-model="store.selectedControllerId" placeholder="选择 AC" filterable>
          <el-option v-for="item in store.controllers" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-checkbox v-model="store.includeSwitchHistory">包含切换历史</el-checkbox>
        <el-button
          type="primary"
          :icon="Refresh"
          :loading="store.refreshStarting"
          :disabled="store.refreshActive || !store.selectedControllerId"
          @click="store.startRefresh"
        >{{ store.refreshActive ? '正在刷新 Mesh-Link…' : '刷新 Mesh-Link' }}</el-button>
      </div>
    </div>

    <el-alert v-if="store.error" :title="store.error" type="warning" :closable="false" show-icon />
    <el-alert v-if="store.refreshError" :title="store.refreshError" type="error" :closable="false" show-icon />
    <el-alert
      v-else-if="store.summary?.data_status !== 'fresh'"
      :title="`当前数据状态：${dataStatusLabel(store.summary?.data_status || 'no_data')}。历史 Forwarding 不代表当前在线。`"
      type="warning"
      :closable="false"
      show-icon
    />

    <div class="summary-grid">
      <article class="metric"><span>已登记车载 MR</span><strong>{{ store.summary?.registered_mrs ?? 0 }}</strong></article>
      <article class="metric good"><span>当前在线</span><strong>{{ store.summary?.online_mrs ?? 0 }}</strong></article>
      <article class="metric bad"><span>当前离线</span><strong>{{ store.summary?.offline_mrs ?? 0 }}</strong></article>
      <article class="metric warn"><span>数据过期</span><strong>{{ store.summary?.stale_mrs ?? 0 }}</strong></article>
      <article class="metric"><span>状态未知</span><strong>{{ store.summary?.unknown_mrs ?? 0 }}</strong></article>
      <article class="metric"><span>有效 Mesh-Link</span><strong>{{ store.summary?.active_links ?? 0 }}</strong></article>
      <article class="metric warn"><span>未匹配轨旁 AP</span><strong>{{ store.summary?.unmatched_links ?? 0 }}</strong></article>
      <article class="metric bad"><span>关联离线 AP</span><strong>{{ store.summary?.offline_ap_links ?? 0 }}</strong></article>
    </div>

    <div class="source-strip">
      <span>局点：{{ store.summary?.site_id || '无数据' }}</span>
      <span>更新时间：{{ formatTime(store.summary?.updated_at || '') }}</span>
      <span>数据年龄：{{ store.summary?.age_seconds == null ? '无数据' : `${store.summary.age_seconds}s` }}</span>
      <el-tag :type="statusType(store.summary?.data_status || 'no_data')">{{ dataStatusLabel(store.summary?.data_status || 'no_data') }}</el-tag>
      <span>原始回显：{{ store.summary?.raw_available ? '可用' : '不可用' }}</span>
      <template v-if="store.refreshTask">
        <span>刷新任务：{{ store.refreshTask.status }}</span>
        <el-button link type="primary" @click="router.push({ name: 'tasks', query: { task_id: store.refreshTask?.id } })">打开任务详情</el-button>
      </template>
    </div>

    <div class="content-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="车载 MR 在线状态" name="mrs">
          <div class="toolbar">
            <el-input v-model="store.filters.query" clearable placeholder="列车 / MR / AP / 站点 / MAC" @keyup.enter="store.applyFilters" />
            <el-select v-model="store.filters.online_status" clearable placeholder="MR 状态">
              <el-option label="在线" value="online" /><el-option label="离线" value="offline" />
              <el-option label="数据过期" value="stale" /><el-option label="未知" value="unknown" />
            </el-select>
            <el-input v-model="store.filters.station" clearable placeholder="站点" />
            <el-input v-model="store.filters.section" clearable placeholder="区间" />
            <el-checkbox v-model="store.filters.unmatched_only">只看未匹配</el-checkbox>
            <el-checkbox v-model="store.filters.offline_ap_only">关联离线 AP</el-checkbox>
            <el-checkbox v-model="store.filters.optical_anomaly_only">光衰异常</el-checkbox>
            <el-button type="primary" @click="store.applyFilters">应用</el-button>
          </div>
          <el-table v-loading="store.loading" :data="store.mrs" stripe height="calc(100vh - 535px)" empty-text="暂无车载 MR 数据">
            <el-table-column prop="train_display_name" label="列车" width="90" fixed="left" />
            <el-table-column prop="mr_name" label="MR 名称" min-width="175" fixed="left" />
            <el-table-column prop="car_end" label="端别" width="75" />
            <el-table-column label="在线状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.online_status)">{{ mrStatusLabel(row.online_status) }}</el-tag></template></el-table-column>
            <el-table-column prop="peer_ap_name" label="当前轨旁 AP" min-width="165"><template #default="{ row }">{{ display(row.peer_ap_name) }}</template></el-table-column>
            <el-table-column prop="peer_ap_mac" label="轨旁 AP MAC" min-width="145"><template #default="{ row }">{{ display(row.peer_ap_mac) }}</template></el-table-column>
            <el-table-column prop="mesh_radio" label="Mesh Radio" width="120"><template #default="{ row }">{{ display(row.mesh_radio) }}</template></el-table-column>
            <el-table-column prop="rssi" label="RSSI" width="75"><template #default="{ row }">{{ display(row.rssi) }}</template></el-table-column>
            <el-table-column prop="link_status" label="链路状态" width="110"><template #default="{ row }">{{ display(row.link_status) }}</template></el-table-column>
            <el-table-column prop="station" label="站点" min-width="125"><template #default="{ row }">{{ display(row.station) }}</template></el-table-column>
            <el-table-column prop="section" label="区间" min-width="145"><template #default="{ row }">{{ display(row.section) }}</template></el-table-column>
            <el-table-column prop="mileage" label="里程" width="105"><template #default="{ row }">{{ display(row.mileage) }}</template></el-table-column>
            <el-table-column prop="line_side" label="线路方向" width="105"><template #default="{ row }">{{ display(row.line_side) }}</template></el-table-column>
            <el-table-column label="轨旁 AP 状态" width="120"><template #default="{ row }"><el-tag :type="statusType(row.ap_online_status)">{{ apStatusLabel(row.ap_online_status) }}</el-tag></template></el-table-column>
            <el-table-column prop="optical_status" label="光衰状态" width="105" />
            <el-table-column label="最近更新" width="170"><template #default="{ row }">{{ formatTime(row.last_seen_at) }}</template></el-table-column>
            <el-table-column label="匹配方式" width="115"><template #default="{ row }">{{ matchLabel(row.match_method) }}</template></el-table-column>
            <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openMr(row)">详情</el-button></template></el-table-column>
          </el-table>
          <div class="pagination"><span>共 {{ store.mrTotal }} 条</span><el-pagination :current-page="store.filters.page" :page-size="store.filters.page_size" layout="prev, pager, next" :total="store.mrTotal" @current-change="store.setMrPage" /></div>
        </el-tab-pane>

        <el-tab-pane label="当前链路" name="links">
          <div class="toolbar compact">
            <el-input v-model="store.linkFilters.query" clearable placeholder="MR / AP / MAC / 位置" @keyup.enter="store.applyFilters" />
            <el-select v-model="store.linkFilters.match_status" clearable placeholder="匹配状态"><el-option label="已匹配" value="matched" /><el-option label="未匹配" value="unmatched" /></el-select>
            <el-button type="primary" @click="store.applyFilters">应用</el-button>
          </div>
          <el-table :data="store.links" stripe height="calc(100vh - 520px)" empty-text="暂无当前 Mesh-Link">
            <el-table-column prop="mr_name" label="MR 名称" min-width="175" fixed="left" />
            <el-table-column prop="mr_mac" label="MR MAC" min-width="145" />
            <el-table-column prop="peer_ap_name" label="轨旁 AP" min-width="160" />
            <el-table-column prop="peer_ap_mac" label="轨旁 AP MAC" min-width="145"><template #default="{ row }">{{ display(row.peer_ap_mac) }}</template></el-table-column>
            <el-table-column prop="peer_radio" label="Mesh Radio" width="120"><template #default="{ row }">{{ display(row.peer_radio) }}</template></el-table-column>
            <el-table-column prop="rssi" label="RSSI" width="75"><template #default="{ row }">{{ display(row.rssi) }}</template></el-table-column>
            <el-table-column prop="link_status" label="链路状态" width="110" />
            <el-table-column prop="channel" label="信道" width="75"><template #default="{ row }">{{ display(row.channel) }}</template></el-table-column>
            <el-table-column prop="bandwidth" label="带宽" width="80"><template #default="{ row }">{{ display(row.bandwidth) }}</template></el-table-column>
            <el-table-column prop="station" label="站点" min-width="125" />
            <el-table-column prop="section" label="区间" min-width="145"><template #default="{ row }">{{ display(row.section) }}</template></el-table-column>
            <el-table-column prop="mileage" label="里程" width="105"><template #default="{ row }">{{ display(row.mileage) }}</template></el-table-column>
            <el-table-column prop="ap_online_status" label="轨旁 AP 状态" width="120" />
            <el-table-column prop="optical_status" label="光衰" width="90" />
            <el-table-column label="数据状态" width="95"><template #default="{ row }"><el-tag :type="statusType(row.data_status)">{{ dataStatusLabel(row.data_status) }}</el-tag></template></el-table-column>
          </el-table>
          <div class="pagination"><span>共 {{ store.linkTotal }} 条</span><el-pagination :current-page="store.linkFilters.page" :page-size="store.linkFilters.page_size" layout="prev, pager, next" :total="store.linkTotal" @current-change="store.setLinkPage" /></div>
        </el-tab-pane>

        <el-tab-pane label="最近快照" name="snapshots">
          <el-table :data="store.snapshots" stripe height="calc(100vh - 425px)" empty-text="暂无 Mesh-Link 快照">
            <el-table-column prop="id" label="快照 ID" width="90" />
            <el-table-column prop="controller_name" label="AC" min-width="160" />
            <el-table-column label="采集时间" width="180"><template #default="{ row }">{{ formatTime(row.collected_at) }}</template></el-table-column>
            <el-table-column prop="link_count" label="链路数" width="85" />
            <el-table-column prop="parse_status" label="解析状态" width="105" />
            <el-table-column label="数据状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.data_status)">{{ dataStatusLabel(row.data_status) }}</el-tag></template></el-table-column>
            <el-table-column prop="source_reference" label="来源标识" min-width="220" />
            <el-table-column prop="error_summary" label="错误摘要" min-width="200" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-collapse class="raw-panel" @change="handleRawChange">
      <el-collapse-item title="最新 Mesh-Link 原始输出" name="raw">
        <p v-if="!store.rawTail?.available" class="empty-raw">{{ store.rawTail?.message || '暂无 Mesh-Link 原始数据' }}</p>
        <pre v-else>{{ store.rawTail.lines.join('\n') }}</pre>
      </el-collapse-item>
    </el-collapse>

    <el-drawer v-model="detailVisible" title="车载 MR 链路详情" size="min(920px, 95vw)">
      <div v-loading="store.detailLoading">
        <template v-if="store.selected">
          <div class="detail-title"><div><h2>{{ store.selected.mr.mr_name }}</h2><p>{{ store.selected.mr.train_display_name }} · {{ store.selected.mr.car_end }}</p></div><el-tag :type="statusType(store.selected.mr.online_status)" size="large">{{ mrStatusLabel(store.selected.mr.online_status) }}</el-tag></div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="MR MAC">{{ display(store.selected.mr.mr_mac) }}</el-descriptions-item>
            <el-descriptions-item label="管理 IP">{{ display(store.selected.mr.management_ip) }}</el-descriptions-item>
            <el-descriptions-item label="当前轨旁 AP">{{ display(store.selected.mr.peer_ap_name) }}</el-descriptions-item>
            <el-descriptions-item label="Mesh Radio">{{ display(store.selected.mr.mesh_radio) }}</el-descriptions-item>
            <el-descriptions-item label="站点/区间">{{ display([store.selected.mr.station, store.selected.mr.section].filter(Boolean).join(' / ')) }}</el-descriptions-item>
            <el-descriptions-item label="最近更新">{{ formatTime(store.selected.mr.last_seen_at) }}</el-descriptions-item>
          </el-descriptions>
          <div class="detail-actions">
            <el-button v-if="store.selected.mr.peer_ap_id" @click="router.push({ path: '/ac-management', query: { ap: store.selected?.mr.peer_ap_id } })">查看 FIT-AP 详情</el-button>
            <el-button v-if="store.selected.mr.mr_device_id" @click="router.push({ path: '/rail-transit/online-mr', query: { device_id: store.selected?.mr.mr_device_id } })">查看 Online MR</el-button>
          </div>
          <h3>当前快照链路</h3>
          <el-table :data="store.selected.current_links" border empty-text="当前快照无链路">
            <el-table-column prop="peer_ap_name" label="轨旁 AP" min-width="155" />
            <el-table-column prop="peer_radio" label="Mesh Radio" width="120" />
            <el-table-column prop="rssi" label="RSSI" width="75" />
            <el-table-column prop="link_status" label="状态" width="110" />
            <el-table-column prop="station" label="站点" min-width="120" />
            <el-table-column prop="section" label="区间" min-width="140" />
          </el-table>
          <h3>最近上线、离线和位置变化</h3>
          <el-table :data="store.selected.recent_events" border empty-text="暂无历史事件">
            <el-table-column prop="event_time" label="时间" width="175" />
            <el-table-column prop="event_type" label="事件" width="115" />
            <el-table-column prop="ap_name" label="轨旁 AP" min-width="150" />
            <el-table-column prop="station" label="站点" min-width="120" />
            <el-table-column prop="rssi" label="RSSI" width="75" />
          </el-table>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.mesh-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.page-heading, .source-strip, .toolbar, .pagination, .detail-title, .detail-actions, .refresh-actions { display: flex; align-items: center; gap: 12px; }
.page-heading { justify-content: space-between; }
.refresh-actions { flex-wrap: wrap; justify-content: flex-end; }.refresh-actions .el-select { width: 200px; }
.page-heading h1, .detail-title h2 { margin: 2px 0 6px; }
.page-heading p, .detail-title p, .empty-raw { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.summary-grid { display: grid; grid-template-columns: repeat(8, minmax(120px, 1fr)); gap: 10px; }
.metric, .content-card, .raw-panel { background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 12px; }
.metric { padding: 14px; }
.metric span { display: block; color: var(--el-text-color-secondary); font-size: 12px; }
.metric strong { display: block; margin-top: 7px; font-size: 24px; }
.metric.good strong { color: var(--el-color-success); }.metric.bad strong { color: var(--el-color-danger); }.metric.warn strong { color: var(--el-color-warning); }
.source-strip { flex-wrap: wrap; padding: 10px 14px; background: var(--el-fill-color-light); border-radius: 10px; font-size: 13px; }
.content-card { padding: 0 16px 14px; overflow: hidden; }
.toolbar { flex-wrap: wrap; margin-bottom: 12px; }.toolbar .el-input { width: 250px; }.toolbar .el-select { width: 135px; }.toolbar.compact .el-input { width: 300px; }
.pagination { justify-content: space-between; padding-top: 12px; color: var(--el-text-color-secondary); }
.raw-panel { padding: 0 14px; }.raw-panel pre { max-height: 360px; overflow: auto; margin: 0; padding: 12px; background: var(--nc-bg-code); color: var(--nc-text-code); border-radius: 8px; font: 12px/1.6 Consolas, monospace; }.empty-raw { padding: 12px 0; }
.detail-title { justify-content: space-between; margin-bottom: 16px; }.detail-actions { margin: 14px 0; }.detail-title + .el-descriptions { margin-bottom: 12px; }
@media (max-width: 1500px) { .summary-grid { grid-template-columns: repeat(4, minmax(140px, 1fr)); } }
@media (max-width: 900px) { .summary-grid { grid-template-columns: repeat(2, minmax(130px, 1fr)); }.page-heading { align-items: flex-start; flex-direction: column; } }
</style>
