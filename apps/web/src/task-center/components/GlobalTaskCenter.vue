<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { Close, Loading, Tickets, View } from '@element-plus/icons-vue'

import { getPlatformAdapter } from '../../platform/runtime'
import { useTaskStore } from '../../stores/tasks'
import { useWorkspaceStore } from '../../stores/workspace'
import type { TaskItem } from '../../types/task'
import { activeTaskStatuses, taskStatusLabel, taskStatusType } from '../../utils/taskStatus'
import {
  onTaskCenterOpenRequested,
  type TaskCenterOpenContext,
} from '../events'

const GLOBAL_POLLING_CONSUMER = 'global-task-center'
const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'ABORTED', 'STOPPED'])
const QUEUED_STATUSES = new Set(['CREATED', 'QUEUED', 'PENDING'])
const RUNNING_STATUSES = new Set(['STARTING', 'RUNNING', 'STOPPING'])

const store = useTaskStore()
const workspace = useWorkspaceStore()
const drawerVisible = ref(false)
const focusedTaskId = ref('')
const floatingMinimized = ref(false)
const floatingDismissedSignature = ref('')
const notificationStates = new Map<string, string>()
let notificationsReady = false
let removeLocalOpenListener: (() => void) | undefined
let removeNativeOpenListener: (() => void) | undefined

const runningTasks = computed(() => (
  store.tasks.filter((task) => RUNNING_STATUSES.has(task.status))
))
const queuedTasks = computed(() => (
  store.tasks.filter((task) => QUEUED_STATUSES.has(task.status))
))
const failedTasks = computed(() => (
  store.tasks.filter((task) => task.status === 'FAILED' || task.status === 'ABORTED')
))
const warningTasks = computed(() => (
  store.tasks.filter((task) => task.has_warning)
))
const activeTasks = computed(() => (
  store.tasks
    .filter((task) => activeTaskStatuses.includes(task.status))
    .sort(sortNewest)
))
const badgeCount = computed(() => (
  failedTasks.value.length || activeTasks.value.length || warningTasks.value.length
))
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
  const priority = store.tasks
    .filter((task) => (
      activeTaskStatuses.includes(task.status)
      || task.status === 'FAILED'
      || task.status === 'ABORTED'
      || task.has_warning
      || task.id === focusedTaskId.value
    ))
    .sort(sortNewest)
  const fallback = store.tasks.filter((task) => !priority.includes(task)).sort(sortNewest)
  return [...priority, ...fallback].slice(0, 12)
})
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
  removeLocalOpenListener = onTaskCenterOpenRequested(openDrawer)
  removeNativeOpenListener = getPlatformAdapter().onTaskCenterOpenRequested(openDrawer)
  await store.refresh()
  seedNotificationStates()
  notificationsReady = true
  store.acquirePolling(GLOBAL_POLLING_CONSUMER)
})

onBeforeUnmount(() => {
  notificationsReady = false
  removeLocalOpenListener?.()
  removeNativeOpenListener?.()
  store.releasePolling(GLOBAL_POLLING_CONSUMER)
})

function sortNewest(left: TaskItem, right: TaskItem): number {
  return String(right.updated_time || right.created_time).localeCompare(
    String(left.updated_time || left.created_time),
  )
}

function openDrawer(context: TaskCenterOpenContext = {}): void {
  focusedTaskId.value = context.taskId || ''
  drawerVisible.value = true
  if (context.taskId && !store.tasks.some((task) => task.id === context.taskId)) {
    void store.refresh()
  }
}

function dismissFloating(): void {
  floatingDismissedSignature.value = activeSignature.value
}

async function openFullTaskCenter(task?: TaskItem): Promise<void> {
  drawerVisible.value = false
  const query = new URLSearchParams()
  const taskId = task?.id || focusedTaskId.value
  if (taskId) query.set('task_id', taskId)
  if (task?.module) query.set('module', task.module)
  await workspace.openOrActivateRoute(`/tasks${query.size ? `?${query}` : ''}`)
}

async function cancelTask(task: TaskItem): Promise<void> {
  try {
    await store.requestCancelTask(task.id)
    ElMessage.success('已请求停止任务')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '停止任务失败')
  }
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
    notifyTaskTerminal(task)
  }
  for (const id of notificationStates.keys()) {
    if (!currentIds.has(id)) notificationStates.delete(id)
  }
}

function notificationKey(task: TaskItem): string {
  return `${task.status}:${task.has_warning ? 'warning' : 'normal'}`
}

function notifyTaskTerminal(task: TaskItem): void {
  const kind = task.status === 'FAILED' || task.status === 'ABORTED'
    ? 'failure'
    : task.has_warning
      ? 'warning'
      : 'success'
  const title = terminalTitle(task, kind)
  const body = task.error_summary || task.message || taskStatusLabel(task.status)
  const foreground = document.visibilityState === 'visible' && document.hasFocus()

  if (foreground) {
    ElNotification({
      title,
      message: body,
      type: kind === 'failure' ? 'error' : kind,
      duration: kind === 'success' ? 5000 : 0,
      onClick: () => openDrawer({ taskId: task.id, module: task.module as TaskCenterOpenContext['module'] }),
    })
    return
  }
  if (task.status === 'CANCELLED' || task.status === 'STOPPED') return
  const runtime = getPlatformAdapter()
  if (runtime.hostType !== 'electron') return
  const eventId = `${task.id}:${task.status}:${task.updated_time || task.finished_time}`
    .replace(/[^A-Za-z0-9_.:-]/g, '_')
    .slice(0, 180)
  void runtime.showTaskNotification({
    eventId,
    taskId: task.id,
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
          @click="openDrawer()"
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
      title="任务中心"
      size="min(520px, 96vw)"
      class="task-center-drawer"
      data-testid="task-center-drawer"
    >
      <div class="task-drawer-summary">
        <span><strong>{{ runningTasks.length }}</strong> 正在运行</span>
        <span><strong>{{ queuedTasks.length }}</strong> 等待</span>
        <span class="danger"><strong>{{ failedTasks.length }}</strong> 失败</span>
        <span class="warning"><strong>{{ warningTasks.length }}</strong> 告警</span>
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
              <small>{{ taskStatusLabel(task.status) }} · {{ task.updated_time || task.created_time }}</small>
            </div>
            <el-tag :type="task.has_warning ? 'warning' : taskStatusType(task.status)" size="small">
              {{ task.has_warning ? '部分完成' : taskStatusLabel(task.status) }}
            </el-tag>
          </div>
          <el-progress
            v-if="activeTaskStatuses.includes(task.status)"
            :percentage="task.progress"
            :stroke-width="7"
            :show-text="true"
          />
          <p :class="{ error: task.status === 'FAILED' || task.status === 'ABORTED' }">
            {{ task.error_summary || task.message || task.phase || '等待任务状态更新' }}
          </p>
          <div class="task-item-actions">
            <el-button
              v-if="task.cancellable"
              link
              type="danger"
              @click="cancelTask(task)"
            >取消</el-button>
            <el-button link type="primary" :icon="View" @click="openFullTaskCenter(task)">
              {{ task.status === 'FAILED' ? '查看原因' : '查看详情' }}
            </el-button>
          </div>
        </article>
      </div>
      <el-empty v-else description="暂无任务记录" />

      <template #footer>
        <div class="task-drawer-footer">
          <el-button @click="store.manualRefresh">刷新</el-button>
          <el-button type="primary" @click="openFullTaskCenter()">进入完整任务中心</el-button>
        </div>
      </template>
    </el-drawer>

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
          <el-button link type="primary" @click="openDrawer({ taskId: primaryActiveTask?.id })">查看详情</el-button>
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
.task-drawer-summary span { display: grid; gap: 3px; padding: 10px; border: 1px solid var(--nc-border-light); border-radius: 9px; color: var(--nc-text-secondary); font-size: 12px; text-align: center; }
.task-drawer-summary strong { color: var(--nc-text-primary); font-size: 18px; }
.task-drawer-summary .danger strong { color: var(--nc-danger); }
.task-drawer-summary .warning strong { color: var(--nc-warning); }
.task-drawer-list { display: grid; gap: 10px; margin-top: 14px; }
.task-drawer-item { padding: 12px; border: 1px solid var(--nc-border-light); border-radius: 10px; background: var(--nc-bg-card); }
.task-drawer-item.focused { border-color: var(--nc-primary); box-shadow: inset 3px 0 0 var(--nc-primary); }
.task-item-heading { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 9px; }
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
.active-task-floating { position: fixed; z-index: 2050; right: 24px; bottom: 24px; width: min(360px, calc(100vw - 32px)); padding: 15px; border: 1px solid color-mix(in srgb, var(--nc-primary) 28%, var(--nc-border-light)); border-radius: 12px; background: var(--nc-bg-card); box-shadow: var(--nc-shadow-floating); }
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
  .active-task-floating { right: 16px; bottom: 16px; }
}
</style>
