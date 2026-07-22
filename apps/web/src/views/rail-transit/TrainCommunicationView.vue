<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTrainCommunicationCheck,
  getTrainCommunicationSummary,
  getTrainCommunicationTopology,
  listTrainCommunications,
  recoverTrainCommunicationChecks,
  startTrainCommunicationCheck,
} from '../../api/trainCommunication'
import FixedTrainTopology from '../../components/train-communication/FixedTrainTopology.vue'
import { isFeatureEnabled } from '../../features'
import type { TrainCommunicationRow, TrainCommunicationTopology, TopologyStatus } from '../../types/trainCommunication'
import CarNetworkPointTableDialog from './CarNetworkPointTableDialog.vue'

interface PointTableSavedPayload { trainId: string; revision: string; rowCount: number }

const router = useRouter()
const trainOptions = ref<TrainCommunicationRow[]>([])
const selectedTrainId = ref('')
const selectedTrain = computed(() => trainOptions.value.find((item) => item.train_id === selectedTrainId.value || item.canonical_train_id === selectedTrainId.value) ?? null)
const siteId = ref('')
const topology = ref<TrainCommunicationTopology | null>(null)
const loading = ref(false)
const loadingTrains = ref(false)
const checking = ref(false)
const error = ref('')
const notice = ref('')
const lastCheckTaskId = ref('')
const checkMessage = ref('')
const checkFailed = ref(false)
const refreshInterval = ref(0)
const lastUpdatedAt = ref('')
const pointTableVisible = ref(false)
const trainListCollapsed = ref(false)
let refreshTimer: number | null = null
let checkTimer: number | null = null
let checkRunId = 0
let disposed = false

const statusLabels: Record<TopologyStatus, string> = {
  normal: '正常',
  abnormal: '异常',
  checking: '检测中',
  stale: '数据过期',
  not_detected: '未检测',
  not_configured: '未配置',
}

const pointTableStatusLabel = computed(() => {
  if (!topology.value) return ''
  return topology.value.point_table_status === 'configured'
    ? '检测点表已配置'
    : topology.value.point_table_status === 'invalid'
      ? '检测点表不完整'
      : '检测点表未配置'
})
const pointTableAlertType = computed(() => topology.value?.point_table_status === 'invalid' ? 'error' : 'warning')
const canWritePointTable = computed(() => isFeatureEnabled('web.rail_car_network_point_table_write') && isFeatureEnabled('web.rail_task_control'))
const pointTableDisabledReason = computed(() => canWritePointTable.value ? '' : '点表写入功能未启用')
const canStartBlockReason = computed(() => {
  if (!isFeatureEnabled('web.rail_car_network_diagnostic_execute')) return '车内通信检测功能未启用'
  if (!isFeatureEnabled('web.rail_task_control')) return '统一任务中心未启用'
  if (checking.value) return '检测任务正在运行'
  if (!selectedTrainId.value) return '请选择列车'
  if (!selectedTrain.value) return '所选列车不在当前列车列表中，请刷新后重试'
  if (!topology.value) return '拓扑状态尚未加载'
  if (topology.value.point_table_status === 'missing') return '点表未配置'
  if (topology.value.point_table_status === 'invalid') return topology.value.point_table_message || '点表缺少节点或节点未绑定设备/地址'
  if (topology.value.point_table_missing_nodes.length) return `点表缺少节点：${topology.value.point_table_missing_nodes.join('、')}`
  if (![...topology.value.tc1_nodes, ...topology.value.tc2_nodes].some((node) => node.device_id || node.ip_address)) return '点表没有可执行检测的节点'
  return ''
})
const canStart = computed(() => !canStartBlockReason.value)

function statusLabel(status: TopologyStatus): string { return statusLabels[status] || '未检测' }
function formatTime(value: string | null | undefined): string { return value ? value.replace('T', ' ').replace(/\+00:00$/, '') : '未检测' }
function trainDisplayName(train: TrainCommunicationRow): string {
  const display = train.display_name || [train.train_name, train.train_no ? `${train.train_no}车` : ''].filter(Boolean).join(' / ') || train.train_id
  return display
}

function onlineStatusLabel(train: TrainCommunicationRow | null): string {
  if (!train) return '在线状态未知'
  if (train.data_status === 'STALE' || train.overall_status === 'STALE') return '数据过期'
  if (train.overall_status === 'BOTH_ONLINE') return '双端在线'
  if (train.overall_status === 'ONE_SIDE_ONLINE') return '单端在线'
  if (train.overall_status === 'BOTH_OFFLINE') return '当前离线'
  return '在线状态未知'
}

async function loadTrains(): Promise<void> {
  loadingTrains.value = true
  try {
    const [summary, page] = await Promise.all([
      getTrainCommunicationSummary(),
      listTrainCommunications({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' }),
    ])
    siteId.value = summary.site_id
    const previous = selectedTrainId.value
    trainOptions.value = page.items
    const preserved = page.items.find((item) => item.train_id === previous || item.canonical_train_id === previous)
    if (preserved) {
      selectedTrainId.value = preserved.train_id
    } else {
      selectedTrainId.value = page.items[0]?.train_id || ''
      if (previous && !selectedTrainId.value) {
        topology.value = null
        lastUpdatedAt.value = ''
        notice.value = '原选中列车已不在当前局点列车列表中'
      }
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '列车列表加载失败'
  } finally {
    loadingTrains.value = false
  }
}

async function loadTopologyForCurrentTrain(): Promise<void> {
  if (!selectedTrainId.value) {
    topology.value = null
    lastUpdatedAt.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    topology.value = await getTrainCommunicationTopology(selectedTrainId.value)
    lastUpdatedAt.value = topology.value.checked_at || topology.value.point_table_revision || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '车内通信拓扑状态加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshPageState(): Promise<void> {
  notice.value = ''
  await loadTrains()
  await loadTopologyForCurrentTrain()
}

function clearTimer(kind: 'refresh' | 'check'): void {
  const timer = kind === 'refresh' ? refreshTimer : checkTimer
  if (timer !== null) window.clearTimeout(timer)
  if (kind === 'refresh') refreshTimer = null
  else checkTimer = null
}

function scheduleRefresh(): void {
  clearTimer('refresh')
  if (disposed || !refreshInterval.value || !selectedTrainId.value) return
  refreshTimer = window.setTimeout(async () => {
    await refreshPageState()
    scheduleRefresh()
  }, refreshInterval.value * 1000)
}

function scheduleCheck(taskId: string): void {
  clearTimer('check')
  const runId = checkRunId
  checkTimer = window.setTimeout(async () => {
    try {
      const task = await getTrainCommunicationCheck(taskId)
      if (disposed || runId !== checkRunId) return
      const status = task.status.toUpperCase()
      const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED'].includes(status)
      checkFailed.value = terminal && status !== 'COMPLETED'
      checkMessage.value = checkFailed.value ? task.error_message || task.message || '车内通信检测失败' : task.message || ''
      if (terminal) {
        checking.value = false
        await loadTopologyForCurrentTrain()
        return
      }
      scheduleCheck(taskId)
    } catch (cause) {
      checking.value = false
      error.value = cause instanceof Error ? cause.message : '车内通信检测任务状态读取失败'
    }
  }, 1000)
}

async function recoverChecks(): Promise<void> {
  try {
    const tasks = await recoverTrainCommunicationChecks()
    const current = tasks.find((item) => !['COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED'].includes(item.status.toUpperCase()))
    if (!current) return
    lastCheckTaskId.value = current.task_id
    checking.value = true
    checkRunId += 1
    scheduleCheck(current.task_id)
  } catch {
    return
  }
}

async function runCheck(): Promise<void> {
  if (!canStart.value) {
    if (canStartBlockReason.value) notice.value = canStartBlockReason.value
    return
  }
  checking.value = true
  checkRunId += 1
  checkFailed.value = false
  checkMessage.value = ''
  error.value = ''
  notice.value = ''
  try {
    const task = await startTrainCommunicationCheck(selectedTrainId.value)
    lastCheckTaskId.value = task.task_id
    checkMessage.value = task.message || '车内通信检测已提交'
    scheduleCheck(task.task_id)
  } catch (cause) {
    checking.value = false
    checkFailed.value = true
    error.value = cause instanceof Error ? cause.message : '车内通信检测提交失败'
  }
}

async function handlePointTableSaved(_payload: PointTableSavedPayload): Promise<void> {
  const keep = selectedTrainId.value
  await loadTrains()
  if (keep && trainOptions.value.some((item) => item.train_id === keep || item.canonical_train_id === keep)) selectedTrainId.value = keep
  await loadTopologyForCurrentTrain()
  error.value = ''
  notice.value = '检测点表已保存，可以开始检测'
  ElMessage.success('检测点表已保存，可以开始检测')
}

function selectNode(node: { device_id: string | null }): void {
  if (node.device_id) void router.push(`/devices/${encodeURIComponent(node.device_id)}`)
}

watch(selectedTrainId, async () => {
  checkRunId += 1
  clearTimer('check')
  checking.value = false
  lastCheckTaskId.value = ''
  topology.value = null
  lastUpdatedAt.value = ''
  await loadTopologyForCurrentTrain()
  scheduleRefresh()
})
watch(refreshInterval, scheduleRefresh)

onMounted(async () => {
  await Promise.all([refreshPageState(), recoverChecks()])
  scheduleRefresh()
})
onBeforeUnmount(() => { disposed = true; checkRunId += 1; clearTimer('refresh'); clearTimer('check') })
</script>

<template>
  <section class="communication-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">轨道交通 / 车内通信检测</p>
        <h1>车内通信检测</h1>
        <p>检测所选列车 TC1 / TC2 两端车内有线通信拓扑，包括 MR、三层交换机、服务器和跨 TC 通信；VRRP 仅展示虚拟 IP 配置。</p>
      </div>
    </header>

    <section class="action-toolbar" aria-label="车内通信检测操作">
      <el-tooltip :content="canStartBlockReason || '提交车内通信检测任务'" placement="bottom">
        <span><el-button type="primary" :loading="checking" :disabled="!canStart" @click="runCheck">开始检测</el-button></span>
      </el-tooltip>
      <el-button :loading="loading || loadingTrains" @click="refreshPageState">刷新</el-button>
      <el-tooltip :content="pointTableDisabledReason || '在点表管理中导入并预览'" placement="bottom">
        <span><el-button :disabled="Boolean(pointTableDisabledReason)" @click="pointTableVisible = true">导入点表</el-button></span>
      </el-tooltip>
      <el-button @click="pointTableVisible = true">导出点表</el-button>
      <el-button @click="pointTableVisible = true">打开点表</el-button>
      <span class="toolbar-status">当前检测状态：{{ checking ? '检测中' : topology ? statusLabel(topology.train_status) : '未检测' }}</span>
    </section>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <el-alert v-if="notice" :title="notice" type="info" show-icon :closable="true" @close="notice = ''" />
    <el-alert
      v-if="topology && topology.point_table_status !== 'configured'"
      :title="pointTableStatusLabel"
      :description="[topology.point_table_message, topology.point_table_missing_nodes.length ? `缺少节点：${topology.point_table_missing_nodes.join('、')}` : ''].filter(Boolean).join('；')"
      :type="pointTableAlertType"
      show-icon
      :closable="false"
    >
      <el-button link type="primary" @click="pointTableVisible = true">打开点表</el-button>
    </el-alert>

    <section class="diagnostic-layout" :class="{ 'list-collapsed': trainListCollapsed }">
      <aside class="train-panel" :class="{ collapsed: trainListCollapsed }">
        <div class="train-panel-heading">
          <strong v-if="!trainListCollapsed">列车列表</strong>
          <el-button link @click="trainListCollapsed = !trainListCollapsed">{{ trainListCollapsed ? '展开 »' : '收起 «' }}</el-button>
        </div>
        <template v-if="!trainListCollapsed">
          <div class="train-list-header"><span>列车</span><span>最近检测</span><span>TC1/CT</span><span>TC2/CW</span></div>
          <div v-if="trainOptions.length" class="train-list" role="listbox" aria-label="全部已登记列车">
            <button
              v-for="train in trainOptions"
              :key="train.train_id"
              type="button"
              class="train-row"
              :class="{ selected: selectedTrainId === train.train_id || selectedTrainId === train.canonical_train_id }"
              :aria-selected="selectedTrainId === train.train_id || selectedTrainId === train.canonical_train_id"
              @click="selectedTrainId = train.train_id"
            >
              <strong>{{ trainDisplayName(train) }}</strong>
              <span>{{ statusLabel(train.diagnostic_status || 'not_detected') }}</span>
              <span>{{ statusLabel(train.tc1_diagnostic_status || 'not_detected') }}</span>
              <span>{{ statusLabel(train.tc2_diagnostic_status || 'not_detected') }}</span>
            </button>
          </div>
          <div v-else class="train-list-empty">当前局点暂无已登记列车</div>
        </template>
      </aside>

      <main class="diagnostic-main">
        <section class="control-bar" aria-label="车内通信检测状态">
          <span class="site-label">当前局点：{{ siteId || '未配置' }}</span>
          <span class="train-label">当前列车：{{ selectedTrain ? trainDisplayName(selectedTrain) : '未选择列车' }}</span>
          <el-tag type="info">{{ onlineStatusLabel(selectedTrain) }}</el-tag>
          <el-select v-model="refreshInterval" class="refresh-select" aria-label="自动刷新间隔">
            <el-option :value="0" label="自动刷新：关闭" />
            <el-option :value="10" label="自动刷新：10 秒" />
            <el-option :value="30" label="自动刷新：30 秒" />
            <el-option :value="60" label="自动刷新：60 秒" />
          </el-select>
          <span class="updated-label">最近更新：{{ formatTime(lastUpdatedAt) }}</span>
        </section>

        <el-alert v-if="canStartBlockReason && selectedTrainId && !checking" :title="canStartBlockReason" type="warning" show-icon :closable="false" />
        <el-alert v-if="checking || checkMessage" :title="checkMessage || '车内通信检测进行中'" :type="checking ? 'info' : checkFailed ? 'error' : 'success'" show-icon :closable="false" />
        <FixedTrainTopology :topology="topology" :checking="checking" @select-node="selectNode" />

        <section class="result-grid" aria-label="实时检测结果">
          <article v-for="side in ['TC1', 'TC2']" :key="side" class="result-card">
            <h2>{{ side === 'TC1' ? 'TC1端 / CT车头' : 'TC2端 / CW车尾' }} 实时检测结果</h2>
            <div class="result-table">
              <div class="result-row result-header"><span>节点 / IP</span><span>状态</span><span>说明</span></div>
              <div v-for="node in (side === 'TC1' ? topology?.tc1_nodes : topology?.tc2_nodes) || []" :key="node.node_id" class="result-row">
                <span><strong>{{ node.name || node.node_id }}</strong><small>{{ node.ip_address || '未配置地址' }}</small></span>
                <span>{{ statusLabel(checking && node.status !== 'not_configured' ? 'checking' : node.status) }}</span>
                <span>{{ node.message || '—' }}</span>
              </div>
              <div v-if="!topology" class="result-empty">请选择列车并加载拓扑</div>
            </div>
          </article>
        </section>

        <section class="detection-progress">
          <strong>检测进度与当前阶段</strong>
          <span>{{ checking ? checkMessage || '正在执行车内通信检测' : checkMessage || '尚未开始检测' }}</span>
          <span v-if="lastCheckTaskId" class="task-reference">任务：{{ lastCheckTaskId }}</span>
        </section>
      </main>
    </section>

    <section class="state-legend" aria-label="状态图例">
      <span v-for="status in (['normal', 'abnormal', 'checking', 'stale', 'not_detected', 'not_configured'] as TopologyStatus[])" :key="status"><i :class="`legend-dot ${status}`"></i>{{ statusLabel(status) }}</span>
    </section>
    <CarNetworkPointTableDialog v-model="pointTableVisible" :train="selectedTrain" @saved="handlePointTableSaved" />
  </section>
</template>

<style scoped>
.communication-page { display: flex; flex-direction: column; gap: 14px; min-width: 0; overflow-x: auto; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.page-heading h1 { margin: 3px 0 6px; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: 0; }
.action-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.toolbar-status { margin-left: auto; color: var(--el-text-color-secondary); font-size: 13px; }
.diagnostic-layout { display: grid; grid-template-columns: minmax(420px, 520px) minmax(760px, 1fr); gap: 12px; align-items: start; min-width: 1192px; }
.diagnostic-layout.list-collapsed { grid-template-columns: 76px minmax(760px, 1fr); min-width: 848px; }
.train-panel { position: sticky; top: 0; max-height: calc(100vh - 270px); overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.train-panel.collapsed { width: 76px; min-width: 76px; }
.train-panel-heading { position: sticky; top: 0; z-index: 2; display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--el-bg-color); border-bottom: 1px solid var(--el-border-color-lighter); }
.train-list-header, .train-row { display: grid; grid-template-columns: minmax(130px, 1.3fr) repeat(3, minmax(76px, .8fr)); gap: 6px; align-items: center; }
.train-list-header { position: sticky; top: 45px; z-index: 1; padding: 8px 10px; color: var(--el-text-color-secondary); font-size: 12px; background: var(--el-fill-color-light); }
.train-row { width: 100%; padding: 10px; border: 0; border-bottom: 1px solid var(--el-border-color-lighter); color: var(--el-text-color-primary); background: transparent; text-align: left; cursor: pointer; }
.train-row:hover { background: var(--el-fill-color-light); }
.train-row.selected { color: var(--el-color-primary); background: var(--el-color-primary-light-9); box-shadow: inset 3px 0 0 var(--el-color-primary); }
.train-row span { font-size: 12px; }
.train-list-empty, .result-empty { padding: 24px 12px; color: var(--el-text-color-secondary); text-align: center; }
.diagnostic-main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.control-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); min-width: 0; }
.refresh-select { width: 150px; }
.site-label, .train-label, .updated-label { color: var(--el-text-color-secondary); font-size: 13px; }
.train-label { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.updated-label { margin-left: auto; }
.result-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.result-card { min-width: 0; padding: 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.result-card h2 { margin: 0 0 10px; font-size: 15px; }
.result-table { min-width: 0; overflow-x: auto; }
.result-row { display: grid; grid-template-columns: minmax(180px, 1.2fr) 90px minmax(140px, 1fr); gap: 8px; padding: 8px; border-bottom: 1px solid var(--el-border-color-lighter); font-size: 12px; }
.result-row > span:first-child { display: flex; flex-direction: column; gap: 2px; }
.result-row small { color: var(--el-text-color-secondary); }
.result-header { color: var(--el-text-color-secondary); background: var(--el-fill-color-light); }
.detection-progress { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-light); }
.detection-progress span { color: var(--el-text-color-secondary); }
.state-legend { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; color: var(--el-text-color-secondary); font-size: 12px; }
.legend-dot { display: inline-block; width: 9px; height: 9px; margin-right: 5px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.legend-dot.normal { background: var(--el-color-success); }
.legend-dot.abnormal { background: var(--el-color-danger); }
.legend-dot.checking { background: var(--el-color-primary); }
.legend-dot.stale { background: var(--el-color-warning); }
.task-reference { margin-left: auto; }
@media (max-width: 700px) {
  .page-heading { flex-direction: column; }
  .refresh-select { width: 100%; }
  .updated-label, .task-reference, .toolbar-status { margin-left: 0; }
  .train-label { max-width: 100%; white-space: normal; }
}
</style>
