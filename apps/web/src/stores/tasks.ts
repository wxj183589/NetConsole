import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getTask, getTaskLogs, listTasks } from '../api/tasks'
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
  let polling = false
  let detailVisible = false
  let listBusy = false
  let detailBusy = false
  let logBusy = false
  let listTimer: number | null = null
  let detailTimer: number | null = null
  let logTimer: number | null = null

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

  function setDetailVisible(value: boolean): void {
    detailVisible = value
    if (!value) setLogsExpanded(false)
  }

  function setLogsExpanded(value: boolean): void {
    logsExpanded.value = value
    if (logTimer !== null) window.clearInterval(logTimer)
    logTimer = null
    if (value && polling && detailVisible) {
      void refreshLogs()
      logTimer = window.setInterval(() => void refreshLogs(), 1000)
    }
  }

  function startPolling(): void {
    if (polling) return
    polling = true
    void refresh().finally(scheduleListRefresh)
    detailTimer = window.setInterval(() => void refreshSelected(), 2000)
    if (logsExpanded.value) setLogsExpanded(true)
  }

  function stopPolling(): void {
    polling = false
    for (const timer of [listTimer, detailTimer, logTimer]) {
      if (timer !== null) {
        window.clearTimeout(timer)
        window.clearInterval(timer)
      }
    }
    listTimer = detailTimer = logTimer = null
  }

  function scheduleListRefresh(): void {
    if (!polling) return
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
    setDetailVisible,
    setLogsExpanded,
    startPolling,
    stopPolling,
  }
})
