import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { cancelTask, getTask, getTaskLogs, listTasks } from '../api/tasks'
import { resolveWebSocketUrl } from '../platform/runtime'
import type { TaskItem, TaskLogLine } from '../types/task'
import { activeTaskStatuses } from '../utils/taskStatus'

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<TaskItem[]>([])
  const selected = ref<TaskItem | null>(null)
  const logs = ref<TaskLogLine[]>([])
  const loading = ref(false)
  const error = ref('')
  const detailError = ref('')
  const logError = ref('')
  const failures = ref(0)
  const logsExpanded = ref(false)
  const pollingConsumers = new Set<string>()
  let detailVisible = false
  let listBusy = false
  let detailBusy = false
  let logBusy = false
  let listTimer: number | null = null
  let detailTimer: number | null = null
  let logTimer: number | null = null
  let socket: WebSocket | null = null
  let socketReconnectTimer: number | null = null
  let socketReconnectEnabled = false

  const runningCount = computed(() => tasks.value.filter((task) => activeTaskStatuses.includes(task.status)).length)
  const failedCount = computed(() => tasks.value.filter((task) => task.status === 'FAILED').length)
  const completedCount = computed(() => tasks.value.filter((task) => task.status === 'COMPLETED').length)
  const warningCount = computed(() => tasks.value.filter((task) => task.has_warning).length)

  async function refresh(): Promise<void> {
    if (listBusy) return
    listBusy = true
    loading.value = !tasks.value.length
    try {
      tasks.value = await listTasks()
      if (selected.value) selected.value = tasks.value.find((task) => task.id === selected.value?.id) || selected.value
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
    if (!detailVisible || !logsExpanded.value || !selected.value || logBusy) return
    logBusy = true
    try {
      const payload = await getTaskLogs(selected.value.id, 300)
      logs.value = payload.lines
      logError.value = ''
    } catch (cause) {
      logError.value = cause instanceof Error ? cause.message : '任务日志读取失败'
    } finally {
      logBusy = false
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

  function setDetailVisible(value: boolean): void {
    detailVisible = value
    if (!value) setLogsExpanded(false)
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
          payload?: { tasks?: TaskItem[] }
        }
        if (event.type === 'snapshot' && Array.isArray(event.payload?.tasks)) {
          tasks.value = event.payload.tasks
          failures.value = 0
          error.value = ''
          return
        }
        if (event.type !== 'heartbeat') void refresh()
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
    socket?.close()
    socket = null
  }

  function scheduleListRefresh(): void {
    if (!pollingConsumers.size) return
    const delay = failures.value >= 3 ? 10_000 : runningCount.value ? 2_000 : 5_000
    listTimer = window.setTimeout(async () => {
      await refresh()
      scheduleListRefresh()
    }, delay)
  }

  return {
    tasks,
    selected,
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
    refresh,
    selectTask,
    refreshSelected,
    refreshLogs,
    manualRefresh,
    requestCancel,
    setDetailVisible,
    setLogsExpanded,
    acquirePolling,
    releasePolling,
  }
})
