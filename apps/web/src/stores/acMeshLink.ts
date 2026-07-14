import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getMeshLinkSummary,
  getMeshMrDetail,
  getMeshRawTail,
  listMeshLinks,
  listMeshMrs,
  listMeshSnapshots,
  startMeshLinkRefresh,
} from '../api/acMeshLink'
import { getAcSummary } from '../api/acManagement'
import { getTask } from '../api/tasks'
import type { AcOverview } from '../types/acManagement'
import type { TaskItem } from '../types/task'
import type {
  AcMeshLinkRecord,
  AcMeshLinkSummary,
  AcMeshMrDetail,
  AcMeshMrStatus,
  AcMeshRawTail,
  AcMeshSnapshot,
} from '../types/acMeshLink'

export const useAcMeshLinkStore = defineStore('ac-mesh-link', () => {
  const summary = ref<AcMeshLinkSummary | null>(null)
  const mrs = ref<AcMeshMrStatus[]>([])
  const mrTotal = ref(0)
  const links = ref<AcMeshLinkRecord[]>([])
  const linkTotal = ref(0)
  const selected = ref<AcMeshMrDetail | null>(null)
  const snapshots = ref<AcMeshSnapshot[]>([])
  const snapshotTotal = ref(0)
  const rawTail = ref<AcMeshRawTail | null>(null)
  const loading = ref(false)
  const detailLoading = ref(false)
  const failures = ref(0)
  const error = ref('')
  const rawExpanded = ref(false)
  const controllers = ref<AcOverview[]>([])
  const selectedControllerId = ref('')
  const includeSwitchHistory = ref(false)
  const refreshStarting = ref(false)
  const refreshTask = ref<TaskItem | null>(null)
  const refreshError = ref('')
  const activeRefreshStatuses = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'CREATED', 'QUEUED']
  const refreshActive = computed(() => refreshStarting.value || Boolean(
    refreshTask.value && activeRefreshStatuses.includes(refreshTask.value.status),
  ))
  const filters = reactive({
    query: '',
    online_status: '',
    station: '',
    section: '',
    line_side: '',
    unmatched_only: false,
    offline_ap_only: false,
    optical_anomaly_only: false,
    page: 1,
    page_size: 50,
  })
  const linkFilters = reactive({
    query: '',
    link_status: '',
    match_status: '',
    page: 1,
    page_size: 50,
  })
  let polling = false
  let coreBusy = false
  let detailBusy = false
  let rawBusy = false
  let coreTimer: number | null = null
  let rawTimer: number | null = null
  let refreshTimer: number | null = null

  async function refreshCore(): Promise<void> {
    if (coreBusy) return
    coreBusy = true
    loading.value = !summary.value
    try {
      const [summaryResult, mrResult, linkResult, snapshotResult, acResult] = await Promise.all([
        getMeshLinkSummary(),
        listMeshMrs({ ...filters, sort_by: 'train_no', sort_order: 'asc' }),
        listMeshLinks({ ...linkFilters, sort_by: 'mr_name', sort_order: 'asc' }),
        listMeshSnapshots(),
        controllers.value.length ? Promise.resolve(null) : getAcSummary(),
      ])
      summary.value = summaryResult
      mrs.value = mrResult.items
      mrTotal.value = mrResult.total
      links.value = linkResult.items
      linkTotal.value = linkResult.total
      snapshots.value = snapshotResult.items
      snapshotTotal.value = snapshotResult.total
      if (acResult) controllers.value = acResult.acs
      if (!selectedControllerId.value) {
        selectedControllerId.value = summaryResult.controller_id || controllers.value[0]?.id || ''
      }
      failures.value = 0
      error.value = ''
    } catch (cause) {
      failures.value += 1
      if (failures.value >= 3) error.value = 'Mesh-Link 数据刷新失败，已保留最后一次成功数据并降低刷新频率。'
      else if (!summary.value && cause instanceof Error) error.value = cause.message
    } finally {
      coreBusy = false
      loading.value = false
    }
  }

  async function selectMr(mrId: string): Promise<void> {
    if (detailBusy) return
    detailBusy = true
    detailLoading.value = true
    try {
      selected.value = await getMeshMrDetail(mrId)
    } catch (cause) {
      if (cause instanceof Error) error.value = cause.message
    } finally {
      detailBusy = false
      detailLoading.value = false
    }
  }

  async function refreshRawTail(): Promise<void> {
    if (!rawExpanded.value || rawBusy) return
    rawBusy = true
    try {
      rawTail.value = await getMeshRawTail(summary.value ? snapshots.value[0]?.id : undefined)
    } catch (cause) {
      if (cause instanceof Error) error.value = cause.message
    } finally {
      rawBusy = false
    }
  }

  async function startRefresh(): Promise<void> {
    if (refreshActive.value || !selectedControllerId.value) return
    refreshStarting.value = true
    refreshError.value = ''
    try {
      const response = await startMeshLinkRefresh(selectedControllerId.value, includeSwitchHistory.value)
      refreshTask.value = await getTask(response.task_id)
      scheduleRefreshTask()
    } catch (cause) {
      refreshError.value = cause instanceof Error ? cause.message : 'Mesh-Link 刷新任务创建失败'
    } finally {
      refreshStarting.value = false
    }
  }

  async function pollRefreshTask(): Promise<void> {
    if (!refreshTask.value) return
    try {
      const latest = await getTask(refreshTask.value.id)
      refreshTask.value = latest
      if (latest.status === 'COMPLETED') {
        refreshError.value = ''
        await refreshCore()
        if (rawExpanded.value) await refreshRawTail()
        return
      }
      if (['FAILED', 'CANCELLED', 'ABORTED', 'STOPPED'].includes(latest.status)) {
        refreshError.value = latest.error_summary || '本次刷新失败，当前显示上次成功数据。'
        return
      }
      scheduleRefreshTask()
    } catch (cause) {
      refreshError.value = cause instanceof Error ? cause.message : 'Mesh-Link 刷新状态查询失败'
      scheduleRefreshTask()
    }
  }

  function applyFilters(): void {
    filters.page = 1
    linkFilters.page = 1
    void refreshCore()
  }

  function setMrPage(page: number): void {
    filters.page = page
    void refreshCore()
  }

  function setLinkPage(page: number): void {
    linkFilters.page = page
    void refreshCore()
  }

  function setRawExpanded(value: boolean): void {
    rawExpanded.value = value
    if (rawTimer !== null) window.clearTimeout(rawTimer)
    rawTimer = null
    if (value && polling) {
      void refreshRawTail()
      scheduleRaw()
    }
  }

  function startPolling(): void {
    if (polling) return
    polling = true
    void refreshCore()
    scheduleCore()
    if (rawExpanded.value) scheduleRaw()
    if (refreshTask.value && activeRefreshStatuses.includes(refreshTask.value.status)) scheduleRefreshTask()
  }

  function stopPolling(): void {
    polling = false
    if (coreTimer !== null) window.clearTimeout(coreTimer)
    if (rawTimer !== null) window.clearTimeout(rawTimer)
    if (refreshTimer !== null) window.clearTimeout(refreshTimer)
    coreTimer = rawTimer = refreshTimer = null
  }

  function scheduleCore(): void {
    if (!polling) return
    coreTimer = window.setTimeout(async () => {
      await refreshCore()
      scheduleCore()
    }, failures.value >= 3 ? 15_000 : 5_000)
  }

  function scheduleRaw(): void {
    if (!polling || !rawExpanded.value) return
    rawTimer = window.setTimeout(async () => {
      await refreshRawTail()
      scheduleRaw()
    }, 2_000)
  }

  function scheduleRefreshTask(): void {
    if (!polling || !refreshTask.value || !activeRefreshStatuses.includes(refreshTask.value.status)) return
    if (refreshTimer !== null) window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => {
      refreshTimer = null
      void pollRefreshTask()
    }, 1_500)
  }

  return {
    summary,
    mrs,
    mrTotal,
    links,
    linkTotal,
    selected,
    snapshots,
    snapshotTotal,
    rawTail,
    loading,
    detailLoading,
    failures,
    error,
    rawExpanded,
    controllers,
    selectedControllerId,
    includeSwitchHistory,
    refreshStarting,
    refreshTask,
    refreshError,
    refreshActive,
    filters,
    linkFilters,
    refreshCore,
    selectMr,
    refreshRawTail,
    startRefresh,
    applyFilters,
    setMrPage,
    setLinkPage,
    setRawExpanded,
    startPolling,
    stopPolling,
  }
})
