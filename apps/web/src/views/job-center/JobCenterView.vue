<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, View } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import TaskDetailDrawer from '../../task-center/components/TaskDetailDrawer.vue'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { activeTaskStatuses } from '../../utils/taskStatus'
import { formatTaskDateTime } from '../../utils/dateTime'

const store = useTaskStore()
const route = useRoute()
const filter = ref('all')
const moduleFilter = ref('all')
const keyword = ref('')
const detailVisible = ref(false)
const detailTaskId = ref('')
const taskContextError = ref('')
const pollingConsumer = 'job-center-view'
let pollingAcquired = false

const visibleTasks = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  return store.tasks.filter((task) => (
    matchesFilter(task)
    && (moduleFilter.value === 'all' || task.module === moduleFilter.value)
    && (!search || taskSearchText(task).includes(search))
  ))
})

const columns: NcTableColumn<TaskItem>[] = [
  { key: 'task', label: '任务', valueType: 'name', fixed: 'left' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'business_status', label: '业务结果', valueType: 'status', displayValue: (row) => businessResultText(row) },
  { key: 'progress', label: '进度', valueType: 'percentage' },
  { key: 'site_name', label: '局点', valueType: 'text' },
  { key: 'device_name', label: '设备', valueType: 'name' },
  { key: 'executor', label: 'Owner / 执行端', valueType: 'text', displayValue: (row) => `${row.owner || '—'} / ${row.executor}` },
  { key: 'started_time', label: '开始时间', valueType: 'datetime', displayValue: (row) => formatTaskDateTime(row.started_time || row.created_time) },
  { key: 'duration_seconds', label: '持续时间', valueType: 'duration', displayValue: (row) => formatDuration(row.duration_seconds) },
  { key: 'session_id', label: 'Session', valueType: 'text' },
  { key: 'error_summary', label: '错误 / 告警', valueType: 'error', align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情'] },
]

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  const status = typeof route.query.status === 'string' ? route.query.status : ''
  const module = typeof route.query.module === 'string' ? route.query.module : ''
  if (status) filter.value = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(status) ? 'active' : status.toLowerCase()
  if (['devices', 'ac', 'rail', 'config', 'files', 'network', 'command-reference', 'logs'].includes(module)) moduleFilter.value = module
  startPolling()
  const taskId = typeof route.query.task_id === 'string'
    ? route.query.task_id
    : typeof route.query.task === 'string'
      ? route.query.task
      : ''
  if (taskId) openTaskDetail(taskId)
})
onActivated(startPolling)
onDeactivated(stopPolling)
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  stopPolling()
})

function startPolling(): void {
  if (pollingAcquired) return
  pollingAcquired = true
  try {
    store.acquirePolling(pollingConsumer)
  } catch {
    taskContextError.value = '任务列表自动刷新启动失败，可手动刷新后重试。'
    ElMessage.error(taskContextError.value)
  }
}

function stopPolling(): void {
  if (!pollingAcquired) return
  pollingAcquired = false
  store.releasePolling(pollingConsumer)
}

function handleVisibility(): void {
  if (document.hidden) stopPolling()
  else startPolling()
}

function openTaskDetail(task: TaskItem | string): void {
  taskContextError.value = ''
  detailTaskId.value = typeof task === 'string' ? task : task.id
  detailVisible.value = true
}

function handleDetailLoadError(taskId: string): void {
  taskContextError.value = `未找到任务 ${taskId}，已保留当前任务列表。`
  ElMessage.warning(taskContextError.value)
}

function matchesFilter(task: TaskItem): boolean {
  if (filter.value === 'all') return true
  if (filter.value === 'active') return activeTaskStatuses.includes(task.status)
  if (filter.value === 'completed') return task.status === 'COMPLETED'
  if (filter.value === 'failed') return task.status === 'FAILED'
  if (filter.value === 'stopped') return ['CANCELLED', 'STOPPED'].includes(task.status)
  if (filter.value === 'aborted') return task.status === 'ABORTED' || ['TASK_ONLY_FAILED', 'STALE'].includes(task.mapping_state)
  if (filter.value === 'warning') return task.has_warning
  if (filter.value === 'attention') {
    return !task.acknowledged_at && (
      task.status === 'FAILED'
      || task.status === 'ABORTED'
      || task.has_warning
    )
  }
  return true
}

function taskSearchText(task: TaskItem): string {
  return [
    task.id,
    task.type,
    task.name,
    task.session_id,
    task.device_name,
    task.site_name,
    task.error_summary,
    task.business_status,
    task.primary_failure_reason,
  ]
    .join(' ')
    .toLowerCase()
}

function businessStatusLabel(status: string): string {
  return {
    SUCCESS: '成功',
    PARTIAL_SUCCESS: '部分成功',
    FAILED: '失败',
    WARNING: '告警',
    NO_EFFECTIVE_TARGET: '无有效目标',
    NO_TARGET: '无有效目标',
    CANCELLED: '已取消',
  }[status] || status || '--'
}

function businessResultText(task: TaskItem): string {
  const status = businessStatusLabel(String(task.business_status || '').toUpperCase())
  if (status === '--') return status
  const counts = [
    task.success_count ? `成功 ${task.success_count}` : '',
    task.failed_count ? `失败 ${task.failed_count}` : '',
    task.skipped_count ? `跳过 ${task.skipped_count}` : '',
    task.warning_count ? `告警 ${task.warning_count}` : '',
  ].filter(Boolean)
  return counts.length ? `${status} · ${counts.join(' / ')}` : status
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  return hours ? `${hours}h ${minutes}m ${remainder}s` : minutes ? `${minutes}m ${remainder}s` : `${remainder}s`
}

function isResidentTask(task: TaskItem): boolean {
  return task.task_mode === 'resident' || task.type === 'ac_mesh_link_resident_poll'
}

function residentProgressLabel(task: TaskItem): string {
  const count = Number(task.current || task.details?.poll_count || 0)
  if (['COMPLETED', 'STOPPED'].includes(task.status)) return `已正常停止 · 共完成 ${count} 次轮询`
  if (task.status === 'STOPPING') return `正在停止 · 已完成 ${count} 次轮询`
  return `常驻运行 · 已完成 ${count} 次轮询`
}
</script>

<template>
  <section class="job-center">
    <el-alert
      title="统一任务中心"
      description="任务动作由后端 owner/capability 授权；不支持的动作会禁用并说明原因。关闭窗口不会停止后台任务。"
      type="info"
      :closable="false"
      show-icon
      class="readonly-alert"
    />
    <el-alert v-if="taskContextError" :title="taskContextError" type="warning" :closable="false" show-icon class="context-alert" />

    <div class="job-metrics">
      <article><span>任务总数</span><strong>{{ store.tasks.length }}</strong></article>
      <article class="active"><span>运行中</span><strong>{{ store.runningCount }}</strong></article>
      <article class="success"><span>已完成</span><strong>{{ store.completedCount }}</strong></article>
      <article class="danger"><span>失败</span><strong>{{ store.failedCount }}</strong></article>
      <article class="warning"><span>有告警</span><strong>{{ store.warningCount }}</strong></article>
    </div>

    <div class="content-card job-table-card">
      <div class="job-toolbar">
        <div>
          <h2>任务列表</h2>
          <p>{{ store.runningCount ? '存在运行任务，每 2 秒刷新' : '每 5 秒刷新' }} · 连续失败后降为 10 秒</p>
        </div>
        <div class="job-toolbar-actions">
          <el-input v-model="keyword" clearable placeholder="搜索任务、Session、设备或错误" style="width: 290px" />
          <el-select v-model="filter" style="width: 145px">
            <el-option label="全部" value="all" />
            <el-option label="运行中" value="active" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
            <el-option label="已停止" value="stopped" />
            <el-option label="已中断" value="aborted" />
            <el-option label="有告警" value="warning" />
            <el-option label="未处理失败/告警" value="attention" />
          </el-select>
          <el-select v-model="moduleFilter" style="width: 150px"><el-option label="全部模块" value="all" /><el-option label="设备管理" value="devices" /><el-option label="AC 管理" value="ac" /><el-option label="轨道交通" value="rail" /><el-option label="配置采集" value="config" /><el-option label="文件管理" value="files" /><el-option label="网络工具" value="network" /><el-option label="命令说明" value="command-reference" /><el-option label="日志维护" value="logs" /></el-select>
          <el-button :icon="Refresh" :loading="store.loading" @click="store.manualRefresh">刷新</el-button>
        </div>
      </div>

      <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" class="job-error" />
      <NcDataTable v-loading="store.loading" table-id="job-center-tasks" route-key="/tasks" :data="visibleTasks" :columns="columns" empty-text="暂无任务记录" height="calc(100vh - 390px)">
        <template #cell-task="{ row }">
          <strong class="cell-title">{{ row.name }}</strong>
          <small class="cell-subtitle">{{ row.type }} · {{ row.id }}</small>
        </template>
        <template #cell-status="{ row }"><NcStatusTag :status="row.status" /></template>
        <template #cell-progress="{ row }">
          <span v-if="isResidentTask(row)" class="resident-progress">{{ residentProgressLabel(row) }}</span>
          <el-progress v-else :percentage="row.progress" :stroke-width="7" />
        </template>
        <template #cell-actions="{ row }"><el-button link type="primary" :icon="View" @click="openTaskDetail(row)">详情</el-button></template>
      </NcDataTable>
    </div>

    <TaskDetailDrawer
      v-model="detailVisible"
      :task-id="detailTaskId"
      source="job-center"
      @load-error="handleDetailLoadError"
    />
  </section>
</template>

<style scoped>
.job-center { max-width: 1720px; margin: 0 auto; }
.readonly-alert, .context-alert { margin-bottom: 16px; }
.job-metrics { display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 14px; margin-bottom: 16px; }
.job-metrics article { padding: 16px 18px; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-top: 3px solid var(--nc-border-strong); border-radius: 10px; }
.job-metrics article.active { border-top-color: var(--nc-primary); }
.job-metrics article.success { border-top-color: var(--nc-success); }
.job-metrics article.danger { border-top-color: var(--nc-danger); }
.job-metrics article.warning { border-top-color: var(--nc-warning); }
.job-metrics span { display: block; color: var(--nc-text-secondary); font-size: 12px; }
.job-metrics strong { display: block; margin-top: 7px; color: var(--nc-text-primary); font-size: 25px; }
.job-table-card { min-width: 0; }
.job-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 17px 19px; border-bottom: 1px solid var(--nc-divider); }
.job-toolbar h2 { margin: 0; }
.job-toolbar p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.job-toolbar-actions { display: flex; align-items: center; gap: 10px; }
.job-error { margin: 12px 16px 0; width: auto; }
.cell-title, .cell-subtitle { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-subtitle { margin-top: 5px; color: var(--nc-text-tertiary); font-size: 11px; }
@media (max-width: 1200px) {
  .job-metrics { grid-template-columns: repeat(3, 1fr); }
  .job-toolbar { align-items: flex-start; flex-direction: column; }
  .job-toolbar-actions { flex-wrap: wrap; width: 100%; }
}
</style>
