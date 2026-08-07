import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getOnlineMrSession,
  listRecentOnlineMrSessions,
} from '../api/onlineMr'
import type {
  OnlineMrBusinessRow,
  OnlineMrBusinessSummary,
  OnlineMrBusinessTable,
  OnlineMrMetricSeries,
  OnlineMrRawFile,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
  OnlineMrSwitchRssiSource,
  OnlineMrSwitchRssiWindow,
} from '../types/onlineMr'
import type { MeshChartViewport } from '../components/mesh-analysis/meshChartViewport'

const ACTIVE_SESSION_STATES = new Set([
  'CREATED',
  'CONNECTING',
  'INITIALIZING',
  'COLLECTING',
  'RECONNECTING',
  'STARTING',
  'RUNNING',
  'STOPPING',
  'VALIDATING',
  'PREPARING_TASK',
  'PREPARING_SESSION',
  'STARTING_COLLECTION',
  'STOPPING_TRAFFIC',
  'STOPPING_COLLECTION',
])
const FINALIZING_SESSION_STATES = new Set([
  'FINALIZING',
  'PARSING',
  'PACKAGING',
  'ARCHIVING',
  'RECOVERING',
])
const ACTIVE_TASK_STATES = new Set(['PENDING', 'STARTING', 'RUNNING', 'STOPPING'])
const ACTIVE_MAPPING_STATES = new Set(['PENDING_SESSION', 'LINKED'])

export function onlineMrSessionDeleteBlockReason(session: OnlineMrSessionSummary | null | undefined): string {
  if (!session) return ''
  const status = String(session.status || '').toUpperCase()
  const phase = String(session.phase || '').toUpperCase()
  if (FINALIZING_SESSION_STATES.has(status) || FINALIZING_SESSION_STATES.has(phase)) {
    return '会话正在归档、解析或打包，无法删除。'
  }
  if (ACTIVE_SESSION_STATES.has(status) || ACTIVE_SESSION_STATES.has(phase)) {
    return '会话正在采集中，无法删除。'
  }
  if (ACTIVE_TASK_STATES.has(String(session.task_status || '').toUpperCase())
    || ACTIVE_MAPPING_STATES.has(String(session.mapping_state || '').toUpperCase())) {
    return '会话资源正在使用，无法删除。'
  }
  return ''
}

type RefreshOptions = {
  siteKey: string
  requestedSessionId?: string | null
  preferredSessionId?: string | null
  selectFirstWhenEmpty?: boolean
  force?: boolean
}

export type SessionRefreshResult = {
  applied: boolean
  selectionChanged: boolean
  selectedSessionId: string | null
}

export interface OnlineMrAnalysisSessionCache {
  siteKey: string
  sessionId: string
  revision: string | null
  detail: OnlineMrSessionDetail | null
  detailLoaded: boolean
  activeTab: string
  chartTab: string
  startTime: string
  endTime: string
  downsample: 'NONE' | 'BUCKET_AVG' | 'MIN_MAX' | 'LATEST_PER_BUCKET'
  bucketSeconds: number
  businessSummary: OnlineMrBusinessSummary | null
  businessSummaryLoaded: boolean
  businessRows: Record<OnlineMrBusinessTable, OnlineMrBusinessRow[]>
  businessOffsets: Record<OnlineMrBusinessTable, number>
  businessHasMore: Record<OnlineMrBusinessTable, boolean>
  businessLoaded: Record<OnlineMrBusinessTable, boolean>
  metrics: Record<string, OnlineMrMetricSeries[]>
  metricOffsets: Record<string, number>
  metricHasMore: Record<string, boolean>
  metricLoaded: Record<string, boolean>
  switchWindows: Record<OnlineMrSwitchRssiSource, OnlineMrSwitchRssiWindow[]>
  switchOffsets: Record<OnlineMrSwitchRssiSource, number>
  switchHasMore: Record<OnlineMrSwitchRssiSource, boolean>
  switchLoaded: Record<OnlineMrSwitchRssiSource, boolean>
  rawFiles: OnlineMrRawFile[]
  rawFilesLoaded: boolean
  rawTail: string[]
  rawName: string
  rssiViewport: MeshChartViewport | null
  rssiLayoutMode: 'compare' | 'active-focus' | 'trackside-focus'
  rssiSplitRatio: number
  selectedRadio: number | null
  pointLimit: number
  showPeerRssi: boolean
  showSwitchLines: boolean
  showSwitchPoints: boolean
  showLocationBand: boolean
  cursorTime: string | null
  cursorSource: 'active-rssi' | 'trackside-rssi' | 'timeline-metric' | 'programmatic' | null
  selectedTime: string | null
  timeRangeLocked: boolean
  selectedTimeLocked: boolean
  immersiveMode: boolean
  relatedMetricKey: string
  loadedAt: number
  lastAccessedAt: number
}

const BUSINESS_TABLES: readonly OnlineMrBusinessTable[] = [
  'main_link',
  'link_detail',
  'channel_busy',
  'switch_history',
  'switch_realtime',
  'interface_rate',
  'fping_1s',
  'iperf',
  'diagnostics',
]
const SESSION_CACHE_LIMIT = 8

function businessRecord<T>(factory: () => T): Record<OnlineMrBusinessTable, T> {
  return Object.fromEntries(BUSINESS_TABLES.map((table) => [table, factory()])) as Record<OnlineMrBusinessTable, T>
}

export function createOnlineMrAnalysisSessionCache(siteKey: string, sessionId: string): OnlineMrAnalysisSessionCache {
  const now = Date.now()
  return {
    siteKey,
    sessionId,
    revision: null,
    detail: null,
    detailLoaded: false,
    activeTab: 'session-history',
    chartTab: 'rssi',
    startTime: '',
    endTime: '',
    downsample: 'LATEST_PER_BUCKET',
    bucketSeconds: 1,
    businessSummary: null,
    businessSummaryLoaded: false,
    businessRows: businessRecord<OnlineMrBusinessRow[]>(() => []),
    businessOffsets: businessRecord(() => 0),
    businessHasMore: businessRecord(() => false),
    businessLoaded: businessRecord(() => false),
    metrics: {},
    metricOffsets: {},
    metricHasMore: {},
    metricLoaded: {},
    switchWindows: { history: [], realtime: [] },
    switchOffsets: { history: 0, realtime: 0 },
    switchHasMore: { history: false, realtime: false },
    switchLoaded: { history: false, realtime: false },
    rawFiles: [],
    rawFilesLoaded: false,
    rawTail: [],
    rawName: '',
    rssiViewport: null,
    rssiLayoutMode: 'compare',
    rssiSplitRatio: 0.5,
    selectedRadio: null,
    pointLimit: 600,
    showPeerRssi: false,
    showSwitchLines: true,
    showSwitchPoints: true,
    showLocationBand: true,
    cursorTime: null,
    cursorSource: null,
    selectedTime: null,
    timeRangeLocked: false,
    selectedTimeLocked: false,
    immersiveMode: false,
    relatedMetricKey: 'ping-loss',
    loadedAt: now,
    lastAccessedAt: now,
  }
}

export function onlineMrAnalysisCacheKey(siteKey: string, sessionId: string): string {
  return `${siteKey}\0${sessionId}`
}

export function onlineMrSessionRevision(detail: OnlineMrSessionDetail): string {
  const database = detail.database_summary
  return JSON.stringify([
    database.parser_version,
    database.schema_version,
    database.modified_at,
    detail.latest_metric_time,
    detail.data_integrity,
    detail.status,
    detail.stopped_at,
  ])
}

export const useOnlineMrAnalysisStore = defineStore('online-mr-analysis', () => {
  const sessions = ref<OnlineMrSessionSummary[]>([])
  const selectedSessionId = ref<string | null>(null)
  const selectedSessionDetail = ref<OnlineMrSessionDetail | null>(null)
  const loading = ref(false)
  const siteKey = ref('')
  const sessionsLoaded = ref(false)
  const sessionCaches = reactive(new Map<string, OnlineMrAnalysisSessionCache>())
  const deletedSessionIds = new Set<string>()
  const inFlightRequests = new Map<string, Promise<unknown>>()

  let siteGeneration = 0
  let listRequestGeneration = 0
  let detailRequestGeneration = 0
  let listController: AbortController | null = null
  let detailController: AbortController | null = null

  const hasSelection = computed(() => Boolean(selectedSessionId.value))

  function abortListRequest(): void {
    listController?.abort()
    listController = null
    listRequestGeneration += 1
  }

  function abortDetailRequest(): void {
    detailController?.abort()
    detailController = null
    detailRequestGeneration += 1
  }

  function resetForSite(nextSiteKey: string): void {
    siteGeneration += 1
    siteKey.value = nextSiteKey
    abortListRequest()
    abortDetailRequest()
    sessions.value = []
    sessionsLoaded.value = false
    selectedSessionId.value = null
    selectedSessionDetail.value = null
    sessionCaches.clear()
    inFlightRequests.clear()
    deletedSessionIds.clear()
  }

  function invalidateRequests(): void {
    abortListRequest()
    abortDetailRequest()
    siteGeneration += 1
  }

  function clearSelectedSession(): void {
    selectSession(null)
  }

  function selectSession(sessionId: string | null): boolean {
    const next = sessionId && !deletedSessionIds.has(sessionId) ? sessionId : null
    if (selectedSessionId.value === next) return false
    abortDetailRequest()
    selectedSessionId.value = next
    selectedSessionDetail.value = next
      ? sessionCaches.get(onlineMrAnalysisCacheKey(siteKey.value, next))?.detail || null
      : null
    return true
  }

  function markDeleted(sessionId: string): void {
    if (!sessionId) return
    deletedSessionIds.add(sessionId)
    abortListRequest()
    if (selectedSessionId.value === sessionId) {
      abortDetailRequest()
      selectedSessionDetail.value = null
    }
    removeSessionCache(siteKey.value, sessionId)
  }

  function clearDeleted(sessionId: string): void {
    deletedSessionIds.delete(sessionId)
  }

  function isDeleted(sessionId: string): boolean {
    return deletedSessionIds.has(sessionId)
  }

  function removeSessionLocally(sessionId: string): number {
    const index = sessions.value.findIndex((item) => item.session_id === sessionId)
    markDeleted(sessionId)
    sessions.value = sessions.value.filter((item) => item.session_id !== sessionId)
    return index
  }

  function sessionById(sessionId: string): OnlineMrSessionSummary | null {
    return sessions.value.find((item) => item.session_id === sessionId) || null
  }

  function trimSessionCaches(): void {
    if (sessionCaches.size <= SESSION_CACHE_LIMIT) return
    const oldest = [...sessionCaches.entries()]
      .filter(([, value]) => value.sessionId !== selectedSessionId.value)
      .sort((left, right) => left[1].lastAccessedAt - right[1].lastAccessedAt)[0]
    if (oldest) sessionCaches.delete(oldest[0])
  }

  function getSessionCache(requestSiteKey: string, sessionId: string): OnlineMrAnalysisSessionCache | null {
    const cache = sessionCaches.get(onlineMrAnalysisCacheKey(requestSiteKey, sessionId)) || null
    if (cache) cache.lastAccessedAt = Date.now()
    return cache
  }

  function saveSessionCache(value: OnlineMrAnalysisSessionCache): void {
    value.lastAccessedAt = Date.now()
    sessionCaches.set(onlineMrAnalysisCacheKey(value.siteKey, value.sessionId), value)
    trimSessionCaches()
    if (value.siteKey === siteKey.value && value.sessionId === selectedSessionId.value) {
      selectedSessionDetail.value = value.detail
    }
  }

  function invalidateSessionAnalysis(requestSiteKey: string, sessionId: string): void {
    const existing = getSessionCache(requestSiteKey, sessionId)
    if (!existing) return
    const replacement = createOnlineMrAnalysisSessionCache(requestSiteKey, sessionId)
    Object.assign(replacement, {
      detail: existing.detail,
      detailLoaded: existing.detailLoaded,
      revision: existing.revision,
      activeTab: existing.activeTab,
      chartTab: existing.chartTab,
      startTime: existing.startTime,
      endTime: existing.endTime,
      downsample: existing.downsample,
      bucketSeconds: existing.bucketSeconds,
      rssiViewport: existing.rssiViewport,
      rssiLayoutMode: existing.rssiLayoutMode,
      rssiSplitRatio: existing.rssiSplitRatio,
      selectedRadio: existing.selectedRadio,
      pointLimit: existing.pointLimit,
      showPeerRssi: existing.showPeerRssi,
      showSwitchLines: existing.showSwitchLines,
      showSwitchPoints: existing.showSwitchPoints,
      showLocationBand: existing.showLocationBand,
      cursorTime: existing.cursorTime,
      cursorSource: existing.cursorSource,
      selectedTime: existing.selectedTime,
      timeRangeLocked: existing.timeRangeLocked,
      selectedTimeLocked: existing.selectedTimeLocked,
      immersiveMode: existing.immersiveMode,
      relatedMetricKey: existing.relatedMetricKey,
    })
    saveSessionCache(replacement)
  }

  function invalidateSession(requestSiteKey: string, sessionId: string): void {
    const existing = getSessionCache(requestSiteKey, sessionId)
    const replacement = createOnlineMrAnalysisSessionCache(requestSiteKey, sessionId)
    if (existing) {
      Object.assign(replacement, {
        activeTab: existing.activeTab,
        chartTab: existing.chartTab,
        startTime: existing.startTime,
        endTime: existing.endTime,
        downsample: existing.downsample,
        bucketSeconds: existing.bucketSeconds,
        rssiViewport: existing.rssiViewport,
        rssiLayoutMode: existing.rssiLayoutMode,
        rssiSplitRatio: existing.rssiSplitRatio,
        selectedRadio: existing.selectedRadio,
        pointLimit: existing.pointLimit,
        showPeerRssi: existing.showPeerRssi,
        showSwitchLines: existing.showSwitchLines,
        showSwitchPoints: existing.showSwitchPoints,
        showLocationBand: existing.showLocationBand,
        cursorTime: existing.cursorTime,
        cursorSource: existing.cursorSource,
        selectedTime: existing.selectedTime,
        timeRangeLocked: existing.timeRangeLocked,
        selectedTimeLocked: existing.selectedTimeLocked,
        immersiveMode: existing.immersiveMode,
        relatedMetricKey: existing.relatedMetricKey,
      })
    }
    saveSessionCache(replacement)
    if (requestSiteKey === siteKey.value && sessionId === selectedSessionId.value) {
      selectedSessionDetail.value = null
    }
  }

  function removeSessionCache(requestSiteKey: string, sessionId: string): void {
    const prefix = `${onlineMrAnalysisCacheKey(requestSiteKey, sessionId)}\0`
    sessionCaches.delete(onlineMrAnalysisCacheKey(requestSiteKey, sessionId))
    for (const key of inFlightRequests.keys()) {
      if (key.startsWith(prefix)) inFlightRequests.delete(key)
    }
  }

  async function runDeduped<T>(key: string, request: () => Promise<T>): Promise<T> {
    const existing = inFlightRequests.get(key) as Promise<T> | undefined
    if (existing) return existing
    const pending = request().finally(() => {
      if (inFlightRequests.get(key) === pending) inFlightRequests.delete(key)
    })
    inFlightRequests.set(key, pending)
    return pending
  }

  function applySessionRows(rows: OnlineMrSessionSummary[], options: RefreshOptions): SessionRefreshResult {
    const visibleRows = rows.filter((item) => !deletedSessionIds.has(item.session_id))
    const previous = selectedSessionId.value
    sessions.value = visibleRows
    const requested = options.requestedSessionId && visibleRows.some((item) => item.session_id === options.requestedSessionId)
      ? options.requestedSessionId
      : null
    const preferred = options.preferredSessionId && visibleRows.some((item) => item.session_id === options.preferredSessionId)
      ? options.preferredSessionId
      : null
    const retained = previous && visibleRows.some((item) => item.session_id === previous) ? previous : null
    const next = preferred || requested || retained || (options.selectFirstWhenEmpty ? visibleRows[0]?.session_id || null : null)
    const selectionChanged = next !== previous
    if (selectionChanged) selectSession(next)
    return { applied: true, selectionChanged, selectedSessionId: next }
  }

  async function refreshSessions(options: RefreshOptions): Promise<SessionRefreshResult> {
    if (siteKey.value !== options.siteKey) resetForSite(options.siteKey)
    if (sessionsLoaded.value && !options.force) return applySessionRows(sessions.value, options)
    const generation = ++listRequestGeneration
    const currentSiteGeneration = siteGeneration
    listController?.abort()
    const controller = new AbortController()
    listController = controller
    loading.value = true
    try {
      const rows = await listRecentOnlineMrSessions(100, controller.signal)
      if (generation !== listRequestGeneration || currentSiteGeneration !== siteGeneration || controller.signal.aborted) {
        return { applied: false, selectionChanged: false, selectedSessionId: selectedSessionId.value }
      }
      for (const deletedId of deletedSessionIds) {
        if (!rows.some((item) => item.session_id === deletedId)) deletedSessionIds.delete(deletedId)
      }
      sessionsLoaded.value = true
      return applySessionRows(rows, options)
    } finally {
      if (generation === listRequestGeneration) {
        loading.value = false
        if (listController === controller) listController = null
      }
    }
  }

  async function loadSelectedSession(requestSiteKey: string, force = false): Promise<OnlineMrSessionDetail | null> {
    const target = selectedSessionId.value
    if (!target || requestSiteKey !== siteKey.value || deletedSessionIds.has(target)) {
      selectedSessionDetail.value = null
      return null
    }
    const cached = getSessionCache(requestSiteKey, target)
    if (!force && cached?.detailLoaded) {
      selectedSessionDetail.value = cached.detail
      return cached.detail
    }
    const generation = ++detailRequestGeneration
    const currentSiteGeneration = siteGeneration
    detailController?.abort()
    const controller = new AbortController()
    detailController = controller
    try {
      const value = await getOnlineMrSession(target, controller.signal)
      if (generation !== detailRequestGeneration
        || currentSiteGeneration !== siteGeneration
        || controller.signal.aborted
        || selectedSessionId.value !== target
        || deletedSessionIds.has(target)) return null
      const existing = getSessionCache(requestSiteKey, target)
      const revision = onlineMrSessionRevision(value)
      if (existing?.revision && existing.revision !== revision) invalidateSessionAnalysis(requestSiteKey, target)
      const nextCache = getSessionCache(requestSiteKey, target) || createOnlineMrAnalysisSessionCache(requestSiteKey, target)
      nextCache.detail = value
      nextCache.detailLoaded = true
      nextCache.revision = revision
      nextCache.loadedAt = Date.now()
      saveSessionCache(nextCache)
      selectedSessionDetail.value = value
      return value
    } finally {
      if (generation === detailRequestGeneration && detailController === controller) detailController = null
    }
  }

  function dispose(): void {
    invalidateRequests()
    sessions.value = []
    sessionsLoaded.value = false
    selectedSessionId.value = null
    selectedSessionDetail.value = null
    sessionCaches.clear()
    inFlightRequests.clear()
    deletedSessionIds.clear()
  }

  return {
    sessions,
    selectedSessionId,
    selectedSessionDetail,
    loading,
    siteKey,
    sessionsLoaded,
    sessionCaches,
    hasSelection,
    refreshSessions,
    loadSelectedSession,
    resetForSite,
    invalidateRequests,
    clearSelectedSession,
    selectSession,
    markDeleted,
    clearDeleted,
    isDeleted,
    removeSessionLocally,
    sessionById,
    getSessionCache,
    saveSessionCache,
    invalidateSessionAnalysis,
    invalidateSession,
    removeSessionCache,
    runDeduped,
    dispose,
  }
})
