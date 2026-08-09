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
  const selectedControlMrId = ref('')
  const selectedControlMrSource = ref<'manual' | 'session' | 'route' | 'fallback' | ''>('')
  const loading = ref(false)
  const connectionError = ref('')
  const overviewErrors = ref<Record<string, string>>({})
  const rawErrors = ref<Record<string, string>>({})
  const failures = ref(0)
  let overviewTimer: number | null = null
  let rawTimer: number | null = null
  let overviewBusy = false
  let rawBusy = false
  let polling = false
  let rawExpanded = false
  let missingSessionConfirmations = 0
  const MAX_TRANSIENT_MISSING_CONFIRMATIONS = 3

  const active = computed(() => Boolean(current.value && ACTIVE_STATES.includes(current.value.status.toUpperCase())))
  const error = computed(() => {
    const unavailable = [
      ...Object.keys(overviewErrors.value),
      ...Object.keys(rawErrors.value),
    ]
    if (unavailable.length) {
      return `部分实时数据刷新失败，已保留最后成功数据。失败项目：${unavailable.join('、')}`
    }
    return connectionError.value
  })

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
      if (!activeSession) {
        if (current.value && ACTIVE_STATES.includes(current.value.status.toUpperCase())) {
          missingSessionConfirmations += 1
          connectionError.value = missingSessionConfirmations >= MAX_TRANSIENT_MISSING_CONFIRMATIONS
            ? '当前实时 Session 已结束或不可用。'
            : '当前实时状态刷新中，已保留最后一次有效 Session。'
          if (missingSessionConfirmations < MAX_TRANSIENT_MISSING_CONFIRMATIONS) return
        }
        clearRealtimeState()
        overviewErrors.value = {}
        rawErrors.value = {}
        recordSuccess()
        return
      }
      missingSessionConfirmations = 0
      if (!ACTIVE_STATES.includes(activeSession.status.toUpperCase())) {
        clearRealtimeState()
        overviewErrors.value = {}
        rawErrors.value = {}
        recordSuccess()
        return
      }
      const sessionChanged = current.value?.session_id !== activeSession.session_id
      current.value = activeSession
      selected.value = activeSession
      if (sessionChanged) {
        collectors.value = []
        preview.value = null
        rawFiles.value = []
        rawTail.value = null
        meshRawTail.value = null
        fpingRawTail.value = null
        otherRawTail.value = null
        overviewErrors.value = {}
        rawErrors.value = {}
      }
      recordSuccess()
      const [collectorsResult, previewResult, rawFilesResult] = await Promise.allSettled([
        listOnlineMrCollectors(activeSession.session_id),
        getOnlineMrPreview(activeSession.session_id),
        listOnlineMrRawFiles(activeSession.session_id),
      ] as const)
      applySettledResult(collectorsResult, '采集器状态', (value) => { collectors.value = value }, overviewErrors)
      applySettledResult(previewResult, '实时预览', (value) => { preview.value = value }, overviewErrors)
      applySettledResult(rawFilesResult, '原始文件', (value) => { rawFiles.value = value }, overviewErrors)
      if (rawExpanded) await refreshRawTail()
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
      const sources: Array<{
        name: string
        label: string
        assign: (value: OnlineMrRawTail) => void
      }> = [
        { name: 'mesh_link', label: 'Mesh 原始输出', assign: (value) => { meshRawTail.value = value } },
        { name: 'fping_raw', label: 'fping 原始输出', assign: (value) => { fpingRawTail.value = value } },
      ]
      const otherSource = rawSource.value && !['mesh_link', 'fping_raw'].includes(rawSource.value) ? rawSource.value : ''
      if (otherSource) {
        sources.push({
          name: otherSource,
          label: '当前原始输出',
          assign: (value) => {
            otherRawTail.value = value
            rawTail.value = value
          },
        })
      }
      const results = await Promise.allSettled(
        sources.map((source) => getOnlineMrRawTail(sessionId, source.name)),
      )
      results.forEach((result, index) => {
        const source = sources[index]
        if (source) applySettledResult(result, source.label, source.assign, rawErrors)
      })
    } catch (cause) {
      rawErrors.value = { ...rawErrors.value, '原始输出': errorMessage(cause) }
    } finally {
      rawBusy = false
    }
  }

  function setRawSource(name: string): void {
    rawSource.value = name
    rawTail.value = null
    if (rawExpanded) void refreshRawTail()
  }

  function setSelectedControlMrId(
    mrId: string,
    source: 'manual' | 'session' | 'route' | 'fallback' = 'manual',
  ): void {
    selectedControlMrId.value = String(mrId || '')
    selectedControlMrSource.value = selectedControlMrId.value ? source : ''
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
    connectionError.value = ''
  }

  function recordFailure(_cause: unknown): void {
    failures.value += 1
    if (failures.value >= 3) {
      connectionError.value = '状态刷新失败，请检查主程序服务或当前采集任务。'
    }
  }

  function errorMessage(cause: unknown): string {
    return cause instanceof Error && cause.message ? cause.message : '未知错误'
  }

  function applySettledResult<T>(
    result: PromiseSettledResult<T>,
    label: string,
    assign: (value: T) => void,
    errors: typeof overviewErrors,
  ): void {
    if (result.status === 'fulfilled') {
      assign(result.value)
      if (errors.value[label]) {
        const next = { ...errors.value }
        delete next[label]
        errors.value = next
      }
      return
    }
    errors.value = { ...errors.value, [label]: errorMessage(result.reason) }
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
    selectedControlMrId,
    selectedControlMrSource,
    loading,
    error,
    failures,
    active,
    refreshOverview,
    refreshActive,
    refreshRawTail,
    setRawSource,
    setSelectedControlMrId,
    setRawExpanded,
    startPolling,
    stopPolling,
  }
})
