import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import { getMrCommunication, getMrCommunicationPreview, getTrainCommunication, getTrainCommunicationSummary, listTrainCommunications } from '../api/trainCommunication'
import { getOnlineMrRawTail } from '../api/onlineMr'
import type { OnlineMrRawTail } from '../types/onlineMr'
import type { MrCommunicationDetail, TrainCommunicationDetail, TrainCommunicationRow, TrainCommunicationSummary } from '../types/trainCommunication'

export const useTrainCommunicationStore = defineStore('train-communication', () => {
  const summary = ref<TrainCommunicationSummary | null>(null)
  const trains = ref<TrainCommunicationRow[]>([])
  const total = ref(0)
  const selectedTrain = ref<TrainCommunicationDetail | null>(null)
  const selectedMr = ref<MrCommunicationDetail | null>(null)
  const rawTail = ref<OnlineMrRawTail | null>(null)
  const rawSource = ref('mesh_link')
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref('')
  const failures = ref(0)
  const filters = reactive({
    query: '', communication_status: '', station: '', section: '', active_only: false,
    agent_only: false, optical_anomaly_only: false, page: 1, page_size: 50,
    sort_by: 'train_no', sort_order: 'asc' as const,
  })
  const hasActive = computed(() => Boolean(summary.value?.active_online_mr_sessions))
  let polling = false
  let pageVisible = true
  let rawExpanded = false
  let coreBusy = false
  let detailBusy = false
  let rawBusy = false
  let coreTimer: number | null = null
  let detailTimer: number | null = null
  let rawTimer: number | null = null

  async function refreshCore(): Promise<void> {
    if (coreBusy || !pageVisible) return
    coreBusy = true
    loading.value = !summary.value
    try {
      const [nextSummary, page] = await Promise.all([getTrainCommunicationSummary(), listTrainCommunications({ ...filters })])
      summary.value = nextSummary
      trains.value = page.items
      total.value = page.total
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      loading.value = false
      coreBusy = false
    }
  }

  async function selectTrain(trainId: string): Promise<void> {
    detailLoading.value = true
    try {
      selectedTrain.value = await getTrainCommunication(trainId)
      selectedMr.value = null
      rawTail.value = null
      recordSuccess()
      scheduleDetail()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      detailLoading.value = false
    }
  }

  async function selectMr(mrId: string): Promise<void> {
    detailLoading.value = true
    try {
      selectedMr.value = await getMrCommunication(mrId)
      rawTail.value = null
      if (rawExpanded) await refreshRawTail()
      recordSuccess()
      scheduleDetail()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      detailLoading.value = false
    }
  }

  async function refreshDetail(): Promise<void> {
    if (detailBusy || !pageVisible) return
    const trainId = selectedTrain.value?.train.train_id
    const mrId = selectedMr.value?.mr.mr_id
    if (!trainId && !mrId) return
    detailBusy = true
    try {
      if (trainId) selectedTrain.value = await getTrainCommunication(trainId)
      if (mrId && selectedMr.value) selectedMr.value.mr = await getMrCommunicationPreview(mrId)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      detailBusy = false
    }
  }

  async function refreshRawTail(): Promise<void> {
    const sessionId = selectedMr.value?.mr.session_id
    if (!rawExpanded || !sessionId || rawBusy || !pageVisible) return
    rawBusy = true
    try {
      const tail = rawSource.value === 'collector_output' ? 300 : rawSource.value === 'fping_samples' ? 100 : 200
      rawTail.value = await getOnlineMrRawTail(sessionId, rawSource.value, tail)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      rawBusy = false
    }
  }

  function applyFilters(): void { filters.page = 1; void refreshCore() }
  function setPage(page: number): void { filters.page = page; void refreshCore() }
  function setRawSource(name: string): void { rawSource.value = name; rawTail.value = null; if (rawExpanded) void refreshRawTail() }
  function setRawExpanded(value: boolean): void { rawExpanded = value; clearTimer('raw'); if (value) { void refreshRawTail(); scheduleRaw() } }
  function setPageVisible(value: boolean): void { pageVisible = value; if (!value) clearAll(); else if (polling) scheduleAll() }

  function startPolling(): void {
    if (polling) return
    polling = true
    pageVisible = !document.hidden
    void refreshCore().finally(scheduleCore)
    scheduleDetail()
    if (rawExpanded) scheduleRaw()
  }
  function stopPolling(): void { polling = false; clearAll() }
  function scheduleAll(): void { scheduleCore(); scheduleDetail(); if (rawExpanded) scheduleRaw() }
  function scheduleCore(): void {
    clearTimer('core'); if (!polling || !pageVisible) return
    coreTimer = window.setTimeout(async () => { await refreshCore(); scheduleCore() }, failures.value >= 3 ? 15_000 : hasActive.value ? 2_000 : 10_000)
  }
  function scheduleDetail(): void {
    clearTimer('detail'); if (!polling || !pageVisible || (!selectedTrain.value && !selectedMr.value)) return
    detailTimer = window.setTimeout(async () => { await refreshDetail(); scheduleDetail() }, failures.value >= 3 ? 15_000 : selectedMr.value?.mr.is_active ? 1_500 : 10_000)
  }
  function scheduleRaw(): void {
    clearTimer('raw'); if (!polling || !pageVisible || !rawExpanded) return
    rawTimer = window.setTimeout(async () => { await refreshRawTail(); scheduleRaw() }, 1_000)
  }
  function clearTimer(kind: 'core' | 'detail' | 'raw'): void {
    const timer = kind === 'core' ? coreTimer : kind === 'detail' ? detailTimer : rawTimer
    if (timer !== null) window.clearTimeout(timer)
    if (kind === 'core') coreTimer = null
    else if (kind === 'detail') detailTimer = null
    else rawTimer = null
  }
  function clearAll(): void { clearTimer('core'); clearTimer('detail'); clearTimer('raw') }
  function recordSuccess(): void { failures.value = 0; error.value = '' }
  function recordFailure(cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) error.value = '通信状态刷新连续失败，已保留最后一次成功数据并降低刷新频率。'
    else if (!summary.value && cause instanceof Error) error.value = cause.message
  }

  return {
    summary, trains, total, selectedTrain, selectedMr, rawTail, rawSource, loading, detailLoading,
    error, failures, filters, hasActive, refreshCore, selectTrain, selectMr, refreshDetail, refreshRawTail,
    applyFilters, setPage, setRawSource, setRawExpanded, setPageVisible, startPolling, stopPolling,
  }
})
