import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getRailTransitSummary,
  listDataQualityIssues,
  listRelations,
  listSections,
  listStations,
  listTracksideAps,
  listTrains,
  listVehicleMrs,
  previewRailTransitImport,
} from '../api/railTransitBaseData'
import type {
  DataQualityIssue,
  ImportPreviewResult,
  RailTransitSummary,
  Relation,
  Section,
  Station,
  TracksideAp,
  Train,
  VehicleMr,
} from '../types/railTransitBaseData'

export const useRailTransitBaseDataStore = defineStore('rail-transit-base-data', () => {
  const summary = ref<RailTransitSummary | null>(null)
  const stations = ref<Station[]>([])
  const sections = ref<Section[]>([])
  const aps = ref<TracksideAp[]>([])
  const trains = ref<Train[]>([])
  const mrs = ref<VehicleMr[]>([])
  const issues = ref<DataQualityIssue[]>([])
  const relations = ref<Relation[]>([])
  const apTotal = ref(0)
  const trainTotal = ref(0)
  const mrTotal = ref(0)
  const issueTotal = ref(0)
  const importPreview = ref<ImportPreviewResult | null>(null)
  const selectedFileName = ref('')
  const loading = ref(false)
  const previewLoading = ref(false)
  const failures = ref(0)
  const error = ref('')
  const apFilters = reactive({ query: '', station: '', section: '', line_side: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'name', sort_order: 'asc' })
  const mrFilters = reactive({ query: '', train: '', mr_role: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'train_no', sort_order: 'asc' })
  const issueFilters = reactive({ query: '', severity: '', entity_type: '', page: 1, page_size: 50 })
  let summaryTimer: number | null = null
  let runtimeTimer: number | null = null
  let staticTimer: number | null = null
  let summaryBusy = false
  let runtimeBusy = false
  let staticBusy = false
  let polling = false

  async function refreshSummary(): Promise<void> {
    if (summaryBusy) return
    summaryBusy = true
    try {
      summary.value = await getRailTransitSummary()
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally { summaryBusy = false }
  }

  async function refreshRuntime(): Promise<void> {
    if (runtimeBusy) return
    runtimeBusy = true
    try {
      const [apPage, trainPage, mrPage, relationPage] = await Promise.all([
        listTracksideAps(apFilters),
        listTrains({ page: 1, page_size: 100 }),
        listVehicleMrs(mrFilters),
        listRelations({ page: 1, page_size: 100 }),
      ])
      aps.value = apPage.items; apTotal.value = apPage.total
      trains.value = trainPage.items; trainTotal.value = trainPage.total
      mrs.value = mrPage.items; mrTotal.value = mrPage.total
      relations.value = relationPage.items
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally { runtimeBusy = false }
  }

  async function refreshStatic(): Promise<void> {
    if (staticBusy) return
    staticBusy = true
    try {
      const [stationPage, sectionPage, issuePage] = await Promise.all([
        listStations({ page: 1, page_size: 200 }),
        listSections({ page: 1, page_size: 200 }),
        listDataQualityIssues(issueFilters),
      ])
      stations.value = stationPage.items
      sections.value = sectionPage.items
      issues.value = issuePage.items; issueTotal.value = issuePage.total
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally { staticBusy = false }
  }

  async function manualRefresh(): Promise<void> {
    loading.value = true
    try { await Promise.all([refreshSummary(), refreshRuntime(), refreshStatic()]) }
    finally { loading.value = false }
  }

  async function previewImport(file: File): Promise<void> {
    previewLoading.value = true
    selectedFileName.value = file.name
    try {
      importPreview.value = await previewRailTransitImport(file)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
      throw cause
    } finally { previewLoading.value = false }
  }

  function applyApFilters(): void { apFilters.page = 1; void refreshRuntime() }
  function setApPage(page: number): void { apFilters.page = page; void refreshRuntime() }
  function applyMrFilters(): void { mrFilters.page = 1; void refreshRuntime() }
  function setMrPage(page: number): void { mrFilters.page = page; void refreshRuntime() }
  function applyIssueFilters(): void { issueFilters.page = 1; void refreshStatic() }
  function setIssuePage(page: number): void { issueFilters.page = page; void refreshStatic() }

  function startPolling(): void {
    if (polling) return
    polling = true
    void manualRefresh()
    scheduleSummary(); scheduleRuntime(); scheduleStatic()
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [summaryTimer, runtimeTimer, staticTimer]) if (timer !== null) window.clearTimeout(timer)
    summaryTimer = runtimeTimer = staticTimer = null
  }

  function scheduleSummary(): void { summaryTimer = schedule(refreshSummary, 30_000, scheduleSummary) }
  function scheduleRuntime(): void { runtimeTimer = schedule(refreshRuntime, 15_000, scheduleRuntime) }
  function scheduleStatic(): void { staticTimer = schedule(refreshStatic, 60_000, scheduleStatic) }
  function schedule(callback: () => Promise<void>, delay: number, again: () => void): number | null {
    if (!polling) return null
    return window.setTimeout(async () => { await callback(); if (polling) again() }, failures.value >= 3 ? 120_000 : delay)
  }

  function recordSuccess(): void { failures.value = 0; error.value = '' }
  function recordFailure(cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) error.value = '基础资料刷新连续失败，已保留最后成功数据并降低刷新频率。'
    else if (!summary.value && cause instanceof Error) error.value = cause.message
  }

  return {
    summary, stations, sections, aps, trains, mrs, issues, relations,
    apTotal, trainTotal, mrTotal, issueTotal, importPreview, selectedFileName,
    loading, previewLoading, failures, error, apFilters, mrFilters, issueFilters,
    refreshSummary, refreshRuntime, refreshStatic, manualRefresh, previewImport,
    applyApFilters, setApPage, applyMrFilters, setMrPage, applyIssueFilters, setIssuePage,
    startPolling, stopPolling,
  }
})
