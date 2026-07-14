import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getCurrentOnlineMrSession,
  getOnlineMrPreview,
  getOnlineMrRawTail,
  getOnlineMrSession,
  listOnlineMrCollectors,
  listOnlineMrRawFiles,
  listRecentOnlineMrSessions,
} from '../api/onlineMr'
import type {
  OnlineMrCollectorStatus,
  OnlineMrRawFile,
  OnlineMrRawTail,
  OnlineMrRealtimePreview,
  OnlineMrSessionDetail,
  OnlineMrSessionSummary,
} from '../types/onlineMr'

const ACTIVE_STATES = ['CREATED', 'CONNECTING', 'INITIALIZING', 'COLLECTING', 'RECONNECTING', 'RUNNING', 'STOPPING']

export const useOnlineMrStore = defineStore('online-mr', () => {
  const current = ref<OnlineMrSessionDetail | null>(null)
  const recent = ref<OnlineMrSessionSummary[]>([])
  const selected = ref<OnlineMrSessionDetail | null>(null)
  const collectors = ref<OnlineMrCollectorStatus[]>([])
  const preview = ref<OnlineMrRealtimePreview | null>(null)
  const rawFiles = ref<OnlineMrRawFile[]>([])
  const rawTail = ref<OnlineMrRawTail | null>(null)
  const rawSource = ref('collector_output')
  const loading = ref(false)
  const error = ref('')
  const failures = ref(0)
  let activeTimer: number | null = null
  let overviewTimer: number | null = null
  let rawTimer: number | null = null
  let activeBusy = false
  let overviewBusy = false
  let sessionBusy = false
  let rawBusy = false
  let polling = false
  let rawExpanded = false

  const active = computed(() => Boolean(selected.value && ACTIVE_STATES.includes(selected.value.status.toUpperCase())))

  async function refreshOverview(): Promise<void> {
    if (overviewBusy) return
    overviewBusy = true
    loading.value = !selected.value
    try {
      const [activeSession, rows] = await Promise.all([getCurrentOnlineMrSession(), listRecentOnlineMrSessions()])
      current.value = activeSession
      recent.value = rows
      const desired = selected.value?.session_id || activeSession?.session_id || rows[0]?.session_id
      if (desired) await loadSession(desired)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      overviewBusy = false
      loading.value = false
    }
  }

  async function refreshActive(): Promise<void> {
    const id = selected.value?.session_id || current.value?.session_id
    if (!id || activeBusy || sessionBusy) return
    if (selected.value && !ACTIVE_STATES.includes(selected.value.status.toUpperCase())) return
    activeBusy = true
    sessionBusy = true
    try {
      const [detail, nextPreview] = await Promise.all([getOnlineMrSession(id), getOnlineMrPreview(id)])
      selected.value = detail
      preview.value = nextPreview
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      activeBusy = false
      sessionBusy = false
    }
  }

  async function loadSession(id: string): Promise<void> {
    if (sessionBusy) return
    sessionBusy = true
    try {
      const [detail, nextCollectors, nextPreview, nextRawFiles] = await Promise.all([
        getOnlineMrSession(id),
        listOnlineMrCollectors(id),
        getOnlineMrPreview(id),
        listOnlineMrRawFiles(id),
      ])
      selected.value = detail
      collectors.value = nextCollectors
      preview.value = nextPreview
      rawFiles.value = nextRawFiles
      if (rawExpanded) await refreshRawTail()
    } finally {
      sessionBusy = false
    }
  }

  async function selectSession(id: string): Promise<void> {
    loading.value = true
    try {
      await loadSession(id)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      loading.value = false
    }
  }

  async function refreshRawTail(): Promise<void> {
    if (!rawExpanded || !selected.value || rawBusy) return
    rawBusy = true
    try {
      rawTail.value = await getOnlineMrRawTail(selected.value.session_id, rawSource.value)
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      rawBusy = false
    }
  }

  function setRawSource(name: string): void {
    rawSource.value = name
    rawTail.value = null
    if (rawExpanded) void refreshRawTail()
  }

  function setRawExpanded(value: boolean): void {
    rawExpanded = value
    if (rawTimer !== null) window.clearInterval(rawTimer)
    rawTimer = null
    if (value && polling) {
      void refreshRawTail()
      rawTimer = window.setInterval(() => void refreshRawTail(), 1000)
    }
  }

  function startPolling(): void {
    if (polling) return
    polling = true
    void refreshOverview()
    activeTimer = window.setInterval(() => void refreshActive(), 2000)
    overviewTimer = window.setInterval(() => void refreshOverview(), 5000)
    if (rawExpanded) setRawExpanded(true)
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [activeTimer, overviewTimer, rawTimer]) {
      if (timer !== null) window.clearInterval(timer)
    }
    activeTimer = overviewTimer = rawTimer = null
  }

  function recordSuccess(): void {
    failures.value = 0
    error.value = ''
  }

  function recordFailure(_cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) error.value = '状态刷新失败，请检查主程序服务或会话是否仍存在。'
  }

  return {
    current,
    recent,
    selected,
    collectors,
    preview,
    rawFiles,
    rawTail,
    rawSource,
    loading,
    error,
    failures,
    active,
    refreshOverview,
    refreshActive,
    selectSession,
    refreshRawTail,
    setRawSource,
    setRawExpanded,
    startPolling,
    stopPolling,
  }
})
