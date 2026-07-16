<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Refresh, Setting, View } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'

import { isFeatureEnabled } from '../../features'
import { useAcManagementStore } from '../../stores/acManagement'
import type { AcAp, AcConfigSnapshot } from '../../types/acManagement'

const store = useAcManagementStore()
const route = useRoute()
const activeTab = ref(route.name === 'ac-optical' ? 'optical' : 'aps')
const detailVisible = ref(false)
const configVisible = ref(false)
const configSearch = ref('')
const currentMatch = ref(-1)
const selectedApIds = ref(new Set<string>())

interface TableColumn { key: string; label: string; width: number; sortable?: boolean }

const columns: TableColumn[] = [
  { key: 'name', label: 'AP 名称', width: 190, sortable: true },
  { key: 'ip', label: 'AP IP', width: 130, sortable: true },
  { key: 'mac', label: 'AP MAC', width: 150 },
  { key: 'status', label: '状态', width: 105, sortable: true },
  { key: 'model', label: '型号', width: 120 },
  { key: 'radio1_status', label: 'Mesh Radio 1 状态', width: 145 },
  { key: 'radio2_status', label: 'Mesh Radio 2 状态', width: 145 },
  { key: 'radio1_channel', label: 'Mesh Radio 1 信道', width: 140 },
  { key: 'radio2_channel', label: 'Mesh Radio 2 信道', width: 140 },
  { key: 'radio1_power', label: 'Mesh Radio 1 功率', width: 140 },
  { key: 'radio2_power', label: 'Mesh Radio 2 功率', width: 140 },
  { key: 'station', label: '归属站点', width: 140, sortable: true },
  { key: 'section', label: '归属区间', width: 170, sortable: true },
  { key: 'mileage', label: '里程', width: 110, sortable: true },
  { key: 'direction', label: '线路方向', width: 110 },
  { key: 'switch_name', label: '连接交换机', width: 150 },
  { key: 'switch_interface', label: '连接端口', width: 150 },
  { key: 'lldp_status', label: 'LLDP 状态', width: 120 },
  { key: 'optical_status', label: '光衰状态', width: 125, sortable: true },
  { key: 'optical_rx_power', label: '光衰值', width: 110, sortable: true },
  { key: 'updated_at', label: '最近更新时间', width: 180, sortable: true },
]

const columnVisibility = reactive<Record<string, boolean>>(
  Object.fromEntries(columns.map((column) => [column.key, true])),
)
const visibleColumns = computed(() => columns.filter((column) => columnVisibility[column.key]))
const detailRadios = computed(() => (store.selected?.radios || []).filter((radio) => radio.radio_id <= 2))
const configLines = computed(() => (store.configContent?.content || '').split('\n'))
const diffLines = computed(() => (store.configDiff?.raw_diff || '').split('\n'))
const taskActive = computed(() => !!store.refreshTask && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(store.refreshTask.status))
const taskCollection = computed(() => (store.refreshTask?.result_summary.collection || {}) as Record<string, unknown>)
const taskLabel = computed(() => ({
  ac_info_refresh: 'AC 信息更新',
  ac_fit_ap_resources_refresh: 'FIT-AP 资源更新',
  ac_fit_ap_detail_refresh: 'FIT-AP 深度更新',
  ac_fit_ap_optical_refresh: 'FIT-AP 光衰更新',
  ac_fit_ap_delete_many: 'FIT-AP 批量删除',
}[store.refreshTask?.action || ''] || 'AC / FIT-AP 更新'))
const matchingLines = computed(() => {
  const needle = configSearch.value.trim().toLowerCase()
  if (!needle) return []
  return configLines.value.flatMap((line, index) => (line.toLowerCase().includes(needle) ? [index] : []))
})

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  store.startPolling()
  const apId = typeof route.query.ap === 'string' ? route.query.ap : ''
  if (apId) {
    detailVisible.value = true
    void store.selectAp(apId)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
}

function clearFilters(): void {
  Object.assign(store.filters, {
    query: '',
    status: '',
    station: '',
    section: '',
    model: '',
    switch: '',
    optical_status: '',
    sort_by: 'name',
    sort_order: 'asc',
  })
  store.applyFilters()
}

function setApSelected(apId: string, selected: boolean): void {
  const next = new Set(selectedApIds.value)
  if (selected) next.add(apId)
  else next.delete(apId)
  selectedApIds.value = next
}

function selectCurrentPage(): void {
  const next = new Set(selectedApIds.value)
  for (const ap of store.aps) next.add(ap.id)
  selectedApIds.value = next
}

function invertCurrentPage(): void {
  const next = new Set(selectedApIds.value)
  for (const ap of store.aps) {
    if (next.has(ap.id)) next.delete(ap.id)
    else next.add(ap.id)
  }
  selectedApIds.value = next
}

async function deleteSelectedAps(): Promise<void> {
  const apIds = [...selectedApIds.value]
  if (!apIds.length) return
  try {
    await ElMessageBox.confirm(
      `确认从当前 AC 资源库删除选中的 ${apIds.length} 个 FIT-AP 及其关联光衰/元数据？`,
      '批量删除 FIT-AP',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await store.startFitApDelete(apIds)
  if (store.refreshTask?.action === 'ac_fit_ap_delete_many') selectedApIds.value = new Set()
}

function handleSort(event: { prop: string; order: 'ascending' | 'descending' | null }): void {
  const sortMap: Record<string, string> = {
    name: 'name',
    ip: 'ip',
    status: 'status',
    station: 'station',
    section: 'section',
    mileage: 'mileage',
    optical_status: 'optical_status',
    optical_rx_power: 'optical_value',
    updated_at: 'updated_at',
  }
  store.filters.sort_by = sortMap[event.prop] || 'name'
  store.filters.sort_order = event.order === 'descending' ? 'desc' : 'asc'
  store.applyFilters()
}

async function openDetail(row: AcAp): Promise<void> {
  detailVisible.value = true
  await store.selectAp(row.id)
}

async function openConfig(snapshot: AcConfigSnapshot): Promise<void> {
  configVisible.value = true
  configSearch.value = ''
  currentMatch.value = -1
  await store.loadConfig(snapshot.id)
}

async function openDiff(snapshot: AcConfigSnapshot): Promise<void> {
  configVisible.value = true
  configSearch.value = ''
  currentMatch.value = -1
  await store.loadDiff(snapshot.id)
}

async function nextConfigMatch(): Promise<void> {
  if (!matchingLines.value.length) return
  currentMatch.value = (currentMatch.value + 1) % matchingLines.value.length
  await nextTick()
  document.querySelector(`[data-config-line="${matchingLines.value[currentMatch.value]}"]`)?.scrollIntoView({ block: 'center' })
}

function display(value: unknown): string {
  return value === null || value === undefined || value === '' ? '--' : String(value)
}

function statusLabel(value: string): string {
  return { online: '在线', offline: '离线', unauthenticated: '未认证', unknown: '无数据' }[value] || value || '无数据'
}

function opticalLabel(value: string): string {
  return { normal: '正常', warning: '告警', critical: '严重', no_data: '无数据', unrelated: '未关联 AP 离线' }[value] || value
}

function statusType(value: string): 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'online' || value === 'normal') return 'success'
  if (value === 'unauthenticated' || value === 'warning' || value === 'unrelated') return 'warning'
  if (value === 'offline' || value === 'critical') return 'danger'
  return 'info'
}

function formatTime(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'diff-file'
  if (line.startsWith('+')) return 'diff-added'
  if (line.startsWith('-')) return 'diff-removed'
  if (line.startsWith('@@')) return 'diff-range'
  return ''
}
</script>

<template>
  <section class="ac-management">
    <el-alert
      title="AC / FIT-AP 资源"
      description="“更新 FIT-AP 资源”通过后台任务连接所选 H3C AC，保留命令原始记录并持久化 AP、Radio、连接记录与 LLDP 结果；任务可取消并可在页面重启后恢复。"
      type="info"
      :closable="false"
      show-icon
      class="readonly-alert"
    />

    <div class="page-toolbar">
      <div>
        <h2>{{ store.activeAc?.name || 'AC 管理' }}</h2>
        <p>{{ store.summary?.site_id || '--' }} · 数据源：{{ store.activeAc?.data_source || 'SQLite 已采集数据' }} · 更新于 {{ formatTime(store.summary?.updated_at || '') }}</p>
      </div>
      <div class="toolbar-actions">
        <el-select :model-value="store.filters.ac_id" placeholder="选择 AC" style="width: 220px" @change="store.setAcId">
          <el-option v-for="ac in store.summary?.acs || []" :key="ac.id" :label="`${ac.name} (${ac.management_ip || '--'})`" :value="ac.id" />
        </el-select>
        <el-button :icon="Refresh" :loading="store.loading" @click="store.manualRefresh">刷新已有数据</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startAcInfoRefresh">更新 AC 信息</el-button>
        <el-button type="primary" :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startFitApRefresh">更新 FIT-AP 资源</el-button>
        <el-button :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startOpticalRefresh">更新光衰</el-button>
      </div>
    </div>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />
    <div v-if="store.refreshTask" class="task-panel">
      <div class="task-heading">
        <div>
          <strong>{{ taskLabel }} · {{ store.refreshTask.status }}</strong>
          <p>{{ store.refreshTask.message || store.refreshTask.error_message || store.refreshTask.stage || '等待任务事件…' }}</p>
        </div>
        <el-button v-if="taskActive" type="danger" plain @click="store.cancelRefreshTask">取消任务</el-button>
      </div>
      <el-progress :percentage="store.refreshTask.progress" :status="store.refreshTask.status === 'FAILED' ? 'exception' : store.refreshTask.status === 'COMPLETED' ? 'success' : undefined" />
      <p v-if="store.refreshTask.status === 'COMPLETED' && store.refreshTask.action === 'ac_info_refresh'" class="task-result">
        AC 信息已持久化；HTTPS 端口 {{ taskCollection.https_port || '未解析' }}。
      </p>
      <p v-else-if="store.refreshTask.status === 'COMPLETED' && store.refreshTask.action === 'ac_fit_ap_detail_refresh'" class="task-result">
        已深度更新选中 AP，BSSID {{ taskCollection.bbssid_rows_parsed || 0 }} 条，LLDP {{ taskCollection.lldp_rows_parsed || 0 }} 条。
      </p>
      <p v-else-if="store.refreshTask.status === 'COMPLETED' && store.refreshTask.action === 'ac_fit_ap_optical_refresh'" class="task-result">
        已更新 {{ taskCollection.optical_rows_updated || 0 }} 条光衰记录，失败 {{ taskCollection.failed_aps || 0 }} 个 AP。
      </p>
      <p v-else-if="store.refreshTask.status === 'COMPLETED' && store.refreshTask.action === 'ac_fit_ap_delete_many'" class="task-result">
        已删除 {{ store.refreshTask.result_summary.count || 0 }} 个 FIT-AP。
      </p>
      <p v-else-if="store.refreshTask.status === 'COMPLETED'" class="task-result">
        已更新 {{ taskCollection.fit_ap_resources_updated || 0 }} 个 AP，LLDP {{ taskCollection.lldp_rows_parsed || 0 }} 条，未认证 AP {{ taskCollection.unauthenticated_rows_updated || 0 }} 条。
      </p>
      <el-alert v-if="Array.isArray(taskCollection.failed_commands) && taskCollection.failed_commands.length" :title="`部分命令失败：${taskCollection.failed_commands.join('、')}`" type="warning" :closable="false" show-icon />
    </div>
    <el-empty v-if="store.summary?.message && !store.summary.acs.length" :description="store.summary.message" />

    <el-descriptions v-else-if="store.activeAc" :column="4" border class="ac-info-strip">
      <el-descriptions-item label="AC 型号">{{ display(store.activeAc.model) }}</el-descriptions-item>
      <el-descriptions-item label="软件版本">{{ display(store.activeAc.software_version) }}</el-descriptions-item>
      <el-descriptions-item label="CPU 使用率">{{ display(store.activeAc.cpu_usage) }}</el-descriptions-item>
      <el-descriptions-item label="内存使用率">{{ display(store.activeAc.memory_usage) }}</el-descriptions-item>
      <el-descriptions-item label="管理地址">{{ display(store.activeAc.management_ip) }}</el-descriptions-item>
      <el-descriptions-item label="HTTPS 端口">{{ display(store.activeAc.https_port) }}</el-descriptions-item>
    </el-descriptions>

    <div v-if="store.activeAc" class="summary-grid">
      <article><span>AP 总数</span><strong>{{ store.activeAc?.ap_total || 0 }}</strong></article>
      <article class="success"><span>在线 AP</span><strong>{{ store.activeAc?.online_aps || 0 }}</strong></article>
      <article class="danger"><span>离线 AP</span><strong>{{ store.activeAc?.offline_aps || 0 }}</strong></article>
      <article class="warning"><span>未认证 AP</span><strong>{{ store.activeAc?.unauthenticated_aps || 0 }}</strong></article>
      <article><span>Radio 总数</span><strong>{{ store.activeAc?.radio_total || 0 }}</strong></article>
      <article class="danger"><span>关联光衰异常</span><strong>{{ store.activeAc?.optical_anomalies || 0 }}</strong></article>
    </div>

    <div class="content-card">
      <el-tabs v-model="activeTab" class="ac-tabs">
        <el-tab-pane label="FIT-AP 资源" name="aps">
          <div class="filter-bar">
            <el-input v-model="store.filters.query" clearable placeholder="AP 名称 / IP / MAC" @keyup.enter="store.applyFilters" />
            <el-select v-model="store.filters.status" clearable placeholder="AP 状态">
              <el-option label="在线" value="online" /><el-option label="离线" value="offline" /><el-option label="未认证" value="unauthenticated" />
            </el-select>
            <el-select v-model="store.filters.optical_status" clearable placeholder="光衰状态">
              <el-option label="正常" value="normal" /><el-option label="告警" value="warning" /><el-option label="严重" value="critical" />
              <el-option label="无数据" value="no_data" /><el-option label="未关联 AP 离线" value="unrelated" />
            </el-select>
            <el-input v-model="store.filters.station" clearable placeholder="归属站点" />
            <el-input v-model="store.filters.section" clearable placeholder="归属区间" />
            <el-input v-model="store.filters.model" clearable placeholder="型号" />
            <el-input v-model="store.filters.switch" clearable placeholder="交换机" />
            <el-button type="primary" @click="store.applyFilters">应用筛选</el-button>
            <el-button @click="clearFilters">清除</el-button>
            <el-button @click="selectCurrentPage">选择本页</el-button>
            <el-button @click="invertCurrentPage">反选本页</el-button>
            <el-button :disabled="!selectedApIds.size" @click="selectedApIds = new Set()">清空选择</el-button>
            <el-button
              v-if="isFeatureEnabled('web.ac_fit_ap_delete')"
              type="danger"
              plain
              :loading="store.refreshStarting"
              :disabled="!selectedApIds.size || taskActive"
              @click="deleteSelectedAps"
            >批量删除（{{ selectedApIds.size }}）</el-button>
            <el-popover placement="bottom-end" :width="260" trigger="click">
              <template #reference><el-button :icon="Setting">列显隐</el-button></template>
              <div class="column-picker">
                <el-checkbox v-for="column in columns" :key="column.key" v-model="columnVisibility[column.key]">{{ column.label }}</el-checkbox>
              </div>
            </el-popover>
          </div>

          <el-table
            v-loading="store.loading"
            :data="store.aps"
            stripe
            height="calc(100vh - 455px)"
            empty-text="暂无 FIT-AP 资源数据"
            @sort-change="handleSort"
          >
            <el-table-column label="选择" width="62" fixed="left">
              <template #default="{ row }">
                <el-checkbox :model-value="selectedApIds.has(row.id)" @change="setApSelected(row.id, Boolean($event))" />
              </template>
            </el-table-column>
            <el-table-column
              v-for="column in visibleColumns"
              :key="column.key"
              :prop="column.key"
              :label="column.label"
              :min-width="column.width"
              :sortable="column.sortable ? 'custom' : false"
              show-overflow-tooltip
              resizable
            >
              <template #default="{ row }">
                <el-tag v-if="column.key === 'status'" :type="statusType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
                <el-tag v-else-if="column.key === 'optical_status'" :type="statusType(row.optical_status)" effect="light">{{ opticalLabel(row.optical_status) }}</el-tag>
                <span v-else>{{ display(row[column.key]) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="82" fixed="right">
              <template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template>
            </el-table-column>
          </el-table>
          <div class="pagination-row">
            <span>共 {{ store.total }} 条</span>
            <el-pagination
              :current-page="store.filters.page"
              :page-size="store.filters.page_size"
              :page-sizes="[20, 50, 100, 200]"
              layout="sizes, prev, pager, next"
              :total="store.total"
              @current-change="store.setPage"
              @size-change="store.setPageSize"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="配置采集与对比" name="config">
          <div class="config-toolbar">
            <div><h3>配置快照</h3><p>只读取当前局点受控目录；配置正文和差异按选择加载，不轮询大文本。</p></div>
            <div class="toolbar-actions">
              <el-select :model-value="store.snapshotType" clearable placeholder="配置类型" style="width: 145px" @change="store.setSnapshotType">
                <el-option label="运行配置" value="running" /><el-option label="保存配置" value="saved" /><el-option label="差异" value="diff" />
              </el-select>
              <el-button :icon="Refresh" @click="store.refreshSnapshots">刷新历史</el-button>
            </div>
          </div>
          <el-table :data="store.snapshots" stripe empty-text="暂无 AC 配置快照" height="calc(100vh - 405px)">
            <el-table-column label="采集时间" width="180"><template #default="{ row }">{{ formatTime(row.timestamp) }}</template></el-table-column>
            <el-table-column prop="ac_name" label="AC 名称" min-width="180" />
            <el-table-column prop="type" label="配置类型" width="110" />
            <el-table-column label="状态" width="105"><template #default="{ row }"><el-tag :type="row.status === 'AVAILABLE' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column label="文件大小" width="110"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
            <el-table-column prop="path_id" label="路径标识" min-width="140" />
            <el-table-column prop="error_summary" label="错误摘要" min-width="220" show-overflow-tooltip />
            <el-table-column label="只读操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openConfig(row)">查看</el-button>
                <el-button link type="primary" @click="openDiff(row)">对比</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-row">
            <span>共 {{ store.snapshotTotal }} 条</span>
            <el-pagination :current-page="store.snapshotPage" :page-size="store.snapshotPageSize" layout="prev, pager, next" :total="store.snapshotTotal" @current-change="store.setSnapshotPage" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="FIT-AP 光衰" name="optical">
          <div class="config-toolbar">
            <div><h3>FIT-AP 光衰</h3><p>显示 AC 关联的 AP 侧光模块结果；刷新通过持久化后台任务执行。</p></div>
            <div class="toolbar-actions">
              <el-select v-model="store.filters.optical_status" clearable placeholder="光衰状态" style="width: 155px" @change="store.applyFilters">
                <el-option label="正常" value="normal" /><el-option label="告警" value="warning" /><el-option label="严重" value="critical" />
                <el-option label="无数据" value="no_data" /><el-option label="未关联 AP 离线" value="unrelated" />
              </el-select>
              <el-button type="primary" :icon="Refresh" :loading="store.refreshStarting" :disabled="!store.filters.ac_id || taskActive" @click="store.startOpticalRefresh">更新光衰</el-button>
            </div>
          </div>
          <el-table :data="store.aps" stripe height="calc(100vh - 405px)" empty-text="暂无 FIT-AP 光衰数据">
            <el-table-column prop="name" label="AP 名称" min-width="190" />
            <el-table-column prop="status" label="AP 状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
            <el-table-column prop="switch_name" label="关联交换机" min-width="160" />
            <el-table-column prop="switch_interface" label="关联端口" min-width="170" />
            <el-table-column prop="optical_rx_power" label="Rx Power" width="120"><template #default="{ row }">{{ display(row.optical_rx_power) }}</template></el-table-column>
            <el-table-column prop="optical_status" label="光衰状态" width="130"><template #default="{ row }"><el-tag :type="statusType(row.optical_status)">{{ opticalLabel(row.optical_status) }}</el-tag></template></el-table-column>
            <el-table-column prop="updated_at" label="更新时间" min-width="180"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
            <el-table-column label="操作" width="82" fixed="right"><template #default="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-drawer v-model="detailVisible" title="FIT-AP 详情" size="min(920px, 95vw)">
      <div v-loading="store.detailLoading">
        <template v-if="store.selected">
          <div class="detail-heading">
            <div><h2>{{ store.selected.ap.name }}</h2><p>{{ store.selected.ap.ip || '--' }} · {{ store.selected.ap.mac || '--' }}</p></div>
            <div class="toolbar-actions">
              <el-tag :type="statusType(store.selected.ap.status)" size="large">{{ statusLabel(store.selected.ap.status) }}</el-tag>
              <el-button type="primary" :icon="Refresh" :loading="store.refreshStarting" :disabled="taskActive" @click="store.startFitApDetailRefresh">深度更新</el-button>
            </div>
          </div>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="型号">{{ display(store.selected.ap.model) }}</el-descriptions-item>
            <el-descriptions-item label="上线时长">{{ display(store.selected.ap.online_time) }}</el-descriptions-item>
            <el-descriptions-item label="归属站点">{{ display(store.selected.ap.station) }}</el-descriptions-item>
            <el-descriptions-item label="归属区间">{{ display(store.selected.ap.section) }}</el-descriptions-item>
            <el-descriptions-item label="里程">{{ display(store.selected.ap.mileage) }}</el-descriptions-item>
            <el-descriptions-item label="线路方向">{{ display(store.selected.ap.direction) }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="detail-section-title">AC 连接记录</h3>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="连接状态">{{ display(store.selected.connection.state) }}</el-descriptions-item>
            <el-descriptions-item label="连接 IP">{{ display(store.selected.connection.ip_address) }}</el-descriptions-item>
            <el-descriptions-item label="最近建链时间">{{ display(store.selected.connection.connected_at) }}</el-descriptions-item>
            <el-descriptions-item label="数据更新时间">{{ formatTime(store.selected.connection.updated_at) }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="detail-section-title">Mesh Radio 1 / 2</h3>
          <el-table :data="detailRadios" border>
            <el-table-column prop="radio_id" label="Mesh Radio ID" width="125" />
            <el-table-column prop="status" label="状态" min-width="90"><template #default="{ row }">{{ display(row.status) }}</template></el-table-column>
            <el-table-column prop="mode" label="模式" min-width="90"><template #default="{ row }">{{ display(row.mode) }}</template></el-table-column>
            <el-table-column prop="band" label="频段" min-width="90"><template #default="{ row }">{{ display(row.band) }}</template></el-table-column>
            <el-table-column prop="channel" label="信道" min-width="90" />
            <el-table-column prop="bandwidth" label="带宽" min-width="90" />
            <el-table-column prop="usage" label="利用率 (%)" min-width="100" />
            <el-table-column prop="tx_power" label="功率" min-width="90" />
            <el-table-column prop="clients" label="客户端" min-width="90" />
            <el-table-column prop="bssid" label="BSSID" min-width="145" />
          </el-table>

          <h3 class="detail-section-title">LLDP / 端口</h3>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="交换机">{{ display(store.selected.lldp.switch_name) }}</el-descriptions-item>
            <el-descriptions-item label="交换机 IP">{{ display(store.selected.lldp.switch_ip) }}</el-descriptions-item>
            <el-descriptions-item label="接口">{{ display(store.selected.lldp.interface_name) }}</el-descriptions-item>
            <el-descriptions-item label="LLDP 邻居">{{ display(store.selected.lldp.lldp_neighbor) }}</el-descriptions-item>
            <el-descriptions-item label="端口状态">{{ display(store.selected.lldp.port_status) }}</el-descriptions-item>
            <el-descriptions-item label="VLAN">{{ display(store.selected.lldp.vlan) }}</el-descriptions-item>
            <el-descriptions-item label="光模块状态">{{ display(store.selected.lldp.optical_module_status) }}</el-descriptions-item>
            <el-descriptions-item label="LLDP 状态">{{ display(store.selected.lldp.match_status) }}</el-descriptions-item>
          </el-descriptions>

          <h3 class="detail-section-title">光衰</h3>
          <el-alert :title="store.selected.optical.anomaly_reason" :type="statusType(store.selected.optical.optical_status)" :closable="false" show-icon />
          <el-descriptions :column="2" border class="optical-detail">
            <el-descriptions-item label="Tx Power">{{ display(store.selected.optical.tx_power) }}</el-descriptions-item>
            <el-descriptions-item label="Rx Power">{{ display(store.selected.optical.rx_power) }}</el-descriptions-item>
            <el-descriptions-item label="交换机 Rx">{{ display(store.selected.optical.switch_rx_power) }}</el-descriptions-item>
            <el-descriptions-item label="阈值状态">{{ display(store.selected.optical.threshold_status) }}</el-descriptions-item>
            <el-descriptions-item label="温度">{{ display(store.selected.optical.temperature) }}</el-descriptions-item>
            <el-descriptions-item label="电压">{{ display(store.selected.optical.voltage) }}</el-descriptions-item>
            <el-descriptions-item label="偏置电流">{{ display(store.selected.optical.bias_current) }}</el-descriptions-item>
            <el-descriptions-item label="最近更新时间">{{ formatTime(store.selected.optical.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </div>
    </el-drawer>

    <el-drawer v-model="configVisible" title="AC 配置只读查看" size="min(1100px, 96vw)">
      <div v-loading="store.configLoading" class="config-viewer">
        <template v-if="store.configContent">
          <div class="config-searchbar">
            <el-input v-model="configSearch" clearable placeholder="搜索配置文本" />
            <el-button @click="nextConfigMatch">下一个匹配（{{ matchingLines.length }}）</el-button>
            <span>{{ store.configContent.snapshot.path_id }} · {{ store.configContent.total_chars }} 字符</span>
          </div>
          <div class="code-panel">
            <div
              v-for="(line, index) in configLines"
              :key="index"
              :data-config-line="index"
              :class="['config-line', { matched: matchingLines.includes(index), current: matchingLines[currentMatch] === index }]"
            ><span>{{ index + 1 }}</span><code>{{ line || ' ' }}</code></div>
          </div>
          <el-button v-if="store.configContent.next_offset" class="load-more" @click="store.loadMoreConfig">加载下一块</el-button>
        </template>
        <template v-else-if="store.configDiff">
          <div class="diff-summary">新增 {{ store.configDiff.added.length }} 行 · 删除 {{ store.configDiff.removed.length }} 行<span v-if="store.configDiff.truncated"> · 大文本已截断</span></div>
          <div class="code-panel diff-panel">
            <div v-for="(line, index) in diffLines" :key="index" :class="['config-line', diffLineClass(line)]"><span>{{ index + 1 }}</span><code>{{ line || ' ' }}</code></div>
          </div>
        </template>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.ac-management { max-width: 1780px; margin: 0 auto; }
.readonly-alert, .page-error { margin-bottom: 16px; }
.task-panel { margin-bottom: 16px; padding: 14px 16px; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.task-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
.task-heading p, .task-result { margin: 5px 0 0; color: #718096; font-size: 12px; }
.page-toolbar, .config-toolbar, .detail-heading, .config-searchbar, .pagination-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-toolbar { margin-bottom: 16px; }
.page-toolbar h2, .config-toolbar h3, .detail-heading h2 { margin: 0; }
.page-toolbar p, .config-toolbar p, .detail-heading p { margin: 5px 0 0; color: #718096; font-size: 12px; }
.toolbar-actions { display: flex; align-items: center; gap: 10px; }
.ac-info-strip { margin-bottom: 12px; }
.summary-grid { display: grid; grid-template-columns: repeat(6, minmax(125px, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-grid article { padding: 15px 17px; background: #fff; border: 1px solid #dfe7f1; border-top: 3px solid #71839a; border-radius: 10px; }
.summary-grid article.success { border-top-color: #28a06b; }
.summary-grid article.warning { border-top-color: #d99a24; }
.summary-grid article.danger { border-top-color: #d95656; }
.summary-grid span { display: block; color: #718096; font-size: 12px; }
.summary-grid strong { display: block; margin-top: 6px; color: #172033; font-size: 24px; }
.content-card { overflow: hidden; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.ac-tabs :deep(.el-tabs__header) { margin: 0; padding: 0 18px; }
.filter-bar { display: grid; grid-template-columns: minmax(220px, 1.5fr) repeat(6, minmax(115px, 1fr)) auto auto auto; gap: 8px; padding: 14px; border-bottom: 1px solid #edf1f6; }
.column-picker { display: grid; grid-template-columns: 1fr 1fr; max-height: 360px; overflow: auto; }
.column-picker :deep(.el-checkbox) { margin-right: 8px; }
.pagination-row { padding: 12px 16px; color: #718096; font-size: 12px; }
.config-toolbar { padding: 15px 18px; border-bottom: 1px solid #edf1f6; }
.detail-section-title { margin: 23px 0 10px; }
.optical-detail { margin-top: 12px; }
.config-viewer { min-height: 360px; }
.config-searchbar { position: sticky; top: 0; z-index: 2; padding: 10px 0; background: #fff; }
.config-searchbar .el-input { max-width: 360px; }
.config-searchbar span, .diff-summary { color: #718096; font-size: 12px; }
.code-panel { max-height: calc(100vh - 190px); overflow: auto; background: #101827; border-radius: 8px; color: #d9e2ed; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.config-line { display: grid; grid-template-columns: 58px minmax(max-content, 1fr); min-width: max-content; border-bottom: 1px solid #ffffff0a; }
.config-line > span { padding: 2px 10px; color: #748399; text-align: right; border-right: 1px solid #ffffff12; user-select: none; }
.config-line code { padding: 2px 12px; white-space: pre; }
.config-line.matched { background: #725e182b; }
.config-line.current { background: #a87f2255; }
.diff-added { color: #96e6b3; background: #1d6d3c28; }
.diff-removed { color: #ffabab; background: #8e303028; }
.diff-range { color: #9bbfff; }
.diff-file { color: #f0c77d; }
.diff-summary { margin-bottom: 10px; }
.load-more { display: block; margin: 12px auto 0; }
@media (max-width: 1400px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .filter-bar { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
}
@media (max-width: 900px) {
  .page-toolbar, .config-toolbar { align-items: flex-start; flex-direction: column; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); }
  .filter-bar { grid-template-columns: 1fr 1fr; }
  .toolbar-actions { flex-wrap: wrap; }
}
</style>
