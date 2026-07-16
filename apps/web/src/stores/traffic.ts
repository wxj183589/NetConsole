import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  cancelTrafficRun,
  getTrafficRun,
  getTrafficSummary,
  listTrafficEvents,
  listTrafficExecutionTargets,
  listTrafficPingSamples,
  listTrafficRuns,
  retryTrafficRun,
  startFping,
  startIperfClient,
  startIperfServer,
} from '../api/traffic'
import { startTcpPortTest } from '../api/networkTools'
import type { TcpPortTestRequest } from '../types/networkTools'
import type {
  FpingRequest,
  IperfClientRequest,
  IperfServerRequest,
  TrafficEvent,
  TrafficExecutionTarget,
  TrafficPingSample,
  TrafficRun,
  TrafficSocketMessage,
} from '../types/traffic'
import { activeTaskStatuses } from '../utils/taskStatus'
import { resolveWebSocketUrl } from '../platform/runtime'

const EVENT_LIMIT = 800
const SAMPLE_LIMIT = 2000

export const useTrafficStore = defineStore('traffic', () => {
  const targets = ref<TrafficExecutionTarget[]>([])
  const runs = ref<TrafficRun[]>([])
  const selected = ref<TrafficRun | null>(null)
  const summary = ref<Record<string, unknown>>({})
  const events = ref<TrafficEvent[]>([])
  const samples = ref<TrafficPingSample[]>([])
  const loading = ref(false)
  const starting = ref(false)
  const error = ref('')
  const socketConnected = ref(false)
  let socket: WebSocket | null = null
  let socketRunId = ''
  let reconnectTimer: number | null = null
  let reconnectEnabled = true

  const runningCount = computed(() => runs.value.filter((run) => activeTaskStatuses.includes(run.status)).length)
  const failedCount = computed(() => runs.value.filter((run) => run.status === 'FAILED').length)
  const completedCount = computed(() => runs.value.filter((run) => run.status === 'COMPLETED').length)

  async function refreshTargets(): Promise<void> {
    targets.value = await listTrafficExecutionTargets()
  }

  async function refreshRuns(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      runs.value = await listTrafficRuns()
      if (selected.value) selected.value = runs.value.find((run) => run.traffic_run_id === selected.value?.traffic_run_id) || selected.value
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '流量任务加载失败'
    } finally {
      loading.value = false
    }
  }

  async function selectRun(id: string): Promise<void> {
    await loadRun(id)
    connectSocket(id)
  }

  async function loadRun(id: string): Promise<void> {
    selected.value = await getTrafficRun(id)
    summary.value = (await getTrafficSummary(id)).summary
    events.value = await listTrafficEvents(id)
    samples.value = await listTrafficPingSamples(id)
  }

  async function createIperfServer(value: IperfServerRequest): Promise<TrafficRun> {
    return createRun(() => startIperfServer(value))
  }

  async function createIperfClient(value: IperfClientRequest): Promise<TrafficRun> {
    return createRun(() => startIperfClient(value))
  }

  async function createFping(value: FpingRequest): Promise<TrafficRun> {
    return createRun(() => startFping(value))
  }

  async function createTcpPortTest(value: TcpPortTestRequest): Promise<TrafficRun> {
    return createRun(() => startTcpPortTest(value))
  }

  async function requestCancel(id: string): Promise<void> {
    await cancelTrafficRun(id)
    await refreshRuns()
    if (selected.value?.traffic_run_id === id) await selectRun(id)
  }

  async function requestRetry(id: string): Promise<TrafficRun> {
    const response = await retryTrafficRun(id)
    upsertRun(response.run)
    await selectRun(response.run.traffic_run_id)
    return response.run
  }

  function connectSocket(id: string): void {
    if (socket && socketRunId === id && socket.readyState <= WebSocket.OPEN) return
    disconnectSocket()
    reconnectEnabled = true
    socketRunId = id
    const afterEvent = events.value.at(-1)?.sequence || 0
    const afterSample = samples.value.at(-1)?.sequence || 0
    socket = new WebSocket(
      resolveWebSocketUrl(`/ws/traffic/${encodeURIComponent(id)}?after_event=${afterEvent}&after_sample=${afterSample}`),
    )
    socket.onopen = () => {
      socketConnected.value = true
    }
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as TrafficSocketMessage
      if (event.type === 'event') {
        applyEvents([event.event])
      } else if (event.type === 'events') {
        applyEvents(event.events)
      } else if (event.type === 'samples') {
        mergeSamples(event.samples)
      }
    }
    socket.onclose = () => {
      socketConnected.value = false
      socket = null
      const runId = socketRunId
      if (reconnectEnabled && runId) reconnectTimer = window.setTimeout(() => void reconnectSocket(runId), 2000)
    }
    socket.onerror = () => socket?.close()
  }

  async function reconnectSocket(id: string): Promise<void> {
    if (!reconnectEnabled || socketRunId !== id) return
    try {
      await loadRun(id)
    } catch {
      // REST 仍是事实来源；短暂失败后由下一次 WebSocket 重连继续恢复。
    }
    if (reconnectEnabled && socketRunId === id) connectSocket(id)
  }

  function disconnectSocket(): void {
    reconnectEnabled = false
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
    socket?.close()
    socket = null
    socketConnected.value = false
  }

  async function createRun(starter: () => Promise<{ run: TrafficRun }>): Promise<TrafficRun> {
    starting.value = true
    error.value = ''
    try {
      const response = await starter()
      upsertRun(response.run)
      await selectRun(response.run.traffic_run_id)
      return response.run
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '流量任务启动失败'
      throw cause
    } finally {
      starting.value = false
      void refreshRuns()
    }
  }

  function upsertRun(run: TrafficRun): void {
    const index = runs.value.findIndex((item) => item.traffic_run_id === run.traffic_run_id)
    if (index >= 0) runs.value[index] = run
    else runs.value.unshift(run)
    if (selected.value?.traffic_run_id === run.traffic_run_id) selected.value = run
  }

  function mergeEvents(items: TrafficEvent[]): void {
    if (!items.length) return
    const seen = new Set(events.value.map((event) => event.sequence))
    events.value = [...events.value, ...items.filter((event) => !seen.has(event.sequence))]
      .sort((left, right) => left.sequence - right.sequence)
      .slice(-EVENT_LIMIT)
  }

  function applyEvents(items: TrafficEvent[]): void {
    mergeEvents(items)
    for (const event of items) {
      if (event.type === 'summary') summary.value = { ...summary.value, ...event.payload }
      if (event.type === 'state' && selected.value && typeof event.payload.state === 'string') {
        selected.value = { ...selected.value, status: event.payload.state as TrafficRun['status'], updated_at: event.timestamp }
        upsertRun(selected.value)
      }
      if (event.type === 'error' && selected.value) {
        selected.value = {
          ...selected.value,
          error_code: String(event.payload.code || ''),
          error_message: String(event.payload.message || event.payload.error || ''),
          updated_at: event.timestamp,
        }
        upsertRun(selected.value)
      }
    }
  }

  function mergeSamples(items: TrafficPingSample[]): void {
    if (!items.length) return
    const seen = new Set(samples.value.map((sample) => sample.sequence))
    samples.value = [...samples.value, ...items.filter((sample) => !seen.has(sample.sequence))]
      .sort((left, right) => left.sequence - right.sequence)
      .slice(-SAMPLE_LIMIT)
  }

  return {
    targets,
    runs,
    selected,
    summary,
    events,
    samples,
    loading,
    starting,
    error,
    socketConnected,
    runningCount,
    failedCount,
    completedCount,
    refreshTargets,
    refreshRuns,
    selectRun,
    createIperfServer,
    createIperfClient,
    createFping,
    createTcpPortTest,
    requestCancel,
    requestRetry,
    connectSocket,
    disconnectSocket,
  }
})
