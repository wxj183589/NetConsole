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
import type {
  AcAp,
  AcApDetail,
  AcConfigContent,
  AcConfigDiff,
  AcConfigSnapshot,
  AcManagementSummary,
} from '../types/acManagement'

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
  const failures = ref(0)
  const error = ref('')
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
    sort_by: 'name',
    sort_order: 'asc' as 'asc' | 'desc',
  })
  const snapshotPage = ref(1)
  const snapshotPageSize = ref(30)
  const snapshotType = ref('')
  let summaryBusy = false
  let apsBusy = false
  let detailBusy = false
  let snapshotBusy = false
  let polling = false
  let summaryTimer: number | null = null
  let apsTimer: number | null = null
  let detailTimer: number | null = null
  let snapshotTimer: number | null = null

  const activeAc = computed(() => summary.value?.acs.find((item) => item.id === filters.ac_id) || summary.value?.acs[0])

  async function refreshSummary(): Promise<void> {
    if (summaryBusy) return
    summaryBusy = true
    try {
      summary.value = await getAcSummary()
      if (!filters.ac_id && summary.value.acs.length) filters.ac_id = summary.value.acs[0].id
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
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
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      apsBusy = false
      loading.value = false
    }
  }

  async function selectAp(apId: string): Promise<void> {
    if (detailBusy) return
    detailBusy = true
    detailLoading.value = true
    try {
      selected.value = await getAcApDetail(apId)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
      if (cause instanceof Error) error.value = cause.message
    } finally {
      detailBusy = false
      detailLoading.value = false
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
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      snapshotBusy = false
    }
  }

  async function loadConfig(snapshotId: number): Promise<void> {
    configLoading.value = true
    configDiff.value = null
    try {
      configContent.value = await getAcConfigSnapshot(snapshotId)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
      if (cause instanceof Error) error.value = cause.message
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
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
      if (cause instanceof Error) error.value = cause.message
    } finally {
      configLoading.value = false
    }
  }

  async function loadDiff(snapshotId: number): Promise<void> {
    configLoading.value = true
    configContent.value = null
    try {
      configDiff.value = await getAcConfigDiff(snapshotId)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
      if (cause instanceof Error) error.value = cause.message
    } finally {
      configLoading.value = false
    }
  }

  async function manualRefresh(): Promise<void> {
    await refreshSummary()
    await Promise.all([refreshAps(), refreshSnapshots(), refreshSelected()])
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
    scheduleSummary()
    scheduleAps()
    scheduleDetail()
    scheduleSnapshots()
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [summaryTimer, apsTimer, detailTimer, snapshotTimer]) {
      if (timer !== null) window.clearTimeout(timer)
    }
    summaryTimer = apsTimer = detailTimer = snapshotTimer = null
  }

  function scheduleSummary(): void {
    summaryTimer = schedule(refreshSummary, 15_000, scheduleSummary)
  }

  function scheduleAps(): void {
    apsTimer = schedule(refreshAps, 30_000, scheduleAps)
  }

  function scheduleDetail(): void {
    detailTimer = schedule(refreshSelected, 15_000, scheduleDetail)
  }

  function scheduleSnapshots(): void {
    snapshotTimer = schedule(refreshSnapshots, 30_000, scheduleSnapshots)
  }

  function schedule(callback: () => Promise<void>, delay: number, again: () => void): number | null {
    if (!polling) return null
    return window.setTimeout(async () => {
      await callback()
      if (polling) again()
    }, failures.value >= 3 ? 60_000 : delay)
  }

  function recordSuccess(): void {
    failures.value = 0
    error.value = ''
  }

  function recordFailure(cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) error.value = 'AC 数据刷新失败，已保留最后一次成功数据并降低刷新频率。'
    else if (!aps.value.length && cause instanceof Error) error.value = cause.message
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
