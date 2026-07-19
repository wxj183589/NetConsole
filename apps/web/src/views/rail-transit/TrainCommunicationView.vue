<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  getTrainCommunicationCheck,
  getTrainCommunicationSummary,
  getTrainCommunicationTopology,
  listTrainCommunications,
  startTrainCommunicationCheck,
} from '../../api/trainCommunication'
import FixedTrainTopology from '../../components/train-communication/FixedTrainTopology.vue'
import { isFeatureEnabled } from '../../features'
import type { TrainCommunicationRow, TrainCommunicationTopology, TopologyStatus } from '../../types/trainCommunication'
import CarNetworkPointTableDialog from './CarNetworkPointTableDialog.vue'

const router = useRouter()
const trainOptions = ref<TrainCommunicationRow[]>([])
const selectedTrainId = ref('')
const siteId = ref('')
const topology = ref<TrainCommunicationTopology | null>(null)
const loading = ref(false)
const checking = ref(false)
const error = ref('')
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

const pointTableStatusLabel = computed(() => {
  if (!topology.value) return ''
  return topology.value.point_table_status === 'configured'
    ? '检测点表已配置'
    : topology.value.point_table_status === 'invalid'
      ? '检测点表不完整'
      : '检测点表未配置'
})
const pointTableAlertType = computed(() => topology.value?.point_table_status === 'invalid' ? 'error' : 'warning')
const canStart = computed(() => Boolean(
  selectedTrainId.value
  && topology.value?.point_table_status === 'configured'
  && !checking.value
  && isFeatureEnabled('web.rail_car_network_diagnostic_execute')
  && isFeatureEnabled('web.rail_task_control'),
))

function statusLabel(status: TopologyStatus): string { return statusLabels[status] || '未检测' }
function formatTime(value: string | null | undefined): string { return value ? value.replace('T', ' ').replace(/\+00:00$/, '') : '未检测' }

async function loadTrainOptions(): Promise<void> {
  try {
    const [summary, page] = await Promise.all([
      getTrainCommunicationSummary(),
      listTrainCommunications({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' }),
    ])
    siteId.value = summary.site_id
    trainOptions.value = page.items
    if (!selectedTrainId.value && page.items[0]) selectedTrainId.value = page.items[0].train_id
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '列车列表加载失败'
  }
}

async function loadTopology(): Promise<void> {
  if (!selectedTrainId.value) {
    topology.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    topology.value = await getTrainCommunicationTopology(selectedTrainId.value)
    lastUpdatedAt.value = topology.value.checked_at || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '拓扑状态加载失败'
  } finally {
    loading.value = false
  }
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
    await loadTopology()
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
        await loadTopology()
        return
      }
      scheduleCheck(taskId)
    } catch (cause) {
      checking.value = false
      error.value = cause instanceof Error ? cause.message : '检测任务状态读取失败'
    }
  }, 1000)
}

async function runCheck(): Promise<void> {
  if (!canStart.value) return
  checking.value = true
  checkRunId += 1
  checkFailed.value = false
  checkMessage.value = ''
  error.value = ''
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

function selectNode(node: { device_id: string | null }): void {
  if (node.device_id) void router.push(`/devices/${encodeURIComponent(node.device_id)}`)
}

watch(selectedTrainId, async () => {
  checkRunId += 1
  clearTimer('check')
  checking.value = false
  lastCheckTaskId.value = ''
  await loadTopology()
  scheduleRefresh()
})
watch(refreshInterval, scheduleRefresh)

onMounted(async () => {
  await loadTrainOptions()
  scheduleRefresh()
})
onBeforeUnmount(() => { disposed = true; checkRunId += 1; clearTimer('refresh'); clearTimer('check') })
</script>

<template>
  <section class="communication-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">轨道交通 / 车内通信</p>
        <h1>在线列车车地通信检测</h1>
        <p>固定展示 TC1 / TC2 两端车载通信拓扑、节点状态、VRRP 和跨 TC 通信状态。</p>
      </div>
      <div class="heading-actions">
        <el-tag type="info">固定六节点</el-tag>
        <el-button :disabled="!isFeatureEnabled('web.rail_car_network_point_table_write')" @click="pointTableVisible = true">点表管理</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
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

    <section class="control-bar" aria-label="车内通信检测控制">
      <el-select v-model="selectedTrainId" filterable clearable placeholder="选择列车" class="train-select">
        <el-option v-for="train in trainOptions" :key="train.train_id" :label="`${train.train_no} / ${train.train_name}`" :value="train.train_id" />
      </el-select>
      <span class="site-label">当前局点：{{ siteId || '未配置' }}</span>
      <el-tag type="info">状态：{{ topology ? statusLabel(topology.train_status) : '未检测' }}</el-tag>
      <el-button :loading="loading" @click="loadTopology">刷新</el-button>
      <el-button type="primary" :loading="checking" :disabled="!canStart" @click="runCheck">立即检测</el-button>
      <el-select v-model="refreshInterval" class="refresh-select" aria-label="自动刷新间隔">
        <el-option :value="0" label="自动刷新：关闭" />
        <el-option :value="10" label="自动刷新：10 秒" />
        <el-option :value="30" label="自动刷新：30 秒" />
        <el-option :value="60" label="自动刷新：60 秒" />
      </el-select>
      <span class="updated-label">最近更新：{{ formatTime(lastUpdatedAt) }}</span>
    </section>

    <el-alert v-if="checking || checkMessage" :title="checkMessage || '车内通信检测进行中'" :type="checking ? 'info' : checkFailed ? 'error' : 'success'" show-icon :closable="false" />
    <FixedTrainTopology :topology="topology" :checking="checking" @select-node="selectNode" />

    <section class="state-legend" aria-label="状态图例">
      <span v-for="status in (['normal', 'abnormal', 'checking', 'stale', 'not_detected', 'not_configured'] as TopologyStatus[])" :key="status"><i :class="`legend-dot ${status}`"></i>{{ statusLabel(status) }}</span>
      <span v-if="lastCheckTaskId" class="task-reference">检测任务：{{ lastCheckTaskId }}</span>
    </section>
    <CarNetworkPointTableDialog v-model="pointTableVisible" />
  </section>
</template>

<style scoped>
.communication-page { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.heading-actions { display: flex; align-items: center; gap: 10px; }
.page-heading h1 { margin: 3px 0 6px; }
.page-heading p { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.control-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-bg-color); }
.train-select { width: 270px; }
.refresh-select { width: 150px; }
.site-label, .updated-label { color: var(--el-text-color-secondary); font-size: 13px; }
.updated-label { margin-left: auto; }
.state-legend { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; color: var(--el-text-color-secondary); font-size: 12px; }
.legend-dot { display: inline-block; width: 9px; height: 9px; margin-right: 5px; border-radius: 50%; background: var(--el-text-color-placeholder); }
.legend-dot.normal { background: var(--el-color-success); }
.legend-dot.abnormal { background: var(--el-color-danger); }
.legend-dot.checking { background: var(--el-color-primary); }
.legend-dot.stale { background: var(--el-color-warning); }
.task-reference { margin-left: auto; }
@media (max-width: 700px) { .page-heading { flex-direction: column; } .heading-actions, .train-select, .refresh-select { width: 100%; } .updated-label, .task-reference { margin-left: 0; } }
</style>
