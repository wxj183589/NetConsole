import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getMeshLinkSummary,
  getMeshMrDetail,
  getMeshRawTail,
  listMeshLinks,
  listMeshMrs,
  listMeshSnapshots,
} from '../api/acMeshLink'
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

  async function refreshCore(): Promise<void> {
    if (coreBusy) return
    coreBusy = true
    loading.value = !summary.value
    try {
      const [summaryResult, mrResult, linkResult, snapshotResult] = await Promise.all([
        getMeshLinkSummary(),
        listMeshMrs({ ...filters, sort_by: 'train_no', sort_order: 'asc' }),
        listMeshLinks({ ...linkFilters, sort_by: 'mr_name', sort_order: 'asc' }),
        listMeshSnapshots(),
      ])
      summary.value = summaryResult
      mrs.value = mrResult.items
      mrTotal.value = mrResult.total
      links.value = linkResult.items
      linkTotal.value = linkResult.total
      snapshots.value = snapshotResult.items
      snapshotTotal.value = snapshotResult.total
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
  }

  function stopPolling(): void {
    polling = false
    if (coreTimer !== null) window.clearTimeout(coreTimer)
    if (rawTimer !== null) window.clearTimeout(rawTimer)
    coreTimer = rawTimer = null
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
    filters,
    linkFilters,
    refreshCore,
    selectMr,
    refreshRawTail,
    applyFilters,
    setMrPage,
    setLinkPage,
    setRawExpanded,
    startPolling,
    stopPolling,
  }
})
