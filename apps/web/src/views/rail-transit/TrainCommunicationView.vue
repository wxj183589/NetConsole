<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTrainCommunicationCheck,
  getTrainCommunicationSummary,
  getTrainCommunicationTopology,
  listOnlineTrainCommunications,
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
const loadingOnline = ref(false)
const checking = ref(false)
const error = ref('')
const notice = ref('')
const lastCheckTaskId = ref('')
const checkMessage = ref('')
const checkFailed = ref(false)
const refreshInterval = ref(0)
const lastUpdatedAt = ref('')
const pointTableVisible = ref(false)
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

const onlineReasons = [
  '列车在线状态尚未刷新',
  'AC Mesh-Link 数据不存在',
  '列车 MR 映射未配置',
  '数据已经过期',
  '当前确实无在线列车',
]

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
  if (!selectedTrainId.value) return '未选择在线列车'
  if (!selectedTrain.value) return '列车已离线，请刷新后重试'
  if (!topology.value) return '拓扑状态尚未加载'
  if (topology.value.point_table_status === 'missing') return '点表未配置'
  if (topology.value.point_table_status === 'invalid') return topology.value.point_table_message || '点表缺少节点或节点未绑定设备/地址'
  if (topology.value.point_table_missing_nodes.length) return `点表缺少节点：${topology.value.point_table_missing_nodes.join('、')}`
  return ''
})
const canStart = computed(() => !canStartBlockReason.value)

function statusLabel(status: TopologyStatus): string { return statusLabels[status] || '未检测' }
function formatTime(value: string | null | undefined): string { return value ? value.replace('T', ' ').replace(/\+00:00$/, '') : '未检测' }
function trainOptionLabel(train: TrainCommunicationRow): string {
  const display = train.display_name || [train.train_name, train.train_no ? `${train.train_no}车` : ''].filter(Boolean).join(' / ') || train.train_id
  if (train.overall_status === 'BOTH_ONLINE') return `${display} · 双端在线`
  const side = train.ct_online_status === 'ONLINE' ? 'CT' : train.tc_online_status === 'ONLINE' ? 'TC' : '未知端'
  return `${display} · 单端在线（${side}）`
}

async function loadOnlineTrains(): Promise<void> {
  loadingOnline.value = true
  try {
    const [summary, page] = await Promise.all([
      getTrainCommunicationSummary(),
      listOnlineTrainCommunications(1, 200),
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
        notice.value = '原选中列车已离线'
      }
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '在线列车列表加载失败'
  } finally {
    loadingOnline.value = false
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
    error.value = cause instanceof Error ? cause.message : '在线列车车内通信拓扑状态加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshPageState(): Promise<void> {
  notice.value = ''
  await loadOnlineTrains()
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
      checkMessage.value = checkFailed.value ? task.error_message || task.message || '在线列车车内通信检测失败' : task.message || ''
      if (terminal) {
        checking.value = false
        await loadTopologyForCurrentTrain()
        return
      }
      scheduleCheck(taskId)
    } catch (cause) {
      checking.value = false
      error.value = cause instanceof Error ? cause.message : '在线列车车内通信检测任务状态读取失败'
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
    checkMessage.value = task.message || '在线列车车内通信检测已提交'
    scheduleCheck(task.task_id)
  } catch (cause) {
    checking.value = false
    checkFailed.value = true
    error.value = cause instanceof Error ? cause.message : '在线列车车内通信检测提交失败'
  }
}

async function handlePointTableSaved(_payload: PointTableSavedPayload): Promise<void> {
  const keep = selectedTrainId.value
  await loadOnlineTrains()
  if (keep && trainOptions.value.some((item) => item.train_id === keep || item.canonical_train_id === keep)) selectedTrainId.value = keep
  await loadTopologyForCurrentTrain()
  error.value = ''
  notice.value = '检测点表已保存，可以开始检测'
  ElMessage.success('检测点表已保存，可以开始检测')
}

function selectNode(node: { device_id: string | null }): void {
  if (node.device_id) void router.push(`/devices/${encodeURIComponent(node.device_id)}`)
}

function goTrainOnline(query: Record<string, string> = {}): void {
  void router.push({ path: '/rail-transit/train-online', query })
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
        <p class="eyebrow">轨道交通 / 在线列车车内通信检测</p>
        <h1>在线列车车内通信检测</h1>
        <p>检测在线列车 TC1 / TC2 两端车内有线通信拓扑，包括 MR、三层交换机、服务器、VRRP 和跨 TC 通信。</p>
      </div>
      <div class="heading-actions">
        <el-tag type="info">固定六节点</el-tag>
        <el-tooltip :content="pointTableDisabledReason || '管理车内通信检测点表'" placement="bottom">
          <span><el-button :disabled="Boolean(pointTableDisabledReason)" @click="pointTableVisible = true">点表管理</el-button></span>
        </el-tooltip>
      </div>
    </header>

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
      <el-button link type="primary" @click="pointTableVisible = true">配置点表</el-button>
    </el-alert>
    <el-alert v-if="!trainOptions.length && !loadingOnline" title="当前未检测到在线列车" type="warning" show-icon :closable="false">
      <div class="empty-online">
        <span v-for="item in onlineReasons" :key="item">{{ item }}</span>
        <div class="empty-actions">
          <el-button link type="primary" @click="refreshPageState">刷新在线列车</el-button>
          <el-button link type="primary" @click="goTrainOnline()">前往“列车在线情况”</el-button>
          <el-button link type="primary" @click="goTrainOnline({ mappings: '1' })">打开列车 MR 映射</el-button>
        </div>
      </div>
    </el-alert>

    <section class="control-bar" aria-label="在线列车车内通信检测控制">
      <el-select v-model="selectedTrainId" filterable clearable placeholder="选择在线列车" class="train-select" :loading="loadingOnline">
        <el-option v-for="train in trainOptions" :key="train.train_id" :label="trainOptionLabel(train)" :value="train.train_id" />
        <template #empty>
          <div class="select-empty">
            <strong>当前未检测到在线列车</strong>
            <small>请刷新在线状态或检查列车 MR 映射</small>
            <el-button link type="primary" @click.stop="refreshPageState">刷新在线列车</el-button>
          </div>
        </template>
      </el-select>
      <span class="site-label">当前局点：{{ siteId || '未配置' }}</span>
      <span class="train-label">当前列车：{{ selectedTrain ? trainOptionLabel(selectedTrain) : '未选择在线列车' }}</span>
      <el-tag type="info">状态：{{ topology ? statusLabel(topology.train_status) : '未检测' }}</el-tag>
      <el-button :loading="loading || loadingOnline" @click="refreshPageState">刷新</el-button>
      <el-tooltip :content="canStartBlockReason || '提交在线列车车内通信检测任务'" placement="bottom">
        <span><el-button type="primary" :loading="checking" :disabled="!canStart" @click="runCheck">立即检测</el-button></span>
      </el-tooltip>
      <el-select v-model="refreshInterval" class="refresh-select" aria-label="自动刷新间隔">
        <el-option :value="0" label="自动刷新：关闭" />
        <el-option :value="10" label="自动刷新：10 秒" />
        <el-option :value="30" label="自动刷新：30 秒" />
        <el-option :value="60" label="自动刷新：60 秒" />
      </el-select>
      <span class="updated-label">最近更新：{{ formatTime(lastUpdatedAt) }}</span>
    </section>

    <el-alert v-if="canStartBlockReason && selectedTrainId && !checking" :title="canStartBlockReason" type="warning" show-icon :closable="false" />
    <el-alert v-if="checking || checkMessage" :title="checkMessage || '在线列车车内通信检测进行中'" :type="checking ? 'info' : checkFailed ? 'error' : 'success'" show-icon :closable="false" />
    <FixedTrainTopology :topology="topology" :checking="checking" @select-node="selectNode" />

    <section class="state-legend" aria-label="状态图例">
      <span v-for="status in (['normal', 'abnormal', 'checking', 'stale', 'not_detected', 'not_configured'] as TopologyStatus[])" :key="status"><i :class="`legend-dot ${status}`"></i>{{ statusLabel(status) }}</span>
      <span v-if="lastCheckTaskId" class="task-reference">检测任务：{{ lastCheckTaskId }}</span>
    </section>
    <CarNetworkPointTableDialog v-model="pointTableVisible" :train="selectedTrain" @saved="handlePointTableSaved" />
  </section>
</template>

<style scoped>
.communication-page { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.heading-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.page-heading h1 { margin: 3px 0 6px; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: 0; }
.control-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); min-width: 0; }
.train-select { width: min(360px, 100%); }
.refresh-select { width: 150px; }
.site-label, .train-label, .updated-label { color: var(--el-text-color-secondary); font-size: 13px; }
.train-label { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.updated-label { margin-left: auto; }
.empty-online { display: flex; flex-direction: column; gap: 4px; }
.empty-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.select-empty { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 10px; color: var(--el-text-color-secondary); }
.select-empty strong { color: var(--el-text-color-primary); }
.state-legend { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; color: var(--el-text-color-secondary); font-size: 12px; }
.legend-dot { display: inline-block; width: 9px; height: 9px; margin-right: 5px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.legend-dot.normal { background: var(--el-color-success); }
.legend-dot.abnormal { background: var(--el-color-danger); }
.legend-dot.checking { background: var(--el-color-primary); }
.legend-dot.stale { background: var(--el-color-warning); }
.task-reference { margin-left: auto; }
@media (max-width: 700px) {
  .page-heading { flex-direction: column; }
  .heading-actions, .train-select, .refresh-select { width: 100%; }
  .updated-label, .task-reference { margin-left: 0; }
  .train-label { max-width: 100%; white-space: normal; }
}
</style>
