<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { Check, Close, Delete, Loading, MoreFilled, Tickets, View } from '@element-plus/icons-vue'

import { ApiRequestError } from '../../api/client'
import { t } from '../../i18n/runtime'
import { useConfirm } from '../../components/feedback/useConfirm'
import { getPlatformAdapter } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import { useWorkspaceStore } from '../../stores/workspace'
import type { TaskCleanupResult, TaskCleanupType, TaskItem } from '../../types/task'
import { activeTaskStatuses, taskStatusLabel, taskStatusType } from '../../utils/taskStatus'
import { formatTaskDateTime, parseUtcDateTime, taskDateTimeTitle } from '../../utils/dateTime'
import {
  onTaskCenterOpenRequested,
  type TaskCenterOpenContext,
} from '../events'
import TaskDetailDrawer from './TaskDetailDrawer.vue'

const GLOBAL_POLLING_CONSUMER = 'global-task-center'
const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'ABORTED', 'STOPPED'])
const QUEUED_STATUSES = new Set(['CREATED', 'QUEUED', 'PENDING'])
const RUNNING_STATUSES = new Set(['STARTING', 'RUNNING', 'STOPPING'])
const BATCH_NOTIFICATION_TASK_TYPES = new Set(['device_connection_test', 'device_detail_collect'])
const TERMINAL_NOTIFICATION_BUFFER_MS = 800

type NotificationKind = 'success' | 'warning' | 'failure'

const store = useTaskStore()
const workspace = useWorkspaceStore()
const { confirm } = useConfirm()
const drawerVisible = ref(false)
const detailVisible = ref(false)
const detailTaskId = ref('')
const detailSource = ref<'notification' | 'global-list' | 'floating' | 'native'>('global-list')
const drawerFilter = ref<'all' | 'active' | 'attention' | 'completed' | 'running' | 'queued'>('all')
const focusedTaskId = ref('')
const floatingMinimized = ref(false)
const floatingDismissedSignature = ref('')
const cleanupBusy = ref(false)
const notificationStates = new Map<string, string>()
const pendingTerminalNotifications = new Map<string, TaskItem>()
let notificationsReady = false
let terminalNotificationTimer: number | null = null
let removeLocalOpenListener: (() => void) | undefined
let removeNativeOpenListener: (() => void) | undefined

const runningTasks = computed(() => (
  store.tasks.filter((task) => RUNNING_STATUSES.has(task.status))
))
const queuedTasks = computed(() => (
  store.tasks.filter((task) => QUEUED_STATUSES.has(task.status))
))
const failedTasks = computed(() => store.unacknowledgedFailedTasks)
const warningTasks = computed(() => store.unacknowledgedWarningTasks)
const attentionTasks = computed(() => {
  const ids = new Set<string>()
  return [...failedTasks.value, ...warningTasks.value].filter((task) => {
    if (ids.has(task.id)) return false
    ids.add(task.id)
    return true
  })
})
const activeTasks = computed(() => (
  store.tasks
    .filter((task) => activeTaskStatuses.includes(task.status))
    .sort(sortNewest)
))
const badgeCount = computed(() => activeTasks.value.length + attentionTasks.value.length)
const indicatorState = computed(() => (
  failedTasks.value.length
    ? 'failed'
    : warningTasks.value.length
      ? 'warning'
      : activeTasks.value.length
        ? 'active'
        : 'idle'
))
const drawerTasks = computed(() => {
  return [...store.tasks]
    .sort(sortDrawerTasks)
    .filter(matchesDrawerFilter)
    .slice(0, 12)
})
const drawerFilterOptions = computed(() => [
  { label: t('job_center.filter.all', '全部'), value: 'all' },
  { label: t('job_center.filter.active', '进行中'), value: 'active' },
  { label: t('job_center.filter.attention', '失败/告警'), value: 'attention' },
  { label: t('job_center.filter.completed', '已完成'), value: 'completed' },
])
const activeSignature = computed(() => activeTasks.value.map((task) => task.id).sort().join('|'))
const showFloatingCard = computed(() => (
  Boolean(activeSignature.value)
  && floatingDismissedSignature.value !== activeSignature.value
))
const primaryActiveTask = computed(() => activeTasks.value[0] ?? null)
const floatingTitle = computed(() => (
  activeTasks.value.length > 1
    ? `${activeTasks.value.length} 个任务正在运行`
    : primaryActiveTask.value?.name || '任务正在运行'
))
const floatingMessage = computed(() => (
  primaryActiveTask.value?.message
  || primaryActiveTask.value?.phase
  || taskStatusLabel(primaryActiveTask.value?.status || 'RUNNING')
))
const floatingProgress = computed(() => primaryActiveTask.value?.progress || 0)

watch(activeSignature, (signature) => {
  if (!signature) {
    floatingDismissedSignature.value = ''
    floatingMinimized.value = false
  }
})

watch(
  () => store.tasks.map((task) => ({
    id: task.id,
    status: task.status,
    updated: task.updated_time,
    warning: task.has_warning,
  })),
  () => handleTaskStateChanges(),
  { deep: true },
)

watch(
  [() => activeTasks.value.length, () => failedTasks.value.length, () => warningTasks.value.length],
  ([active, failed, warning]) => {
    getPlatformAdapter().setTaskTrayStatus({ active, failed, warning })
  },
  { immediate: true },
)

onMounted(async () => {
  removeLocalOpenListener = onTaskCenterOpenRequested(openRequestedTaskCenter)
  removeNativeOpenListener = getPlatformAdapter().onTaskCenterOpenRequested(openRequestedTaskCenter)
  await store.refresh()
  seedNotificationStates()
  notificationsReady = true
  store.acquirePolling(GLOBAL_POLLING_CONSUMER)
})

onBeforeUnmount(() => {
  notificationsReady = false
  if (terminalNotificationTimer !== null) window.clearTimeout(terminalNotificationTimer)
  terminalNotificationTimer = null
  pendingTerminalNotifications.clear()
  removeLocalOpenListener?.()
  removeNativeOpenListener?.()
  store.releasePolling(GLOBAL_POLLING_CONSUMER)
})

function sortNewest(left: TaskItem, right: TaskItem): number {
  const rightTime = taskTimestamp(right)
  const leftTime = taskTimestamp(left)
  return rightTime - leftTime || right.id.localeCompare(left.id)
}

function taskTimestamp(task: TaskItem): number {
  return parseUtcDateTime(task.updated_time)?.getTime()
    ?? parseUtcDateTime(task.created_time)?.getTime()
    ?? Number.NEGATIVE_INFINITY
}

function sortDrawerTasks(left: TaskItem, right: TaskItem): number {
  const priority = (task: TaskItem): number => {
    if (task.id === focusedTaskId.value) return -1
    if (RUNNING_STATUSES.has(task.status)) return 0
    if (QUEUED_STATUSES.has(task.status)) return 1
    if (!task.acknowledged_at && (task.status === 'FAILED' || task.status === 'ABORTED')) return 2
    if (!task.acknowledged_at && task.has_warning) return 3
    return 4
  }
  return priority(left) - priority(right) || sortNewest(left, right)
}

function openRequestedTaskCenter(context: TaskCenterOpenContext = {}): void {
  if (context.taskId) {
    openTaskDetail(context.taskId, 'native')
    return
  }
  openTaskSummaryDrawer()
}

function openTaskSummaryDrawer(): void {
  detailVisible.value = false
  focusedTaskId.value = ''
  drawerVisible.value = true
  void store.refresh()
}

function openTaskDetail(
  taskId: string,
  source: 'notification' | 'global-list' | 'floating' | 'native' = 'global-list',
): void {
  const normalizedTaskId = taskId.trim()
  if (!normalizedTaskId) return
  drawerVisible.value = false
  focusedTaskId.value = normalizedTaskId
  detailTaskId.value = normalizedTaskId
  detailSource.value = source
  detailVisible.value = true
}

function handleDetailLoadError(_taskId: string, message: string): void {
  ElMessage.error(message)
}

function matchesDrawerFilter(task: TaskItem): boolean {
  if (drawerFilter.value === 'all') return true
  if (drawerFilter.value === 'active') return activeTaskStatuses.includes(task.status)
  if (drawerFilter.value === 'attention') {
    return !task.acknowledged_at && (task.status === 'FAILED' || task.status === 'ABORTED' || task.has_warning)
  }
  if (drawerFilter.value === 'completed') return TERMINAL_STATUSES.has(task.status)
  if (drawerFilter.value === 'running') return RUNNING_STATUSES.has(task.status)
  if (drawerFilter.value === 'queued') return QUEUED_STATUSES.has(task.status)
  return true
}

function dismissFloating(): void {
  floatingDismissedSignature.value = activeSignature.value
}

async function navigateToFullTaskCenter(): Promise<void> {
  drawerVisible.value = false
  await workspace.openOrActivateRoute('/tasks')
}

async function cancelTask(task: TaskItem): Promise<void> {
  try {
    await store.requestCancelTask(task.id)
    ElMessage.success('已请求停止任务')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '停止任务失败')
  }
}

async function cleanupHistory(cleanupType: TaskCleanupType): Promise<void> {
  if (cleanupBusy.value) return
  cleanupBusy.value = true
  let feedbackShown = false
  const showCleanupError = (cause: unknown): void => {
    if (feedbackShown) return
    feedbackShown = true
    ElMessage.error(cleanupErrorMessage(cause))
  }
  try {
    const preview = await store.previewCleanup(cleanupType)
    if (!preview.matched) {
      ElMessage.info(t('job_center.cleanup.empty', '当前没有可清理的已结束任务'))
      return
    }
    await confirm({
      type: 'DANGER',
      title: t('job_center.cleanup.dialog_title', '清理任务记录'),
      message: cleanupMessage(cleanupType, preview.matched),
      highlight: `${preview.matched} 个`,
      notice: cleanupNotice(preview),
      width: 'min(468px, calc(100vw - 32px))',
      confirmText: t('job_center.cleanup.confirm', '确认清理'),
      confirmLoadingText: t('job_center.cleanup.loading', '正在清理…'),
      cancelText: t('job_center.cleanup.cancel', '取消'),
      onConfirm: async () => {
        try {
          const result = await store.cleanupHistory(cleanupType)
          if (!result.dismissed) {
            ElMessage.info(t('job_center.cleanup.empty', '当前没有可清理的已结束任务'))
            return
          }
          ElMessage.success(t(
            'job_center.cleanup.done',
            '已清理 {count} 条已结束任务',
          ).replace('{count}', String(result.dismissed)))
        } catch (cause) {
          showCleanupError(cause)
        }
      },
    })
  } catch (cause) {
    showCleanupError(cause)
  } finally {
    cleanupBusy.value = false
  }
}

function cleanupErrorMessage(cause: unknown): string {
  if (cause instanceof ApiRequestError && cause.status === 409 && cause.message) {
    return cause.message
  }
  return cause instanceof Error && cause.message
    ? cause.message
    : t('job_center.cleanup.failed', '任务清理失败')
}

function cleanupMessage(cleanupType: TaskCleanupType, count: number): string {
  const labels: Record<TaskCleanupType, string> = {
    completed: t('job_center.cleanup.message_completed', '将从任务中心移除 {count} 个已完成任务。'),
    cancelled: t('job_center.cleanup.message_cancelled', '将从任务中心移除 {count} 个已取消任务。'),
    expired: t('job_center.cleanup.message_expired', '将从任务中心移除 {count} 个已过期任务。'),
    completed_and_expired: t('job_center.cleanup.message_completed_expired', '将从任务中心移除 {count} 个已完成或已过期任务。'),
    resolved_alerts: t('job_center.cleanup.message_resolved_alerts', '将从任务中心移除 {count} 个已处理的失败或警告任务。'),
    all_history: t('job_center.cleanup.message_all_history', '将从任务中心移除 {count} 个历史任务。'),
  }
  return labels[cleanupType].replace('{count}', String(count))
}

function cleanupNotice(preview: TaskCleanupResult): string {
  const retained = preview.skipped_unacknowledged
    ? t(
        'job_center.cleanup.retained_alerts',
        '{count} 个未处理的失败或警告任务将保留。',
      ).replace('{count}', String(preview.skipped_unacknowledged))
    : ''
  const safety = t(
    'job_center.cleanup.no_files',
    '不会影响运行中或等待中的任务，也不会删除日志、采集文件或导出结果。',
  )
  return [retained, safety].filter(Boolean).join(' ')
}

async function acknowledgeAllAlerts(): Promise<void> {
  try {
    const count = await store.acknowledgeAllAlerts()
    ElMessage.success(count ? `已将 ${count} 个失败或告警任务标记为已读` : '没有未读失败或告警任务')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : t('job_center.acknowledge.failed', '标记失败'))
  }
}

async function acknowledgeTask(task: TaskItem): Promise<void> {
  try {
    await store.acknowledgeHistoryTask(task.id)
    ElMessage.success(t('job_center.acknowledge.done', '任务已标记为已处理'))
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : t('job_center.acknowledge.failed', '标记失败'))
  }
}

async function dismissTask(task: TaskItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      t('job_center.cleanup.dismiss_single', '仅从任务中心移除此记录，不会删除日志、采集文件或导出结果。'),
      t('job_center.cleanup.dismiss', '从列表移除'),
      {
        confirmButtonText: t('job_center.cleanup.dismiss_confirm', '移除'),
        cancelButtonText: t('job_center.cleanup.cancel', '取消'),
        type: 'warning',
      },
    )
    await store.dismissHistoryTask(task.id)
    ElMessage.success(t('job_center.cleanup.dismissed', '任务记录已从列表移除'))
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '移除失败')
  }
}

function taskNeedsAcknowledgement(task: TaskItem): boolean {
  return !task.acknowledged_at && (
    task.status === 'FAILED'
    || task.status === 'ABORTED'
    || task.has_warning
  )
}

function taskCanDismiss(task: TaskItem): boolean {
  return TERMINAL_STATUSES.has(task.status) && !taskNeedsAcknowledgement(task)
}

function taskSummaryMessage(task: TaskItem): string {
  if (task.artifact_availability === 'MISSING') {
    return task.missing_reason || '输出文件已不存在，可能已在资源管理器中删除。'
  }
  if (task.artifact_availability === 'INVALID') {
    return task.missing_reason || '输出文件校验失败，当前不可下载。'
  }
  return task.error_summary || task.message || task.phase || '等待任务状态更新'
}

function handleTaskMenu(command: string, task: TaskItem): void {
  if (command === 'detail') openTaskDetail(task.id)
  else if (command === 'acknowledge') void acknowledgeTask(task)
  else if (command === 'dismiss') void dismissTask(task)
}

function seedNotificationStates(): void {
  notificationStates.clear()
  for (const task of store.tasks) notificationStates.set(task.id, notificationKey(task))
}

function handleTaskStateChanges(): void {
  if (!notificationsReady) return
  const currentIds = new Set(store.tasks.map((task) => task.id))
  for (const task of store.tasks) {
    const key = notificationKey(task)
    const previous = notificationStates.get(task.id)
    notificationStates.set(task.id, key)
    if (previous === key || !TERMINAL_STATUSES.has(task.status)) continue
    queueTerminalNotification(task)
  }
  for (const id of notificationStates.keys()) {
    if (!currentIds.has(id)) notificationStates.delete(id)
  }
}

function notificationKey(task: TaskItem): string {
  return `${task.status}:${task.has_warning ? 'warning' : 'normal'}`
}

function queueTerminalNotification(task: TaskItem): void {
  pendingTerminalNotifications.set(task.id, task)
  if (terminalNotificationTimer !== null) return
  terminalNotificationTimer = window.setTimeout(flushTerminalNotifications, TERMINAL_NOTIFICATION_BUFFER_MS)
}

function flushTerminalNotifications(): void {
  terminalNotificationTimer = null
  if (!notificationsReady) {
    pendingTerminalNotifications.clear()
    return
  }
  const currentTasks = new Map(store.tasks.map((task) => [task.id, task]))
  const pending = [...pendingTerminalNotifications.values()]
    .map((task) => currentTasks.get(task.id) || task)
    .filter((task) => TERMINAL_STATUSES.has(task.status))
  pendingTerminalNotifications.clear()

  const batches = new Map<string, TaskItem[]>()
  const individual: TaskItem[] = []
  for (const task of pending) {
    if (!BATCH_NOTIFICATION_TASK_TYPES.has(task.type)) {
      individual.push(task)
      continue
    }
    const batchKey = `${task.type}:${task.site_name || ''}`
    const batch = batches.get(batchKey) || []
    batch.push(task)
    batches.set(batchKey, batch)
  }
  for (const task of individual) notifyTaskTerminal(task)
  for (const batch of batches.values()) {
    if (batch.length > 1) notifyTaskBatchTerminal(batch)
    else notifyTaskTerminal(batch[0])
  }
}

function notifyTaskTerminal(task: TaskItem): void {
  const kind = taskNotificationKind(task)
  const title = terminalTitle(task, kind)
  const body = task.error_summary || task.message || taskStatusLabel(task.status)
  notifyTask(
    task.id,
    title,
    body,
    kind,
    () => openTaskDetail(task.id, 'notification'),
    undefined,
    task.status === 'CANCELLED' || task.status === 'STOPPED',
  )
}

function notifyTaskBatchTerminal(tasks: TaskItem[]): void {
  const representative = tasks[0]
  const kind = batchNotificationKind(tasks)
  const allCancelled = tasks.every((task) => task.status === 'CANCELLED' || task.status === 'STOPPED')
  const label = batchNotificationLabel(representative)
  const title = `${label} · 批量完成`
  const body = batchNotificationSummary(tasks)
  const eventId = `batch:${representative.type}:${representative.site_name || 'site'}:${tasks.length}:${tasks
    .map((task) => task.id)
    .sort()
    .join(',')}`
  notifyTask(representative.id, title, body, kind, openTaskSummaryDrawer, eventId, allCancelled)
}

function taskNotificationKind(task: TaskItem): NotificationKind {
  return task.status === 'FAILED' || task.status === 'ABORTED'
    ? 'failure'
    : task.has_warning
      ? 'warning'
      : 'success'
}

function batchNotificationKind(tasks: TaskItem[]): NotificationKind {
  return tasks.some((task) => task.status === 'FAILED' || task.status === 'ABORTED')
    ? 'failure'
    : tasks.some((task) => task.has_warning || task.status === 'CANCELLED' || task.status === 'STOPPED')
      ? 'warning'
      : 'success'
}

function batchNotificationLabel(task: TaskItem): string {
  return task.name.split(' · ')[0].trim() || task.type || '批量任务'
}

function batchNotificationSummary(tasks: TaskItem[]): string {
  const failed = tasks.filter((task) => task.status === 'FAILED' || task.status === 'ABORTED').length
  const warning = tasks.filter((task) => (
    !['FAILED', 'ABORTED'].includes(task.status)
    && (task.has_warning || task.status === 'CANCELLED' || task.status === 'STOPPED')
  )).length
  const success = tasks.length - failed - warning
  return `共 ${tasks.length} 个子任务：成功 ${success}，失败 ${failed}${warning ? `，告警/取消 ${warning}` : ''}`
}

function notifyTask(
  taskId: string,
  title: string,
  body: string,
  kind: NotificationKind,
  openDetails: () => void,
  eventIdOverride?: string,
  suppressNative = false,
): void {
  const foreground = document.visibilityState === 'visible' && document.hasFocus()

  if (foreground) {
    let notification: ReturnType<typeof ElNotification> | undefined
    const showDetail = () => {
      notification?.close()
      openDetails()
    }
    notification = ElNotification({
      title,
      message: h('div', { class: 'nc-task-notification__content' }, [
        h('p', { class: 'nc-task-notification__summary' }, body),
        h('button', {
          type: 'button',
          class: 'nc-task-notification__detail',
          'aria-label': `查看任务 ${title} 详情`,
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            showDetail()
          },
        }, '查看详情'),
      ]),
      type: kind === 'failure' ? 'error' : kind,
      duration: kind === 'success' ? 5000 : 0,
      position: 'top-right',
      customClass: 'nc-task-notification',
      appendTo: document.body,
    })
    return
  }
  if (suppressNative) return
  const runtime = getPlatformAdapter()
  if (runtime.hostType !== 'electron') return
  const eventId = (eventIdOverride || `${taskId}:${title}:${body}`)
    .replace(/[^A-Za-z0-9_.:-]/g, '_')
    .slice(0, 180)
  void runtime.showTaskNotification({
    eventId,
    taskId,
    title,
    body,
    kind,
  })
}

function terminalTitle(task: TaskItem, kind: 'success' | 'warning' | 'failure'): string {
  if (kind === 'failure') return `${task.name || '任务'}失败`
  if (kind === 'warning') return `${task.name || '任务'}部分完成`
  if (task.status === 'CANCELLED' || task.status === 'STOPPED') return `${task.name || '任务'}已取消`
  return `${task.name || '任务'}已完成`
}
</script>

<template>
  <div class="global-task-center">
    <el-tooltip content="任务中心" placement="bottom">
      <el-badge
        :value="badgeCount"
        :hidden="badgeCount === 0"
        :type="indicatorState === 'failed' ? 'danger' : indicatorState === 'warning' ? 'warning' : 'primary'"
        :max="99"
      >
        <button
          type="button"
          :class="['global-task-indicator', indicatorState]"
          :aria-label="`打开任务中心，运行中 ${activeTasks.length}，失败 ${failedTasks.length}`"
          data-testid="global-task-indicator"
          @click="openTaskSummaryDrawer"
        >
          <el-icon :class="{ spinning: indicatorState === 'active' }">
            <Loading v-if="indicatorState === 'active'" />
            <Tickets v-else />
          </el-icon>
        </button>
      </el-badge>
    </el-tooltip>

    <el-drawer
      v-model="drawerVisible"
      size="min(520px, 96vw)"
      class="task-center-drawer"
      data-testid="task-center-drawer"
    >
      <template #header>
        <div class="task-drawer-header">
          <strong>{{ t('job_center.title', '任务中心') }}</strong>
          <el-dropdown trigger="click" :disabled="cleanupBusy" @command="cleanupHistory">
            <el-button :icon="Delete" :loading="cleanupBusy" :disabled="cleanupBusy">
              {{ t('job_center.cleanup.label', '清理') }}
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="completed_and_expired">{{ t('job_center.cleanup.completed_and_expired', '清理已完成和已过期任务') }}</el-dropdown-item>
                <el-dropdown-item command="completed">{{ t('job_center.cleanup.completed', '清理已完成任务') }}</el-dropdown-item>
                <el-dropdown-item command="cancelled">{{ t('job_center.cleanup.cancelled', '清理已取消任务') }}</el-dropdown-item>
                <el-dropdown-item command="expired">{{ t('job_center.cleanup.expired', '清理已过期任务') }}</el-dropdown-item>
                <el-dropdown-item command="resolved_alerts" divided>{{ t('job_center.cleanup.resolved_alerts', '清理已处理的失败和告警') }}</el-dropdown-item>
                <el-dropdown-item command="all_history">{{ t('job_center.cleanup.all_history', '清理全部历史任务') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </template>
      <div class="task-drawer-summary">
        <button type="button" :class="{ selected: drawerFilter === 'running' }" @click="drawerFilter = 'running'"><strong>{{ runningTasks.length }}</strong> 正在运行</button>
        <button type="button" :class="{ selected: drawerFilter === 'queued' }" @click="drawerFilter = 'queued'"><strong>{{ queuedTasks.length }}</strong> 等待</button>
        <button type="button" :class="['danger', { selected: drawerFilter === 'attention' }]" @click="drawerFilter = 'attention'"><strong>{{ failedTasks.length }}</strong> 失败</button>
        <button type="button" :class="['warning', { selected: drawerFilter === 'attention' }]" @click="drawerFilter = 'attention'"><strong>{{ warningTasks.length }}</strong> 告警</button>
      </div>
      <div class="task-drawer-controls">
        <el-segmented v-model="drawerFilter" :options="drawerFilterOptions" />
        <el-button
          v-if="attentionTasks.length"
          link
          type="primary"
          :icon="Check"
          @click="acknowledgeAllAlerts"
        >{{ t('job_center.acknowledge.all', '全部标为已读') }}</el-button>
      </div>

      <el-alert
        v-if="store.error"
        :title="store.error"
        type="error"
        :closable="false"
        show-icon
      />

      <div v-if="drawerTasks.length" class="task-drawer-list">
        <article
          v-for="task in drawerTasks"
          :key="task.id"
          :class="['task-drawer-item', { focused: task.id === focusedTaskId }]"
        >
          <div class="task-item-heading">
            <span :class="['task-state-dot', taskStatusType(task.status)]"></span>
            <div>
              <strong>{{ task.name || task.type }}</strong>
              <small :title="taskDateTimeTitle(task.updated_time || task.created_time)">{{ taskStatusLabel(task.status) }} · {{ formatTaskDateTime(task.updated_time || task.created_time) }}</small>
            </div>
            <el-tag :type="task.has_warning ? 'warning' : taskStatusType(task.status)" size="small">
              {{ task.has_warning ? '部分完成' : taskStatusLabel(task.status) }}
            </el-tag>
            <el-dropdown trigger="click" @command="(command: string) => handleTaskMenu(command, task)">
              <el-tooltip :content="t('job_center.action.menu', '任务操作')" placement="top">
                <el-button text circle :icon="MoreFilled" :aria-label="t('job_center.action.menu', '任务操作')" />
              </el-tooltip>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="detail" :icon="View">{{ t('job_center.action.details', '查看详情') }}</el-dropdown-item>
                  <el-dropdown-item
                    v-if="taskNeedsAcknowledgement(task)"
                    command="acknowledge"
                    :icon="Check"
                  >{{ t('job_center.acknowledge.one', '标记为已处理') }}</el-dropdown-item>
                  <el-dropdown-item
                    command="dismiss"
                    :icon="Delete"
                    :disabled="!taskCanDismiss(task)"
                    divided
                  >{{ t('job_center.cleanup.dismiss', '从列表移除') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <el-progress
            v-if="activeTaskStatuses.includes(task.status)"
            :percentage="task.progress"
            :stroke-width="7"
            :show-text="true"
          />
          <p :class="{ error: task.status === 'FAILED' || task.status === 'ABORTED' }">
            {{ taskSummaryMessage(task) }}
          </p>
          <div class="task-item-actions">
            <el-button
              v-if="task.cancellable"
              link
              type="danger"
              @click="cancelTask(task)"
            >取消</el-button>
            <el-button
              link
              type="primary"
              :icon="View"
              :data-testid="`task-summary-detail-${task.id}`"
              @click="openTaskDetail(task.id)"
            >
              查看详情
            </el-button>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无任务记录" />

      <template #footer>
        <div class="task-drawer-footer">
          <el-button @click="store.manualRefresh">刷新</el-button>
          <el-button
            type="primary"
            data-testid="navigate-full-task-center"
            @click="navigateToFullTaskCenter"
          >进入完整任务中心</el-button>
        </div>
      </template>
    </el-drawer>

    <TaskDetailDrawer
      v-model="detailVisible"
      :task-id="detailTaskId"
      :source="detailSource"
      @load-error="handleDetailLoadError"
    />

    <aside
      v-if="showFloatingCard"
      :class="['active-task-floating', { minimized: floatingMinimized }]"
      data-testid="active-task-floating-card"
    >
      <template v-if="floatingMinimized">
        <button type="button" class="floating-capsule" @click="floatingMinimized = false">
          任务 {{ activeTasks.length }} · {{ floatingProgress }}%
        </button>
      </template>
      <template v-else>
        <div class="floating-heading">
          <div>
            <strong>{{ floatingTitle }}</strong>
            <span>{{ floatingMessage }}</span>
          </div>
          <el-button text circle :icon="Close" aria-label="关闭任务进度提示" @click="dismissFloating" />
        </div>
        <el-progress :percentage="floatingProgress" :stroke-width="8" />
        <div class="floating-actions">
          <el-button link @click="floatingMinimized = true">后台运行</el-button>
          <el-button
            link
            type="primary"
            data-testid="floating-task-detail"
            @click="primaryActiveTask && openTaskDetail(primaryActiveTask.id, 'floating')"
          >查看详情</el-button>
          <el-button
            v-if="primaryActiveTask?.cancellable"
            link
            type="danger"
            @click="cancelTask(primaryActiveTask)"
          >取消</el-button>
        </div>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.global-task-center { flex: 0 0 auto; }
.global-task-indicator { display: grid; width: 34px; height: 34px; padding: 0; place-items: center; border: 1px solid var(--nc-border-light); border-radius: 9px; background: var(--nc-bg-card); color: var(--nc-text-secondary); cursor: pointer; }
.global-task-indicator:hover { border-color: var(--nc-primary); color: var(--nc-primary); }
.global-task-indicator.active { border-color: color-mix(in srgb, var(--nc-primary) 38%, var(--nc-border-light)); color: var(--nc-primary); }
.global-task-indicator.warning { color: var(--nc-warning); }
.global-task-indicator.failed { color: var(--nc-danger); }
.global-task-indicator .el-icon { font-size: 18px; }
.spinning { animation: task-spin 1.2s linear infinite; }
.task-drawer-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 16px; }
.task-drawer-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; }
.task-drawer-header strong { font-size: 16px; }
.task-drawer-summary button { display: grid; gap: 3px; padding: 10px; border: 1px solid var(--nc-border-light); border-radius: 8px; color: var(--nc-text-secondary); background: var(--nc-bg-card); font: inherit; font-size: 12px; text-align: center; cursor: pointer; }
.task-drawer-summary button:hover, .task-drawer-summary button.selected { border-color: var(--nc-primary); color: var(--nc-primary); }
.task-drawer-summary strong { color: var(--nc-text-primary); font-size: 18px; }
.task-drawer-summary .danger strong { color: var(--nc-danger); }
.task-drawer-summary .warning strong { color: var(--nc-warning); }
.task-drawer-controls { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
.task-drawer-controls :deep(.el-segmented) { min-width: 0; }
.task-drawer-list { display: grid; gap: 10px; margin-top: 14px; }
.task-drawer-item { padding: 12px; border: 1px solid var(--nc-border-light); border-radius: 8px; background: var(--nc-bg-card); }
.task-drawer-item.focused { border-color: var(--nc-primary); box-shadow: inset 3px 0 0 var(--nc-primary); }
.task-item-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 9px; }
.task-item-heading div { min-width: 0; }
.task-item-heading strong, .task-item-heading small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-item-heading small { margin-top: 3px; color: var(--nc-text-tertiary); font-size: 11px; }
.task-state-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--nc-text-tertiary); }
.task-state-dot.success { background: var(--nc-success); }
.task-state-dot.warning { background: var(--nc-warning); }
.task-state-dot.danger { background: var(--nc-danger); }
.task-state-dot.primary { background: var(--nc-primary); }
.task-drawer-item :deep(.el-progress) { margin-top: 10px; }
.task-drawer-item p { margin: 9px 0 0; overflow: hidden; color: var(--nc-text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.task-drawer-item p.error { color: var(--nc-danger); }
.task-item-actions { display: flex; justify-content: flex-end; gap: 4px; margin-top: 7px; }
.task-drawer-footer { display: flex; justify-content: flex-end; gap: 8px; }
.active-task-floating { position: fixed; z-index: 1990; right: 24px; bottom: 24px; width: min(360px, calc(100vw - 32px)); padding: 15px; border: 1px solid color-mix(in srgb, var(--nc-primary) 28%, var(--nc-border-light)); border-radius: 12px; background: var(--nc-bg-card); box-shadow: var(--nc-shadow-floating); }
.active-task-floating.minimized { width: auto; padding: 0; border: 0; border-radius: 999px; }
.floating-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.floating-heading div { min-width: 0; }
.floating-heading strong, .floating-heading span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.floating-heading span { margin-top: 4px; color: var(--nc-text-secondary); font-size: 12px; }
.active-task-floating :deep(.el-progress) { margin-top: 13px; }
.floating-actions { display: flex; justify-content: flex-end; gap: 4px; margin-top: 8px; }
.floating-capsule { padding: 9px 14px; border: 1px solid color-mix(in srgb, var(--nc-primary) 35%, var(--nc-border-light)); border-radius: 999px; background: var(--nc-bg-card); color: var(--nc-primary); box-shadow: var(--nc-shadow-card); cursor: pointer; }
@keyframes task-spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .task-drawer-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .task-drawer-controls { align-items: flex-start; flex-direction: column; }
  .active-task-floating { right: 16px; bottom: 16px; }
}
</style>
