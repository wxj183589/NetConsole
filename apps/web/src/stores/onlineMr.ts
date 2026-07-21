import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getCurrentOnlineMrSession,
  getOnlineMrPreview,
  getOnlineMrRawTail,
  listOnlineMrCollectors,
  listOnlineMrRawFiles,
} from '../api/onlineMr'
import type {
  OnlineMrCollectorStatus,
  OnlineMrRawFile,
  OnlineMrRawTail,
  OnlineMrRealtimePreview,
  OnlineMrSessionDetail,
} from '../types/onlineMr'

const ACTIVE_STATES = ['CREATED', 'CONNECTING', 'INITIALIZING', 'COLLECTING', 'RECONNECTING', 'RUNNING', 'STOPPING']

export const useOnlineMrStore = defineStore('online-mr', () => {
  const current = ref<OnlineMrSessionDetail | null>(null)
  const selected = ref<OnlineMrSessionDetail | null>(null)
  const collectors = ref<OnlineMrCollectorStatus[]>([])
  const preview = ref<OnlineMrRealtimePreview | null>(null)
  const rawFiles = ref<OnlineMrRawFile[]>([])
  const rawTail = ref<OnlineMrRawTail | null>(null)
  const meshRawTail = ref<OnlineMrRawTail | null>(null)
  const fpingRawTail = ref<OnlineMrRawTail | null>(null)
  const otherRawTail = ref<OnlineMrRawTail | null>(null)
  const rawSource = ref('terminal_monitor')
  const loading = ref(false)
  const error = ref('')
  const failures = ref(0)
  let overviewTimer: number | null = null
  let rawTimer: number | null = null
  let overviewBusy = false
  let rawBusy = false
  let polling = false
  let rawExpanded = false

  const active = computed(() => Boolean(current.value && ACTIVE_STATES.includes(current.value.status.toUpperCase())))

  function clearRealtimeState(): void {
    current.value = null
    selected.value = null
    collectors.value = []
    preview.value = null
    rawFiles.value = []
    rawTail.value = null
    meshRawTail.value = null
    fpingRawTail.value = null
    otherRawTail.value = null
  }

  async function refreshOverview(): Promise<void> {
    if (overviewBusy) return
    overviewBusy = true
    loading.value = !current.value
    try {
      const activeSession = await getCurrentOnlineMrSession()
      if (!activeSession || !ACTIVE_STATES.includes(activeSession.status.toUpperCase())) {
        clearRealtimeState()
        recordSuccess()
        return
      }
      const sessionChanged = current.value?.session_id !== activeSession.session_id
      const [nextCollectors, nextPreview, nextRawFiles] = await Promise.all([
        listOnlineMrCollectors(activeSession.session_id),
        getOnlineMrPreview(activeSession.session_id),
        listOnlineMrRawFiles(activeSession.session_id),
      ])
      current.value = activeSession
      selected.value = activeSession
      collectors.value = nextCollectors
      preview.value = nextPreview
      rawFiles.value = nextRawFiles
      if (sessionChanged) {
        rawTail.value = null
        meshRawTail.value = null
        fpingRawTail.value = null
        otherRawTail.value = null
      }
      if (rawExpanded) await refreshRawTail()
      recordSuccess()
    } catch (cause) {
      recordFailure(cause)
    } finally {
      overviewBusy = false
      loading.value = false
    }
  }

  async function refreshActive(): Promise<void> {
    await refreshOverview()
  }

  async function refreshRawTail(): Promise<void> {
    if (!rawExpanded || !current.value || rawBusy) return
    rawBusy = true
    try {
      const sessionId = current.value.session_id
      const sources = [
        ['mesh_link', (value: OnlineMrRawTail) => { meshRawTail.value = value }] as const,
        ['fping_raw', (value: OnlineMrRawTail) => { fpingRawTail.value = value }] as const,
      ]
      const otherSource = rawSource.value && !['mesh_link', 'fping_raw'].includes(rawSource.value) ? rawSource.value : ''
      const tasks = sources.map(([name, assign]) => getOnlineMrRawTail(sessionId, name).then(assign))
      if (otherSource) {
        tasks.push(
          getOnlineMrRawTail(sessionId, otherSource).then((value) => {
            otherRawTail.value = value
            rawTail.value = value
          }),
        )
      }
      const results = await Promise.allSettled(tasks)
      const rejected = results.find((item): item is PromiseRejectedResult => item.status === 'rejected')
      if (results.some((item) => item.status === 'fulfilled')) recordSuccess()
      else recordFailure(rejected?.reason)
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
      rawTimer = window.setInterval(() => void refreshRawTail(), 3000)
    }
  }

  function startPolling(): void {
    if (polling) return
    polling = true
    void refreshOverview()
    overviewTimer = window.setInterval(() => void refreshOverview(), 5000)
    if (rawExpanded) setRawExpanded(true)
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [overviewTimer, rawTimer]) {
      if (timer !== null) window.clearInterval(timer)
    }
    overviewTimer = rawTimer = null
  }

  function recordSuccess(): void {
    failures.value = 0
    error.value = ''
  }

  function recordFailure(_cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) error.value = '状态刷新失败，请检查主程序服务或当前采集任务。'
  }

  return {
    current,
    selected,
    collectors,
    preview,
    rawFiles,
    rawTail,
    meshRawTail,
    fpingRawTail,
    otherRawTail,
    rawSource,
    loading,
    error,
    failures,
    active,
    refreshOverview,
    refreshActive,
    refreshRawTail,
    setRawSource,
    setRawExpanded,
    startPolling,
    stopPolling,
  }
})
