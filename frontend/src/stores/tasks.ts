import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { cancelTask, getTask, listTaskEvents, listTasks } from '../api/tasks'
import type { TaskEvent, TaskItem, TaskSocketEvent } from '../types/task'
import { activeTaskStatuses } from '../utils/taskStatus'

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref<TaskItem[]>([])
  const selected = ref<TaskItem | null>(null)
  const events = ref<TaskEvent[]>([])
  const loading = ref(false)
  const error = ref('')
  const socketConnected = ref(false)
  let socket: WebSocket | null = null
  let reconnectTimer: number | null = null
  let reconnectEnabled = true

  const runningCount = computed(() => tasks.value.filter((task) => activeTaskStatuses.includes(task.status)).length)
  const failedCount = computed(() => tasks.value.filter((task) => task.status === 'FAILED').length)
  const completedCount = computed(() => tasks.value.filter((task) => task.status === 'COMPLETED').length)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      tasks.value = await listTasks()
      if (selected.value) {
        selected.value = tasks.value.find((task) => task.id === selected.value?.id) || selected.value
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '任务加载失败'
    } finally {
      loading.value = false
    }
  }

  async function selectTask(id: string): Promise<void> {
    selected.value = await getTask(id)
    events.value = await listTaskEvents(id)
  }

  async function requestCancel(id: string): Promise<void> {
    await cancelTask(id)
    await refresh()
    if (selected.value?.id === id) await selectTask(id)
  }

  function connectSocket(): void {
    if (socket && socket.readyState <= WebSocket.OPEN) return
    reconnectEnabled = true
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${scheme}://${window.location.host}/ws/tasks`)
    socket.onopen = () => {
      socketConnected.value = true
    }
    socket.onmessage = (message) => {
      const event = JSON.parse(message.data) as TaskSocketEvent
      if (event.type === 'snapshot' && event.payload?.tasks) {
        tasks.value = event.payload.tasks
        return
      }
      if (event.type !== 'heartbeat') void refresh()
      if (selected.value && event.task_id === selected.value.id) void selectTask(selected.value.id)
    }
    socket.onclose = () => {
      socketConnected.value = false
      socket = null
      if (reconnectEnabled) reconnectTimer = window.setTimeout(connectSocket, 2000)
    }
    socket.onerror = () => socket?.close()
  }

  function disconnectSocket(): void {
    reconnectEnabled = false
    if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
    reconnectTimer = null
    socket?.close()
    socket = null
  }

  return {
    tasks,
    selected,
    events,
    loading,
    error,
    socketConnected,
    runningCount,
    failedCount,
    completedCount,
    refresh,
    selectTask,
    requestCancel,
    connectSocket,
    disconnectSocket,
  }
})
