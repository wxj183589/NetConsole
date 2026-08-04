import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getOnlineMrSession,
  listRecentOnlineMrSessions,
} from '../api/onlineMr'
import type {
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
} from '../types/onlineMr'

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
}

export type SessionRefreshResult = {
  applied: boolean
  selectionChanged: boolean
  selectedSessionId: string | null
}

export const useOnlineMrAnalysisStore = defineStore('online-mr-analysis', () => {
  const sessions = ref<OnlineMrSessionSummary[]>([])
  const selectedSessionId = ref<string | null>(null)
  const selectedSessionDetail = ref<OnlineMrSessionDetail | null>(null)
  const loading = ref(false)
  const siteKey = ref('')
  const deletedSessionIds = new Set<string>()

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
    selectedSessionId.value = null
    selectedSessionDetail.value = null
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
    selectedSessionDetail.value = null
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

  async function refreshSessions(options: RefreshOptions): Promise<SessionRefreshResult> {
    if (siteKey.value !== options.siteKey) resetForSite(options.siteKey)
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
      const visibleRows = rows.filter((item) => !deletedSessionIds.has(item.session_id))
      for (const deletedId of deletedSessionIds) {
        if (!rows.some((item) => item.session_id === deletedId)) deletedSessionIds.delete(deletedId)
      }
      const previous = selectedSessionId.value
      sessions.value = visibleRows
      const requested = options.requestedSessionId && visibleRows.some((item) => item.session_id === options.requestedSessionId)
        ? options.requestedSessionId
        : null
      const preferred = options.preferredSessionId && visibleRows.some((item) => item.session_id === options.preferredSessionId)
        ? options.preferredSessionId
        : null
      const retained = previous && visibleRows.some((item) => item.session_id === previous) ? previous : null
      const next = preferred || retained || requested || (options.selectFirstWhenEmpty ? visibleRows[0]?.session_id || null : null)
      const selectionChanged = next !== previous
      if (selectionChanged) selectSession(next)
      return { applied: true, selectionChanged, selectedSessionId: next }
    } finally {
      if (generation === listRequestGeneration) {
        loading.value = false
        if (listController === controller) listController = null
      }
    }
  }

  async function loadSelectedSession(requestSiteKey: string): Promise<OnlineMrSessionDetail | null> {
    const target = selectedSessionId.value
    if (!target || requestSiteKey !== siteKey.value || deletedSessionIds.has(target)) {
      selectedSessionDetail.value = null
      return null
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
      selectedSessionDetail.value = value
      return value
    } finally {
      if (generation === detailRequestGeneration && detailController === controller) detailController = null
    }
  }

  function dispose(): void {
    invalidateRequests()
    sessions.value = []
    selectedSessionId.value = null
    selectedSessionDetail.value = null
    deletedSessionIds.clear()
  }

  return {
    sessions,
    selectedSessionId,
    selectedSessionDetail,
    loading,
    siteKey,
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
    dispose,
  }
})
