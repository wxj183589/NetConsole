import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  acknowledgeAllTaskAlerts,
  acknowledgeTask,
  cancelTask,
  cleanupTasks,
  dismissTask,
  getTask,
  getTaskLogs,
  listTasks,
} from '../api/tasks'
import { resolveWebSocketUrl } from '../platform/runtime'
import type {
  TaskCleanupResult,
  TaskCleanupType,
  TaskItem,
  TaskLogLine,
} from '../types/task'
import { activeTaskStatuses } from '../utils/taskStatus'

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<TaskItem[]>([])
  const selectedDetail = ref<TaskItem | null>(null)
  const selected = selectedDetail
  const logs = ref<TaskLogLine[]>([])
  const loading = ref(false)
  const error = ref('')
  const detailError = ref('')
  const logError = ref('')
  const failures = ref(0)
  const logsExpanded = ref(true)
  const pollingConsumers = new Set<string>()
  let detailVisible = false
  let listBusy = false
  let detailBusy = false
  let logContextGeneration = 0
  let activeLogRequest: { generation: number; taskId: string } | null = null
  let listTimer: number | null = null
  let detailTimer: number | null = null
  let logTimer: number | null = null
  let socket: WebSocket | null = null
  let socketReconnectTimer: number | null = null
  let socketRefreshTimer: number | null = null
  let socketReconnectEnabled = false

  const runningCount = computed(() => tasks.value.filter((task) => activeTaskStatuses.includes(task.status)).length)
  const activeTasks = computed(() => tasks.value.filter((task) => activeTaskStatuses.includes(task.status)))
  const failedCount = computed(() => tasks.value.filter((task) => task.status === 'FAILED').length)
  const completedCount = computed(() => tasks.value.filter((task) => task.status === 'COMPLETED').length)
  const warningCount = computed(() => tasks.value.filter((task) => task.has_warning).length)
  const unacknowledgedFailedTasks = computed(() => (
    tasks.value.filter((task) => task.status === 'FAILED' && !task.acknowledged_at)
  ))
  const unacknowledgedWarningTasks = computed(() => (
    tasks.value.filter((task) => task.has_warning && !task.acknowledged_at)
  ))

  async function refresh(): Promise<void> {
    if (listBusy) return
    listBusy = true
    loading.value = !tasks.value.length
    try {
      tasks.value = await listTasks()
      failures.value = 0
      error.value = ''
    } catch (_cause) {
      failures.value += 1
      if (failures.value >= 3) error.value = '任务中心刷新失败，请检查主程序服务。已降低刷新频率。'
    } finally {
      loading.value = false
      listBusy = false
    }
  }

  async function selectTask(id: string): Promise<void> {
    selected.value = await getTask(id)
    detailVisible = true
    detailError.value = ''
    logs.value = []
    logError.value = ''
    logContextGeneration += 1
    activeLogRequest = null
    setLogsExpanded(true)
  }

  async function refreshSelected(): Promise<void> {
    if (!detailVisible || !selected.value || detailBusy) return
    detailBusy = true
    try {
      selected.value = await getTask(selected.value.id)
      detailError.value = ''
    } catch (cause) {
      detailError.value = cause instanceof Error ? cause.message : '任务详情刷新失败'
    } finally {
      detailBusy = false
    }
  }

  async function refreshLogs(): Promise<void> {
    if (!detailVisible || !logsExpanded.value || !selected.value) return
    const generation = logContextGeneration
    const taskId = selected.value.id
    if (activeLogRequest?.generation === generation && activeLogRequest.taskId === taskId) return
    const request = { generation, taskId }
    activeLogRequest = request
    try {
      const payload = await getTaskLogs(taskId, 300)
      if (
        generation !== logContextGeneration
        || selected.value?.id !== taskId
        || !detailVisible
        || !logsExpanded.value
      ) return
      logs.value = payload.lines
      logError.value = ''
    } catch (cause) {
      if (generation !== logContextGeneration || selected.value?.id !== taskId) return
      logError.value = cause instanceof Error ? cause.message : '任务日志读取失败'
    } finally {
      if (activeLogRequest === request) activeLogRequest = null
    }
  }

  async function manualRefresh(): Promise<void> {
    await refresh()
    await refreshSelected()
    await refreshLogs()
  }

  async function requestCancel(): Promise<void> {
    if (!selected.value?.cancellable) return
    try {
      const updated = await cancelTask(selected.value.id)
      detailError.value = ''
      await refresh()
      selected.value = updated
    } catch (cause) {
      detailError.value = cause instanceof Error ? cause.message : '停止任务失败'
      throw cause
    }
  }

  async function requestCancelTask(id: string): Promise<void> {
    const task = tasks.value.find((item) => item.id === id)
    if (!task?.cancellable) return
    try {
      const updated = await cancelTask(id)
      const index = tasks.value.findIndex((item) => item.id === id)
      if (index >= 0) tasks.value[index] = updated
      if (selected.value?.id === id) selected.value = updated
      detailError.value = ''
      await refresh()
    } catch (cause) {
      detailError.value = cause instanceof Error ? cause.message : '停止任务失败'
      throw cause
    }
  }

  async function previewCleanup(cleanupType: TaskCleanupType): Promise<TaskCleanupResult> {
    return cleanupTasks(cleanupType, { dryRun: true })
  }

  async function cleanupHistory(cleanupType: TaskCleanupType): Promise<TaskCleanupResult> {
    const result = await cleanupTasks(cleanupType)
    applyDismissed(result.task_ids)
    return result
  }

  async function dismissHistoryTask(id: string): Promise<TaskCleanupResult> {
    const result = await dismissTask(id)
    applyDismissed(result.task_ids)
    return result
  }

  async function acknowledgeHistoryTask(id: string): Promise<void> {
    const result = await acknowledgeTask(id)
    applyAcknowledged(result.task_ids, result.acknowledged_at)
  }

  async function acknowledgeAllAlerts(): Promise<number> {
    const result = await acknowledgeAllTaskAlerts()
    applyAcknowledged(result.task_ids, result.acknowledged_at)
    return result.acknowledged
  }

  function setDetailVisible(value: boolean): void {
    detailVisible = value
    if (!value) {
      logContextGeneration += 1
      activeLogRequest = null
      setLogsExpanded(false)
    }
  }

  function setLogsExpanded(value: boolean): void {
    logsExpanded.value = value
    if (logTimer !== null) window.clearInterval(logTimer)
    logTimer = null
    if (value && pollingConsumers.size && detailVisible) {
      void refreshLogs()
      logTimer = window.setInterval(() => void refreshLogs(), 1000)
    }
  }

  function acquirePolling(consumer: string): void {
    const key = consumer.trim()
    if (!key || pollingConsumers.has(key)) return
    pollingConsumers.add(key)
    if (pollingConsumers.size !== 1) return
    connectSocket()
    void refresh().finally(scheduleListRefresh)
    detailTimer = window.setInterval(() => void refreshSelected(), 2000)
    if (logsExpanded.value) setLogsExpanded(true)
  }

  function releasePolling(consumer: string): void {
    pollingConsumers.delete(consumer.trim())
    if (pollingConsumers.size) return
    for (const timer of [listTimer, detailTimer, logTimer]) {
      if (timer !== null) {
        window.clearTimeout(timer)
        window.clearInterval(timer)
      }
    }
    listTimer = detailTimer = logTimer = null
    disconnectSocket()
  }

  function connectSocket(): void {
    if (typeof WebSocket === 'undefined' || !window.location) return
    if (socket && socket.readyState <= WebSocket.OPEN) return
    socketReconnectEnabled = true
    socket = new WebSocket(resolveWebSocketUrl('/ws/tasks'))
    socket.onopen = () => { void refresh() }
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(String(message.data)) as {
          type?: string
          payload?: {
            tasks?: TaskItem[]
            task_ids?: string[]
            acknowledged_at?: string
          }
        }
        if (event.type === 'snapshot') {
          scheduleSocketRefresh(true)
          return
        }
        if (event.type === 'tasks.dismissed') {
          applyDismissed(event.payload?.task_ids || [])
          return
        }
        if (event.type === 'tasks.acknowledged') {
          applyAcknowledged(
            event.payload?.task_ids || [],
            event.payload?.acknowledged_at || '',
          )
          return
        }
        if (event.type !== 'heartbeat') scheduleSocketRefresh()
      } catch {
        // REST 仍是事实来源；损坏事件由下一个正常事件或轮询恢复。
      }
    }
    socket.onclose = () => {
      socket = null
      if (socketReconnectEnabled && pollingConsumers.size) {
        socketReconnectTimer = window.setTimeout(connectSocket, 2000)
      }
    }
    socket.onerror = () => socket?.close()
  }

  function disconnectSocket(): void {
    socketReconnectEnabled = false
    if (socketReconnectTimer !== null) window.clearTimeout(socketReconnectTimer)
    socketReconnectTimer = null
    if (socketRefreshTimer !== null) window.clearTimeout(socketRefreshTimer)
    socketRefreshTimer = null
    socket?.close()
    socket = null
  }

  function scheduleSocketRefresh(immediate = false): void {
    if (socketRefreshTimer !== null) return
    socketRefreshTimer = window.setTimeout(() => {
      socketRefreshTimer = null
      void refresh()
    }, immediate ? 0 : 300)
  }

  function scheduleListRefresh(): void {
    if (!pollingConsumers.size) return
    const delay = failures.value >= 3 ? 10_000 : runningCount.value ? 2_000 : 5_000
    listTimer = window.setTimeout(async () => {
      await refresh()
      scheduleListRefresh()
    }, delay)
  }

  function applyDismissed(taskIds: string[]): void {
    const dismissed = new Set(taskIds)
    if (!dismissed.size) return
    tasks.value = tasks.value.filter((task) => !dismissed.has(task.id))
    if (selected.value && dismissed.has(selected.value.id)) {
      selected.value = null
      logs.value = []
      detailVisible = false
      logContextGeneration += 1
      activeLogRequest = null
    }
  }

  function applyAcknowledged(taskIds: string[], acknowledgedAt: string): void {
    const acknowledged = new Set(taskIds)
    if (!acknowledged.size) return
    tasks.value = tasks.value.map((task) => (
      acknowledged.has(task.id)
        ? { ...task, acknowledged_at: acknowledgedAt || task.acknowledged_at || '' }
        : task
    ))
    if (selected.value && acknowledged.has(selected.value.id)) {
      selected.value = {
        ...selected.value,
        acknowledged_at: acknowledgedAt || selected.value.acknowledged_at || '',
      }
    }
  }

  return {
    tasks,
    selected,
    selectedDetail,
    logs,
    loading,
    error,
    detailError,
    logError,
    failures,
    logsExpanded,
    runningCount,
    failedCount,
    completedCount,
    warningCount,
    unacknowledgedFailedTasks,
    unacknowledgedWarningTasks,
    activeTasks,
    refresh,
    selectTask,
    refreshSelected,
    refreshLogs,
    manualRefresh,
    requestCancel,
    requestCancelTask,
    previewCleanup,
    cleanupHistory,
    dismissHistoryTask,
    acknowledgeHistoryTask,
    acknowledgeAllAlerts,
    setDetailVisible,
    setLogsExpanded,
    acquirePolling,
    releasePolling,
  }
})
