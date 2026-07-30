import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getAcApDetail,
  getAcConfigDiff,
  getAcConfigSnapshot,
  getAcSummary,
  listAcAps,
  listAcConfigSnapshots,
} from '../api/acManagement'
import { cancelAcWebTask, deleteAcFitAps, getAcWebTask, importAcFitApMetadata, recoverAcWebTasks, saveAcFitApMetadata, startAcResourceRefresh } from '../api/acWebParity'
import type {
  AcAp,
  AcApDetail,
  AcConfigContent,
  AcConfigDiff,
  AcConfigSnapshot,
  AcManagementSummary,
} from '../types/acManagement'
import type { AcWebTask } from '../types/acWebParity'

const ACTIVE_TASK_KEY = 'netconsole.ac.active-task'
const ACTIVE_ACTION_TASK_KEY = 'netconsole.ac.active-action-task'
const TERMINAL_TASKS = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const REFRESH_ACTIONS = new Set(['ac_info_refresh', 'ac_fit_ap_resources_refresh', 'ac_fit_ap_detail_refresh', 'ac_fit_ap_optical_refresh', 'ac_fit_ap_delete_many', 'fit_ap_metadata_import', 'fit_ap_metadata_save'])
type RefreshDomain = 'summary' | 'aps' | 'detail' | 'snapshots' | 'config'

export const useAcManagementStore = defineStore('ac-management', () => {
  const summary = ref<AcManagementSummary | null>(null)
  const aps = ref<AcAp[]>([])
  const total = ref(0)
  const selected = ref<AcApDetail | null>(null)
  const snapshots = ref<AcConfigSnapshot[]>([])
  const snapshotTotal = ref(0)
  const configContent = ref<AcConfigContent | null>(null)
  const configDiff = ref<AcConfigDiff | null>(null)
  const loading = ref(false)
  const detailLoading = ref(false)
  const configLoading = ref(false)
  const refreshFailureCounts = reactive<Record<RefreshDomain, number>>({ summary: 0, aps: 0, detail: 0, snapshots: 0, config: 0 })
  const refreshErrors = reactive<Record<RefreshDomain, string>>({ summary: '', aps: '', detail: '', snapshots: '', config: '' })
  const failures = computed(() => Math.max(...Object.values(refreshFailureCounts)))
  const operationError = ref('')
  const error = computed(() => [operationError.value, ...Object.values(refreshErrors)].filter(Boolean).join(' '))
  const refreshTask = ref<AcWebTask | null>(null)
  const actionTask = ref<AcWebTask | null>(null)
  const refreshStarting = ref(false)
  const filters = reactive({
    ac_id: '',
    page: 1,
    page_size: 50,
    query: '',
    status: '',
    station: '',
    section: '',
    model: '',
    switch: '',
    optical_status: '',
    sort_by: 'topology',
    sort_order: 'asc' as 'asc' | 'desc',
  })
  const snapshotPage = ref(1)
  const snapshotPageSize = ref(30)
  const snapshotType = ref('')
  let summaryBusy = false
  let apsBusy = false
  let detailBusy = false
  let detailRequestId = 0
  let snapshotBusy = false
  let polling = false
  let summaryTimer: number | null = null
  let apsTimer: number | null = null
  let detailTimer: number | null = null
  let snapshotTimer: number | null = null
  let taskTimer: number | null = null
  let actionTaskTimer: number | null = null

  const activeAc = computed(() => summary.value?.acs.find((item) => item.id === filters.ac_id) || summary.value?.acs[0])

  async function refreshSummary(): Promise<void> {
    if (summaryBusy) return
    summaryBusy = true
    try {
      summary.value = await getAcSummary()
      if (!filters.ac_id && summary.value.acs.length) filters.ac_id = summary.value.acs[0].id
      recordSuccess('summary')
    } catch (cause) {
      recordFailure('summary', cause)
    } finally {
      summaryBusy = false
    }
  }

  async function refreshAps(): Promise<void> {
    if (apsBusy) return
    apsBusy = true
    loading.value = !aps.value.length
    try {
      const result = await listAcAps(filters)
      aps.value = result.items
      total.value = result.total
      recordSuccess('aps')
    } catch (cause) {
      recordFailure('aps', cause)
    } finally {
      apsBusy = false
      loading.value = false
    }
  }

  async function selectAp(apId: string): Promise<void> {
    const requestId = ++detailRequestId
    detailBusy = true
    detailLoading.value = true
    try {
      const detail = await getAcApDetail(apId)
      if (requestId === detailRequestId) {
        selected.value = detail
        recordSuccess('detail')
      }
    } catch (cause) {
      if (requestId === detailRequestId) {
        recordFailure('detail', cause)
      }
    } finally {
      if (requestId === detailRequestId) {
        detailBusy = false
        detailLoading.value = false
      }
    }
  }

  async function refreshSelected(): Promise<void> {
    if (selected.value) await selectAp(selected.value.ap.id)
  }

  async function refreshSnapshots(): Promise<void> {
    if (snapshotBusy) return
    snapshotBusy = true
    try {
      const result = await listAcConfigSnapshots({
        ac_id: filters.ac_id,
        type: snapshotType.value,
        page: snapshotPage.value,
        page_size: snapshotPageSize.value,
      })
      snapshots.value = result.items
      snapshotTotal.value = result.total
      recordSuccess('snapshots')
    } catch (cause) {
      recordFailure('snapshots', cause)
    } finally {
      snapshotBusy = false
    }
  }

  async function loadConfig(snapshotId: number): Promise<void> {
    configLoading.value = true
    configDiff.value = null
    try {
      configContent.value = await getAcConfigSnapshot(snapshotId)
      recordSuccess('config')
    } catch (cause) {
      recordFailure('config', cause)
    } finally {
      configLoading.value = false
    }
  }

  async function loadMoreConfig(): Promise<void> {
    const current = configContent.value
    if (!current?.next_offset) return
    configLoading.value = true
    try {
      const next = await getAcConfigSnapshot(current.snapshot.id, current.next_offset)
      configContent.value = { ...next, content: current.content + next.content, offset: 0 }
      recordSuccess('config')
    } catch (cause) {
      recordFailure('config', cause)
    } finally {
      configLoading.value = false
    }
  }

  async function loadDiff(snapshotId: number): Promise<void> {
    configLoading.value = true
    configContent.value = null
    configDiff.value = null
    try {
      configDiff.value = await getAcConfigDiff(snapshotId)
      recordSuccess('config')
    } catch (cause) {
      recordFailure('config', cause)
    } finally {
      configLoading.value = false
    }
  }

  async function manualRefresh(): Promise<void> {
    await refreshSummary()
    await Promise.all([refreshAps(), refreshSnapshots(), refreshSelected()])
  }

  async function startRefresh(kind: 'ac' | 'fit-ap' | 'ap-detail' | 'optical', apId = ''): Promise<void> {
    if (!filters.ac_id || refreshStarting.value || (refreshTask.value && !TERMINAL_TASKS.has(refreshTask.value.status))) return
    refreshStarting.value = true
    operationError.value = ''
    try {
      refreshTask.value = await startAcResourceRefresh(kind, filters.ac_id, apId)
      window.localStorage?.setItem(ACTIVE_TASK_KEY, refreshTask.value.task_id)
      scheduleTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'AC / FIT-AP 更新启动失败'
    } finally {
      refreshStarting.value = false
    }
  }

  const startAcInfoRefresh = () => startRefresh('ac')
  const startFitApRefresh = () => startRefresh('fit-ap')
  const startFitApDetailRefresh = () => selected.value ? startRefresh('ap-detail', selected.value.ap.id) : Promise.resolve()
  const startOpticalRefresh = () => startRefresh('optical')
  const startApOpticalRefresh = (apId: string) => startRefresh('optical', apId)

  async function startFitApDelete(apIds: string[]): Promise<void> {
    if (!filters.ac_id || !apIds.length || refreshStarting.value || (refreshTask.value && !TERMINAL_TASKS.has(refreshTask.value.status))) return
    refreshStarting.value = true
    operationError.value = ''
    try {
      refreshTask.value = await deleteAcFitAps(filters.ac_id, apIds)
      window.localStorage?.setItem(ACTIVE_TASK_KEY, refreshTask.value.task_id)
      scheduleTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'FIT-AP 批量删除启动失败'
    } finally {
      refreshStarting.value = false
    }
  }

  async function startFitApMetadataImport(file: File): Promise<void> {
    if (refreshStarting.value || (refreshTask.value && !TERMINAL_TASKS.has(refreshTask.value.status))) return
    refreshStarting.value = true
    operationError.value = ''
    try {
      refreshTask.value = await importAcFitApMetadata(file)
      window.localStorage?.setItem(ACTIVE_TASK_KEY, refreshTask.value.task_id)
      scheduleTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'FIT-AP 元数据导入启动失败'
    } finally {
      refreshStarting.value = false
    }
  }

  async function startFitApMetadataSave(metadata: {
    site_name: string
    mileage: string
    location_note: string
    direction: string
  }): Promise<void> {
    if (!filters.ac_id || !selected.value || refreshStarting.value || (refreshTask.value && !TERMINAL_TASKS.has(refreshTask.value.status))) return
    refreshStarting.value = true
    operationError.value = ''
    try {
      refreshTask.value = await saveAcFitApMetadata(filters.ac_id, selected.value.ap.id, metadata)
      window.localStorage?.setItem(ACTIVE_TASK_KEY, refreshTask.value.task_id)
      scheduleTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'FIT-AP 元数据保存启动失败'
    } finally {
      refreshStarting.value = false
    }
  }

  async function cancelRefreshTask(): Promise<void> {
    if (!refreshTask.value || TERMINAL_TASKS.has(refreshTask.value.status)) return
    try {
      refreshTask.value = await cancelAcWebTask(refreshTask.value.task_id)
      scheduleTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : '取消 AC / FIT-AP 更新失败'
    }
  }

  async function recoverRefreshTask(): Promise<void> {
    const saved = window.localStorage?.getItem(ACTIVE_TASK_KEY)
    const savedAction = window.localStorage?.getItem(ACTIVE_ACTION_TASK_KEY)
    try {
      const tasks = await recoverAcWebTasks()
      refreshTask.value = tasks.find((item) => item.task_id === saved)
        || tasks.find((item) => REFRESH_ACTIONS.has(item.action))
        || null
      if (refreshTask.value && !TERMINAL_TASKS.has(refreshTask.value.status)) scheduleTask()
      actionTask.value = tasks.find((item) => item.task_id === savedAction)
        || tasks.find((item) => item.action === 'ac_command_action_execute'
          && !TERMINAL_TASKS.has(item.status)
          && (!filters.ac_id || item.target_id === filters.ac_id))
        || null
      if (actionTask.value && !TERMINAL_TASKS.has(actionTask.value.status)) scheduleActionTask()
    } catch {
      if (saved) await pollTask(saved)
      if (savedAction) await pollActionTask(savedAction)
    }
  }

  async function trackActionTask(taskId: string): Promise<void> {
    actionTask.value = await getAcWebTask(taskId)
    window.localStorage?.setItem(ACTIVE_ACTION_TASK_KEY, taskId)
    scheduleActionTask()
  }

  async function pollActionTask(taskId: string): Promise<void> {
    try {
      actionTask.value = await getAcWebTask(taskId)
      if (TERMINAL_TASKS.has(actionTask.value.status)) window.localStorage?.removeItem(ACTIVE_ACTION_TASK_KEY)
      else scheduleActionTask()
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'AC 动作任务读取失败'
    }
  }

  async function pollTask(taskId: string): Promise<void> {
    try {
      refreshTask.value = await getAcWebTask(taskId)
      if (TERMINAL_TASKS.has(refreshTask.value.status)) {
        window.localStorage?.removeItem(ACTIVE_TASK_KEY)
        await manualRefresh()
      } else {
        scheduleTask()
      }
    } catch (cause) {
      operationError.value = cause instanceof Error ? cause.message : 'AC / FIT-AP 更新任务读取失败'
    }
  }

  function scheduleTask(): void {
    if (!refreshTask.value || TERMINAL_TASKS.has(refreshTask.value.status)) return
    if (taskTimer !== null) window.clearTimeout(taskTimer)
    taskTimer = window.setTimeout(() => void pollTask(refreshTask.value!.task_id), 1000)
  }

  function scheduleActionTask(): void {
    if (!actionTask.value || TERMINAL_TASKS.has(actionTask.value.status)) return
    if (actionTaskTimer !== null) window.clearTimeout(actionTaskTimer)
    actionTaskTimer = window.setTimeout(() => void pollActionTask(actionTask.value!.task_id), 1000)
  }

  function setAcId(value: string): void {
    filters.ac_id = value
    filters.page = 1
    snapshotPage.value = 1
    selected.value = null
    void Promise.all([refreshAps(), refreshSnapshots()])
  }

  function applyFilters(): void {
    filters.page = 1
    void refreshAps()
  }

  function setPage(page: number): void {
    filters.page = page
    void refreshAps()
  }

  function setPageSize(size: number): void {
    filters.page_size = size
    filters.page = 1
    void refreshAps()
  }

  function setSnapshotPage(page: number): void {
    snapshotPage.value = page
    void refreshSnapshots()
  }

  function setSnapshotType(value: string): void {
    snapshotType.value = value
    snapshotPage.value = 1
    void refreshSnapshots()
  }

  function startPolling(): void {
    if (polling) return
    polling = true
    void manualRefresh()
    void recoverRefreshTask()
    scheduleSummary()
    scheduleAps()
    scheduleDetail()
    scheduleSnapshots()
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [summaryTimer, apsTimer, detailTimer, snapshotTimer, taskTimer, actionTaskTimer]) {
      if (timer !== null) window.clearTimeout(timer)
    }
    summaryTimer = apsTimer = detailTimer = snapshotTimer = null
    taskTimer = null
    actionTaskTimer = null
  }

  function scheduleSummary(): void {
    summaryTimer = schedule(refreshSummary, 'summary', 15_000, scheduleSummary)
  }

  function scheduleAps(): void {
    apsTimer = schedule(refreshAps, 'aps', 30_000, scheduleAps)
  }

  function scheduleDetail(): void {
    detailTimer = schedule(refreshSelected, 'detail', 15_000, scheduleDetail)
  }

  function scheduleSnapshots(): void {
    snapshotTimer = schedule(refreshSnapshots, 'snapshots', 30_000, scheduleSnapshots)
  }

  function schedule(callback: () => Promise<void>, domain: RefreshDomain, delay: number, again: () => void): number | null {
    if (!polling) return null
    return window.setTimeout(async () => {
      await callback()
      if (polling) again()
    }, refreshFailureCounts[domain] >= 3 ? 60_000 : delay)
  }

  function recordSuccess(domain: RefreshDomain): void {
    refreshFailureCounts[domain] = 0
    refreshErrors[domain] = ''
  }

  function recordFailure(domain: RefreshDomain, _cause: unknown): void {
    refreshFailureCounts[domain] += 1
    if (refreshFailureCounts[domain] >= 3) refreshErrors[domain] = 'AC 数据刷新失败，已保留最后一次成功数据并降低刷新频率。'
    else refreshErrors[domain] = '部分 AC 数据刷新失败，已保留最后成功数据。'
  }

  return {
    summary,
    aps,
    total,
    selected,
    snapshots,
    snapshotTotal,
    configContent,
    configDiff,
    loading,
    detailLoading,
    configLoading,
    failures,
    error,
    refreshTask,
    actionTask,
    refreshStarting,
    filters,
    snapshotPage,
    snapshotPageSize,
    snapshotType,
    activeAc,
    refreshSummary,
    refreshAps,
    selectAp,
    refreshSnapshots,
    loadConfig,
    loadMoreConfig,
    loadDiff,
    manualRefresh,
    startAcInfoRefresh,
    startFitApRefresh,
    startFitApDetailRefresh,
    startOpticalRefresh,
    startApOpticalRefresh,
    startFitApDelete,
    startFitApMetadataImport,
    startFitApMetadataSave,
    cancelRefreshTask,
    recoverRefreshTask,
    trackActionTask,
    setAcId,
    applyFilters,
    setPage,
    setPageSize,
    setSnapshotPage,
    setSnapshotType,
    startPolling,
    stopPolling,
  }
})
