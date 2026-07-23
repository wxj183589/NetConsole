import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  applyRailTransitImport,
  getRailTransitBaseDataEditSession,
  getRailTransitSummary,
  getRailTransitImportPolicies,
  getStationSourcePreview,
  listRailTransitImportChanges,
  listRailTransitImportOperations,
  listDataQualityIssueGroups,
  listRelations,
  listSections,
  listStations,
  listTracksideAps,
  listTrains,
  listVehicleMrs,
  previewRailTransitImport,
  previewSectionGeneration,
  previewStationTemplate,
  rollbackRailTransitImport,
  saveRailTransitBaseDataChanges,
  validateRailTransitBaseDataChanges,
} from '../api/railTransitBaseData'
import type {
  BaseDataChange,
  BaseDataEditSession,
  BaseDataSaveResult,
  BaseDataValidationResult,
  DataQualityIssue,
  DataQualityEntityGroup,
  ImportChange,
  ImportOperation,
  ImportPolicyStatus,
  ImportPreviewResult,
  MergeFieldDecision,
  RailTransitSummary,
  Relation,
  Section,
  SectionGenerationPreview,
  Station,
  StationSourcePreview,
  StationTemplatePreview,
  TracksideAp,
  Train,
  VehicleMr,
} from '../types/railTransitBaseData'

export const useRailTransitBaseDataStore = defineStore('rail-transit-base-data', () => {
  const summary = ref<RailTransitSummary | null>(null)
  const editSession = ref<BaseDataEditSession | null>(null)
  const stations = ref<Station[]>([])
  const sections = ref<Section[]>([])
  const aps = ref<TracksideAp[]>([])
  const trains = ref<Train[]>([])
  const mrs = ref<VehicleMr[]>([])
  const issues = ref<DataQualityIssue[]>([])
  const issueGroups = ref<DataQualityEntityGroup[]>([])
  const relations = ref<Relation[]>([])
  const apTotal = ref(0)
  const trainTotal = ref(0)
  const mrTotal = ref(0)
  const issueTotal = ref(0)
  const issueGroupTotal = ref(0)
  const issueCodeCounts = ref<Record<string, number>>({})
  const importPreview = ref<ImportPreviewResult | null>(null)
  const stationSourcePreview = ref<StationSourcePreview | null>(null)
  const stationTemplatePreview = ref<StationTemplatePreview | null>(null)
  const sectionGenerationPreview = ref<SectionGenerationPreview | null>(null)
  const importPolicies = ref<ImportPolicyStatus | null>(null)
  const importOperations = ref<ImportOperation[]>([])
  const importChanges = ref<ImportChange[]>([])
  const selectedOperationId = ref('')
  const selectedFileName = ref('')
  const loading = ref(false)
  const previewLoading = ref(false)
  const stationSourceLoading = ref(false)
  const sectionGenerationLoading = ref(false)
  const applyLoading = ref(false)
  const failures = ref(0)
  const error = ref('')
  const apFilters = reactive({ query: '', station: '', section: '', line_side: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'name', sort_order: 'asc' })
  const mrFilters = reactive({ query: '', train: '', mr_role: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'train_no', sort_order: 'asc' })
  const issueFilters = reactive({ query: '', blocking_only: undefined as boolean | undefined, needs_confirmation_only: undefined as boolean | undefined, page: 1, page_size: 50 })
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
        listDataQualityIssueGroups(issueFilters),
      ])
      stations.value = stationPage.items
      sections.value = sectionPage.items
      issueGroups.value = issuePage.items
      issues.value = issuePage.items.flatMap((item) => item.issues)
      issueTotal.value = issuePage.issue_total
      issueGroupTotal.value = issuePage.total
      issueCodeCounts.value = issuePage.code_counts
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

  async function refreshStationSourcePreview(): Promise<StationSourcePreview> {
    stationSourceLoading.value = true
    try {
      stationSourcePreview.value = await getStationSourcePreview()
      recordSuccess()
      return stationSourcePreview.value
    } catch (cause) {
      recordFailure(cause)
      throw cause
    } finally { stationSourceLoading.value = false }
  }

  async function previewStationTemplateFile(file: File): Promise<StationTemplatePreview> {
    previewLoading.value = true
    selectedFileName.value = file.name
    try {
      stationTemplatePreview.value = await previewStationTemplate(file)
      recordSuccess()
      return stationTemplatePreview.value
    } catch (cause) {
      recordFailure(cause)
      throw cause
    } finally { previewLoading.value = false }
  }

  async function previewSectionsFromDraft(
    metadata: {
      main_path_code: string
      increasing_direction_name: string
      decreasing_direction_name: string
    },
    stations: Station[],
    currentSections: Section[],
  ): Promise<SectionGenerationPreview> {
    if (!editSession.value) await refreshEditSession()
    sectionGenerationLoading.value = true
    try {
      sectionGenerationPreview.value = await previewSectionGeneration({
        site_id: editSession.value!.site_id,
        base_revision: editSession.value!.base_revision,
        line_metadata: metadata,
        stations,
        current_sections: currentSections,
      })
      recordSuccess()
      return sectionGenerationPreview.value
    } catch (cause) {
      recordFailure(cause)
      throw cause
    } finally {
      sectionGenerationLoading.value = false
    }
  }

  async function refreshImportGovernance(): Promise<void> {
    const [policies, operations, session] = await Promise.all([
      getRailTransitImportPolicies(),
      listRailTransitImportOperations(),
      getRailTransitBaseDataEditSession(),
    ])
    importPolicies.value = policies
    importOperations.value = operations
    editSession.value = session
  }

  async function refreshEditSession(): Promise<BaseDataEditSession> {
    editSession.value = await getRailTransitBaseDataEditSession()
    return editSession.value
  }

  async function validateChanges(changes: BaseDataChange[]): Promise<BaseDataValidationResult> {
    if (!editSession.value) await refreshEditSession()
    return validateRailTransitBaseDataChanges({
      site_id: editSession.value!.site_id,
      base_revision: editSession.value!.base_revision,
      changes,
    })
  }

  async function saveChanges(changes: BaseDataChange[]): Promise<BaseDataSaveResult> {
    if (!editSession.value) await refreshEditSession()
    const result = await saveRailTransitBaseDataChanges({
      site_id: editSession.value!.site_id,
      base_revision: editSession.value!.base_revision,
      changes,
      explicit_confirmation: true,
    })
    editSession.value = { ...editSession.value!, base_revision: result.revision, loaded_at: new Date().toISOString() }
    return result
  }

  function canApplyImport(): boolean {
    const policy = importPolicies.value
    return Boolean(policy?.feature_enabled && policy.write_enabled
      && (policy.write_scope === 'copy_validation' ? policy.copy_write_authorized : policy.real_write_authorized))
  }

  async function applyImport(decisions: MergeFieldDecision[]): Promise<string> {
    const preview = importPreview.value
    if (!preview?.merge_plan || !canApplyImport()) throw new Error('基础资料写入未授权')
    applyLoading.value = true
    try {
      const result = await applyRailTransitImport({
        preview_id: preview.preview_id,
        site_id: preview.merge_plan.site_id,
        explicit_confirmation: true,
        decisions,
        expected_database_sha256: preview.database_hash,
      })
      await refreshImportGovernance().catch(() => undefined)
      return result.operation_id
    } finally { applyLoading.value = false }
  }

  async function selectImportOperation(operationId: string): Promise<void> {
    selectedOperationId.value = operationId
    importChanges.value = await listRailTransitImportChanges(operationId)
  }

  async function rollbackImport(operationId: string): Promise<void> {
    if (!importPolicies.value?.rollback_enabled || !canApplyImport()) throw new Error('基础资料回滚未授权')
    applyLoading.value = true
    try {
      await rollbackRailTransitImport(operationId)
      await refreshImportGovernance().catch(() => undefined)
      if (selectedOperationId.value === operationId) {
        await selectImportOperation(operationId).catch(() => undefined)
      }
    } finally { applyLoading.value = false }
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
    summary, editSession, stations, sections, aps, trains, mrs, issues, issueGroups, relations,
    apTotal, trainTotal, mrTotal, issueTotal, issueGroupTotal, issueCodeCounts, importPreview, stationSourcePreview, stationTemplatePreview, sectionGenerationPreview, importPolicies,
    importOperations, importChanges, selectedOperationId, selectedFileName,
    loading, previewLoading, stationSourceLoading, sectionGenerationLoading, applyLoading, failures, error, apFilters, mrFilters, issueFilters,
    refreshSummary, refreshRuntime, refreshStatic, manualRefresh, previewImport, refreshStationSourcePreview, previewStationTemplateFile, previewSectionsFromDraft,
    refreshImportGovernance, refreshEditSession, validateChanges, saveChanges, canApplyImport, applyImport, selectImportOperation, rollbackImport,
    applyApFilters, setApPage, applyMrFilters, setMrPage, applyIssueFilters, setIssuePage,
    startPolling, stopPolling,
  }
})
