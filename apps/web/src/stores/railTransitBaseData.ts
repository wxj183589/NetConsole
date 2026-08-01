import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import { apiErrorDetail, getHealth, type ApiErrorDetail } from '../api/client'
import { getTracksideApPlan } from '../api/tracksideApBusiness'
import {
  applyRailTransitImport,
  clearRailTransitBaseData,
  getRailTransitBaseDataClearPreview,
  getRailTransitBaseDataEditSnapshot,
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
  BaseDataClearPreview,
  BaseDataClearResult,
  BaseDataEditSession,
  BaseDataEditSnapshot,
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
import type { TracksideApPlanRow } from '../types/tracksideApBusiness'

type RefreshDomain = 'summary' | 'static' | 'runtime' | 'governance' | 'health'
type RefreshEndpointKey =
  | 'summary'
  | 'stations'
  | 'sections'
  | 'tracksideApPlan'
  | 'issueGroups'
  | 'tracksideAps'
  | 'trains'
  | 'vehicleMrs'
  | 'relations'
  | 'importPolicies'
  | 'importOperations'
  | 'editSession'
  | 'editSnapshot'
  | 'health'

export interface BaseDataRefreshError extends ApiErrorDetail {
  key: RefreshEndpointKey
  domain: RefreshDomain
  label: string
  failedAt: string
  retainedLastSuccess: boolean
  consecutiveFailures: number
  lastSuccessfulAt: string
}

const REFRESH_ENDPOINTS: Record<RefreshEndpointKey, {
  domain: RefreshDomain
  label: string
  path: string
}> = {
  summary: { domain: 'summary', label: '基础资料总览', path: '/api/rail-transit/base-data/summary' },
  stations: { domain: 'static', label: '站点资料', path: '/api/rail-transit/base-data/stations' },
  sections: { domain: 'static', label: '区间资料', path: '/api/rail-transit/base-data/sections' },
  tracksideApPlan: { domain: 'static', label: '轨旁 AP 规划', path: '/api/rail-transit/trackside-ap-business/plan' },
  issueGroups: { domain: 'static', label: '数据质量问题', path: '/api/rail-transit/base-data/issues/groups' },
  tracksideAps: { domain: 'runtime', label: '轨旁 AP', path: '/api/rail-transit/base-data/aps' },
  trains: { domain: 'runtime', label: '列车资料', path: '/api/rail-transit/base-data/trains' },
  vehicleMrs: { domain: 'runtime', label: '车载 MR', path: '/api/rail-transit/base-data/mrs' },
  relations: { domain: 'runtime', label: '关联运行状态', path: '/api/rail-transit/base-data/relations' },
  importPolicies: { domain: 'governance', label: '导入策略', path: '/api/rail-transit/base-data/import-policies' },
  importOperations: { domain: 'governance', label: '导入审计', path: '/api/rail-transit/base-data/import-operations' },
  editSession: { domain: 'governance', label: '编辑会话', path: '/api/rail-transit/base-data/revision' },
  editSnapshot: { domain: 'governance', label: '完整编辑快照', path: '/api/rail-transit/base-data/edit-snapshot' },
  health: { domain: 'health', label: 'Backend 健康检查', path: '/api/health' },
}
const SUMMARY_ENDPOINTS: RefreshEndpointKey[] = ['summary']
const STATIC_ENDPOINTS: RefreshEndpointKey[] = ['stations', 'sections', 'tracksideApPlan', 'issueGroups']
const RUNTIME_ENDPOINTS: RefreshEndpointKey[] = ['tracksideAps', 'trains', 'vehicleMrs', 'relations']
const GOVERNANCE_ENDPOINTS: RefreshEndpointKey[] = ['importPolicies', 'importOperations', 'editSession', 'editSnapshot']
const CORE_ENDPOINTS: RefreshEndpointKey[] = ['summary', 'stations', 'sections', 'tracksideApPlan', 'tracksideAps', 'trains', 'vehicleMrs', 'relations']

export const useRailTransitBaseDataStore = defineStore('rail-transit-base-data', () => {
  const summary = ref<RailTransitSummary | null>(null)
  const editSession = ref<BaseDataEditSession | null>(null)
  const editSnapshot = ref<BaseDataEditSnapshot | null>(null)
  const stations = ref<Station[]>([])
  const sections = ref<Section[]>([])
  const tracksideApPlans = ref<TracksideApPlanRow[]>([])
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
  const endpointErrors = reactive<Partial<Record<RefreshEndpointKey, BaseDataRefreshError>>>({})
  const endpointFailureCounts = reactive<Record<RefreshEndpointKey, number>>(
    Object.fromEntries(Object.keys(REFRESH_ENDPOINTS).map((key) => [key, 0])) as Record<RefreshEndpointKey, number>,
  )
  const endpointLastSuccessfulAt = reactive<Record<RefreshEndpointKey, string>>(
    Object.fromEntries(Object.keys(REFRESH_ENDPOINTS).map((key) => [key, ''])) as Record<RefreshEndpointKey, string>,
  )
  const healthError = ref<BaseDataRefreshError | null>(null)
  const backendState = ref<'unknown' | 'online' | 'offline'>('unknown')
  const summaryError = computed(() => endpointErrors.summary || null)
  const staticError = computed(() => errorsFor(STATIC_ENDPOINTS))
  const runtimeError = computed(() => errorsFor(RUNTIME_ENDPOINTS))
  const governanceError = computed(() => errorsFor(GOVERNANCE_ENDPOINTS))
  const refreshErrors = computed(() => [
    ...errorsFor([...SUMMARY_ENDPOINTS, ...STATIC_ENDPOINTS, ...RUNTIME_ENDPOINTS, ...GOVERNANCE_ENDPOINTS]),
    ...(healthError.value ? [healthError.value] : []),
  ])
  const backendOffline = computed(() => backendState.value === 'offline')
  const failures = computed(() => Math.max(0, ...Object.values(endpointFailureCounts)))
  const error = computed(() => {
    if (backendOffline.value) return 'Backend 连接中断，请重试。'
    if (refreshErrors.value.length) return '部分基础资料刷新失败，已保留最后成功数据。'
    return ''
  })
  const apFilters = reactive({ query: '', station: '', section: '', line_side: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'name', sort_order: 'asc' })
  const mrFilters = reactive({ query: '', train: '', mr_role: '', has_issue: undefined as boolean | undefined, page: 1, page_size: 50, sort_by: 'train_no', sort_order: 'asc' })
  const issueFilters = reactive({ query: '', blocking_only: undefined as boolean | undefined, needs_confirmation_only: undefined as boolean | undefined, page: 1, page_size: 50 })
  let summaryTimer: number | null = null
  let runtimeTimer: number | null = null
  let staticTimer: number | null = null
  let summaryRequest: Promise<void> | null = null
  let runtimeRequest: Promise<void> | null = null
  let staticRequest: Promise<void> | null = null
  let polling = false
  let healthProbe: Promise<void> | null = null

  function refreshSummary(probeBackend = true): Promise<void> {
    if (summaryRequest) return summaryRequest
    summaryRequest = (async () => {
      await refreshEndpoint('summary', getRailTransitSummary, (value) => { summary.value = value })
      if (probeBackend) await evaluateBackendReachability()
    })().finally(() => { summaryRequest = null })
    return summaryRequest
  }

  function refreshRuntime(probeBackend = true): Promise<void> {
    if (runtimeRequest) return runtimeRequest
    runtimeRequest = (async () => {
      await Promise.all([
        refreshEndpoint('tracksideAps', () => listTracksideAps(apFilters), (page) => {
          aps.value = page.items
          apTotal.value = page.total
        }),
        refreshEndpoint('trains', () => listTrains({ page: 1, page_size: 100 }), (page) => {
          trains.value = page.items
          trainTotal.value = page.total
        }),
        refreshEndpoint('vehicleMrs', () => listVehicleMrs(mrFilters), (page) => {
          mrs.value = page.items
          mrTotal.value = page.total
        }),
        refreshEndpoint('relations', () => listRelations({ page: 1, page_size: 100 }), (page) => {
          relations.value = page.items
        }),
      ])
      if (probeBackend) await evaluateBackendReachability()
    })().finally(() => { runtimeRequest = null })
    return runtimeRequest
  }

  function refreshStatic(probeBackend = true): Promise<void> {
    if (staticRequest) return staticRequest
    staticRequest = (async () => {
      await Promise.all([
        refreshEndpoint('stations', () => listStations({ page: 1, page_size: 200 }), (page) => {
          stations.value = page.items
        }),
        refreshEndpoint('sections', () => listSections({ page: 1, page_size: 200 }), (page) => {
          sections.value = page.items
        }),
        refreshEndpoint('tracksideApPlan', getTracksideApPlan, (plan) => {
          tracksideApPlans.value = plan.items
        }),
        refreshEndpoint('issueGroups', () => listDataQualityIssueGroups(issueFilters), (page) => {
          issueGroups.value = page.items
          issues.value = page.items.flatMap((item) => item.issues)
          issueTotal.value = page.issue_total
          issueGroupTotal.value = page.total
          issueCodeCounts.value = page.code_counts
        }),
      ])
      if (probeBackend) await evaluateBackendReachability()
    })().finally(() => { staticRequest = null })
    return staticRequest
  }

  async function manualRefresh(): Promise<void> {
    loading.value = true
    try {
      await Promise.all([refreshSummary(false), refreshRuntime(false), refreshStatic(false)])
      await evaluateBackendReachability()
    }
    finally { loading.value = false }
  }

  async function previewImport(file: File): Promise<void> {
    previewLoading.value = true
    selectedFileName.value = file.name
    try {
      importPreview.value = await previewRailTransitImport(file)
    } catch (cause) {
      throw cause
    } finally { previewLoading.value = false }
  }

  async function refreshStationSourcePreview(): Promise<StationSourcePreview> {
    stationSourceLoading.value = true
    try {
      stationSourcePreview.value = await getStationSourcePreview()
      return stationSourcePreview.value
    } catch (cause) {
      throw cause
    } finally { stationSourceLoading.value = false }
  }

  async function previewStationTemplateFile(file: File): Promise<StationTemplatePreview> {
    previewLoading.value = true
    selectedFileName.value = file.name
    try {
      stationTemplatePreview.value = await previewStationTemplate(file)
      return stationTemplatePreview.value
    } catch (cause) {
      throw cause
    } finally { previewLoading.value = false }
  }

  async function previewSectionsFromDraft(
    metadata: {
      main_path_code: string
      increasing_direction_name: string
      decreasing_direction_name: string
      increasing_direction_line_side: string
      decreasing_direction_line_side: string
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
      return sectionGenerationPreview.value
    } catch (cause) {
      throw cause
    } finally {
      sectionGenerationLoading.value = false
    }
  }

  async function refreshImportGovernance(): Promise<void> {
    await Promise.all([
      refreshEndpoint('importPolicies', getRailTransitImportPolicies, (value) => { importPolicies.value = value }),
      refreshEndpoint('importOperations', listRailTransitImportOperations, (value) => { importOperations.value = value }),
      refreshEndpoint('editSession', getRailTransitBaseDataEditSession, (value) => { editSession.value = value }),
    ])
    await evaluateBackendReachability()
  }

  async function refreshEditSession(): Promise<BaseDataEditSession> {
    try {
      const value = await getRailTransitBaseDataEditSession()
      editSession.value = value
      recordEndpointSuccess('editSession')
      return value
    } catch (cause) {
      recordEndpointFailure('editSession', cause)
      await evaluateBackendReachability()
      throw cause
    }
  }

  async function refreshEditSnapshot(): Promise<BaseDataEditSnapshot> {
    try {
      const value = await getRailTransitBaseDataEditSnapshot()
      editSnapshot.value = value
      editSession.value = {
        site_id: value.site_id,
        base_revision: value.base_revision,
        loaded_at: value.loaded_at,
        can_write: value.can_write,
        write_scope: value.write_scope,
        storage_mode: value.storage_mode,
        write_denial_code: value.write_denial_code,
        write_denial_reason: value.write_denial_reason,
      }
      recordEndpointSuccess('editSnapshot')
      return value
    } catch (cause) {
      recordEndpointFailure('editSnapshot', cause)
      await evaluateBackendReachability()
      throw cause
    }
  }

  async function previewClearAll(): Promise<BaseDataClearPreview> {
    return getRailTransitBaseDataClearPreview()
  }

  async function clearAll(preview: BaseDataClearPreview): Promise<BaseDataClearResult> {
    const result = await clearRailTransitBaseData({
      site_id: preview.site_id,
      base_revision: preview.base_revision,
      explicit_confirmation: true,
    })
    editSession.value = editSession.value
      ? { ...editSession.value, base_revision: result.revision, loaded_at: new Date().toISOString() }
      : null
    return result
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

  function scheduleSummary(): void { summaryTimer = schedule(refreshSummary, 30_000, scheduleSummary, SUMMARY_ENDPOINTS) }
  function scheduleRuntime(): void { runtimeTimer = schedule(refreshRuntime, 15_000, scheduleRuntime, RUNTIME_ENDPOINTS) }
  function scheduleStatic(): void { staticTimer = schedule(refreshStatic, 60_000, scheduleStatic, STATIC_ENDPOINTS) }
  function schedule(
    callback: () => Promise<void>,
    delay: number,
    again: () => void,
    keys: RefreshEndpointKey[],
  ): number | null {
    if (!polling) return null
    const repeatedFailure = keys.some((key) => endpointFailureCounts[key] >= 3)
    return window.setTimeout(async () => { await callback(); if (polling) again() }, repeatedFailure ? 120_000 : delay)
  }

  function errorsFor(keys: RefreshEndpointKey[]): BaseDataRefreshError[] {
    return keys.flatMap((key) => endpointErrors[key] ? [endpointErrors[key]!] : [])
  }

  function refreshError(key: RefreshEndpointKey, cause: unknown): BaseDataRefreshError {
    const endpoint = REFRESH_ENDPOINTS[key]
    return {
      key,
      domain: endpoint.domain,
      label: endpoint.label,
      failedAt: new Date().toISOString(),
      retainedLastSuccess: Boolean(endpointLastSuccessfulAt[key]),
      consecutiveFailures: endpointFailureCounts[key],
      lastSuccessfulAt: endpointLastSuccessfulAt[key],
      ...apiErrorDetail(cause, endpoint.path),
    }
  }

  async function refreshEndpoint<T>(
    key: RefreshEndpointKey,
    request: () => Promise<T>,
    apply: (value: T) => void,
  ): Promise<boolean> {
    try {
      const value = await request()
      apply(value)
      recordEndpointSuccess(key)
      return true
    } catch (cause) {
      recordEndpointFailure(key, cause)
      return false
    }
  }

  function recordEndpointSuccess(key: RefreshEndpointKey): void {
    endpointFailureCounts[key] = 0
    endpointLastSuccessfulAt[key] = new Date().toISOString()
    delete endpointErrors[key]
    if (!healthError.value) backendState.value = 'online'
  }

  function recordEndpointFailure(key: RefreshEndpointKey, cause: unknown): void {
    endpointFailureCounts[key] += 1
    const detail = refreshError(key, cause)
    endpointErrors[key] = detail
    if (detail.status > 0 && !healthError.value) {
      backendState.value = 'online'
    }
  }

  async function evaluateBackendReachability(): Promise<void> {
    const persistentTransportFailures = CORE_ENDPOINTS.filter((key) => {
      const detail = endpointErrors[key]
      return endpointFailureCounts[key] >= 3 && detail?.status === 0
    })
    const healthRecoveryRequired = Boolean(healthError.value)
    if (persistentTransportFailures.length < 2 && !healthRecoveryRequired) return
    if (!healthProbe) {
      healthProbe = (async () => {
        try {
          await getHealth()
          endpointFailureCounts.health = 0
          endpointLastSuccessfulAt.health = new Date().toISOString()
          backendState.value = 'online'
          healthError.value = null
        } catch (cause) {
          endpointFailureCounts.health += 1
          backendState.value = 'offline'
          healthError.value = refreshError('health', cause)
        }
      })().finally(() => { healthProbe = null })
    }
    await healthProbe
  }

  return {
    summary, editSession, editSnapshot, stations, sections, tracksideApPlans, aps, trains, mrs, issues, issueGroups, relations,
    apTotal, trainTotal, mrTotal, issueTotal, issueGroupTotal, issueCodeCounts, importPreview, stationSourcePreview, stationTemplatePreview, sectionGenerationPreview, importPolicies,
    importOperations, importChanges, selectedOperationId, selectedFileName,
    loading, previewLoading, stationSourceLoading, sectionGenerationLoading, applyLoading,
    failures, error, summaryError, staticError, runtimeError, governanceError, refreshErrors, backendOffline,
    apFilters, mrFilters, issueFilters,
    refreshSummary, refreshRuntime, refreshStatic, manualRefresh, previewImport, refreshStationSourcePreview, previewStationTemplateFile, previewSectionsFromDraft,
    refreshImportGovernance, refreshEditSession, refreshEditSnapshot, previewClearAll, clearAll, validateChanges, saveChanges, canApplyImport, applyImport, selectImportOperation, rollbackImport,
    applyApFilters, setApPage, applyMrFilters, setMrPage, applyIssueFilters, setIssuePage,
    startPolling, stopPolling,
  }
})
