<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CopyDocument, Refresh, View } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { useTaskStore } from '../../stores/tasks'
import type { TaskItem } from '../../types/task'
import { activeTaskStatuses } from '../../utils/taskStatus'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'

const store = useTaskStore()
const router = useRouter()
const route = useRoute()
const filter = ref('all')
const moduleFilter = ref('all')
const keyword = ref('')
const drawerVisible = ref(false)
const lastSavedCapability = ref('')
const nativeActionError = ref('')
const taskContextError = ref('')
let downloadGeneration = 0
const pollingConsumer = 'job-center-view'
let pollingAcquired = false

function clearSavedCapability(): void {
  downloadGeneration += 1
  lastSavedCapability.value = ''
  nativeActionError.value = ''
}

const visibleTasks = computed(() => {
  const search = keyword.value.trim().toLowerCase()
  return store.tasks.filter((task) => matchesFilter(task) && (moduleFilter.value === 'all' || task.module === moduleFilter.value) && (!search || taskSearchText(task).includes(search)))
})
const columns: NcTableColumn<TaskItem>[] = [
  { key: 'task', label: '任务', valueType: 'name', fixed: 'left' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'progress', label: '进度', valueType: 'percentage' },
  { key: 'site_name', label: '局点', valueType: 'text' },
  { key: 'device_name', label: '设备', valueType: 'name' },
  { key: 'executor', label: 'Owner / 执行端', valueType: 'text', displayValue: (row) => `${row.owner || '—'} / ${row.executor}` },
  { key: 'started_time', label: '开始时间', valueType: 'datetime', displayValue: (row) => formatTime(row.started_time || row.created_time) },
  { key: 'duration_seconds', label: '持续时间', valueType: 'duration', displayValue: (row) => formatDuration(row.duration_seconds) },
  { key: 'session_id', label: 'Session', valueType: 'text' },
  { key: 'error_summary', label: '错误 / 告警', valueType: 'error', align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情'] },
]

watch(drawerVisible, (visible) => {
  store.setDetailVisible(visible)
  if (!visible) clearSavedCapability()
})
watch(() => store.selected?.id, clearSavedCapability)

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  const status = typeof route.query.status === 'string' ? route.query.status : ''
  const module = typeof route.query.module === 'string' ? route.query.module : ''
  if (status) filter.value = ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(status) ? 'active' : status.toLowerCase()
  if (['devices', 'ac', 'rail', 'config', 'files', 'network', 'command-reference', 'logs'].includes(module)) moduleFilter.value = module
  reportTaskWindowInteractive()
  startPolling()
  const taskId = typeof route.query.task_id === 'string' ? route.query.task_id : typeof route.query.task === 'string' ? route.query.task : ''
  if (taskId) void selectContextTask(taskId)
})

onBeforeUnmount(() => {
  clearSavedCapability()
  document.removeEventListener('visibilitychange', handleVisibility)
  stopPolling()
})

function reportTaskWindowInteractive(): void {
  if (route.path !== '/desktop/tasks' || route.query.task_window !== '1') return
  getPlatformAdapter().reportRendererReady(true, 'interactive', 'task-window')
}

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

async function selectContextTask(taskId: string): Promise<void> {
  try {
    await store.selectTask(taskId)
    drawerVisible.value = true
  } catch {
    taskContextError.value = `未找到任务 ${taskId}，已保留当前任务列表。`
    ElMessage.warning(taskContextError.value)
  }
}

async function openDetail(task: TaskItem): Promise<void> {
  try {
    await store.selectTask(task.id)
    drawerVisible.value = true
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '任务详情加载失败')
  }
}

function handleVisibility(): void {
  if (document.hidden) stopPolling()
  else startPolling()
}

function matchesFilter(task: TaskItem): boolean {
  if (filter.value === 'all') return true
  if (filter.value === 'active') return activeTaskStatuses.includes(task.status)
  if (filter.value === 'completed') return task.status === 'COMPLETED'
  if (filter.value === 'failed') return task.status === 'FAILED'
  if (filter.value === 'stopped') return ['CANCELLED', 'STOPPED'].includes(task.status)
  if (filter.value === 'aborted') return task.status === 'ABORTED' || ['TASK_ONLY_FAILED', 'STALE'].includes(task.mapping_state)
  if (filter.value === 'warning') return task.has_warning
  return true
}

function taskSearchText(task: TaskItem): string {
  return [task.id, task.type, task.name, task.session_id, task.device_name, task.site_name, task.error_summary]
    .join(' ')
    .toLowerCase()
}

function formatTime(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const remainder = total % 60
  return hours ? `${hours}h ${minutes}m ${remainder}s` : minutes ? `${minutes}m ${remainder}s` : `${remainder}s`
}

async function copyText(value: string, success: string): Promise<void> {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(success)
  } catch {
    ElMessage.error('复制失败，请手工选择文本')
  }
}

function acceptanceCommand(task: TaskItem): string {
  return `python -m scripts.maintenance.check_online_mr_session_state --task-id "${task.id}"`
}

function openOnlineMr(task: TaskItem): void {
  void router.push({ name: 'online-mr-realtime', query: { session_id: task.session_id } })
}

async function cancelSelected(): Promise<void> {
  clearSavedCapability()
  try { await store.requestCancel(); ElMessage.success('已请求停止任务') }
  catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : '停止任务失败') }
}

async function downloadArtifact(): Promise<void> {
  if (!store.selected?.artifact_download) return
  const taskId = store.selected.id
  clearSavedCapability()
  const generation = downloadGeneration
  const artifact = store.selected.artifact_download
  const result = await downloadBackendResource({
    apiPath: artifact.api_path,
    query: artifact.query,
    suggestedName: artifact.display_name,
  })
  if (generation !== downloadGeneration || store.selected?.id !== taskId || !drawerVisible.value) return
  if (result.status === 'saved') {
    lastSavedCapability.value = result.capabilityId || ''
    ElMessage.success('Artifact 已保存')
  } else if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
}

function nativeFailureMessage(action: 'open' | 'reveal', error = ''): string {
  if (error.includes('文件授权已过期')) return '文件授权已过期，请重新下载后再试'
  if (error.includes('文件授权')) return '文件授权已失效，请重新下载后再试'
  return action === 'open'
    ? '系统未能打开文件，请检查文件关联后重试'
    : '系统未能定位文件，请重新下载后再试'
}

async function runSavedAction(action: 'open' | 'reveal'): Promise<void> {
  const capabilityId = lastSavedCapability.value
  if (!capabilityId) return
  const generation = downloadGeneration
  nativeActionError.value = ''
  try {
    const adapter = getPlatformAdapter()
    const result = await (action === 'open'
      ? adapter.openPath(capabilityId)
      : adapter.showItemInFolder(capabilityId))
    if (generation !== downloadGeneration || capabilityId !== lastSavedCapability.value) return
    if (result.success) {
      ElMessage.success(action === 'open' ? '已请求系统打开文件' : '已在文件夹中定位')
      return
    }
    nativeActionError.value = nativeFailureMessage(action, result.error)
  } catch {
    if (generation !== downloadGeneration || capabilityId !== lastSavedCapability.value) return
    nativeActionError.value = nativeFailureMessage(action)
  }
  ElMessage.error(nativeActionError.value)
}

const openSaved = () => runSavedAction('open')
const revealSaved = () => runSavedAction('reveal')
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
        <template #cell-progress="{ row }"><el-progress :percentage="row.progress" :stroke-width="7" /></template>
        <template #cell-actions="{ row }"><el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button></template>
      </NcDataTable>
    </div>

    <el-drawer v-model="drawerVisible" title="任务详情" size="min(820px, 94vw)">
      <template v-if="store.selected">
        <div class="detail-heading">
          <div><h2>{{ store.selected.name }}</h2><p>{{ store.selected.id }}</p></div>
          <NcStatusTag :status="store.selected.status" />
        </div>

        <el-alert v-if="store.detailError" :title="store.detailError" type="error" :closable="false" show-icon />
        <el-alert v-if="store.selected.error_summary" :title="store.selected.error_summary" :type="store.selected.status === 'FAILED' ? 'error' : 'warning'" :closable="false" show-icon class="detail-alert" />

        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务类型">{{ store.selected.type }}</el-descriptions-item>
          <el-descriptions-item label="状态 / 阶段">{{ store.selected.status }} / {{ store.selected.phase || '--' }}</el-descriptions-item>
          <el-descriptions-item label="进度">{{ store.selected.progress }}%</el-descriptions-item>
          <el-descriptions-item label="Owner / 执行端">{{ store.selected.owner || '--' }} / {{ store.selected.executor }}</el-descriptions-item>
          <el-descriptions-item label="局点">{{ store.selected.site_name || '--' }}</el-descriptions-item>
          <el-descriptions-item label="设备">{{ store.selected.device_name || '--' }}（{{ store.selected.device_id || '--' }}）</el-descriptions-item>
          <el-descriptions-item label="MR">{{ store.selected.mr_name || '--' }}</el-descriptions-item>
          <el-descriptions-item label="Agent">{{ store.selected.agent || '--' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(store.selected.started_time) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(store.selected.finished_time) }}</el-descriptions-item>
          <el-descriptions-item label="持续时间">{{ formatDuration(store.selected.duration_seconds) }}</el-descriptions-item>
          <el-descriptions-item label="Mapping">{{ store.selected.mapping_state || '--' }}</el-descriptions-item>
          <el-descriptions-item label="错误码">{{ store.selected.error_code || '--' }}</el-descriptions-item>
          <el-descriptions-item label="消息">{{ store.selected.message || '--' }}</el-descriptions-item>
          <el-descriptions-item label="Session ID" :span="2"><code>{{ store.selected.session_id || '--' }}</code></el-descriptions-item>
          <template v-if="store.selected.type === 'ac_mesh_link_refresh'">
            <el-descriptions-item label="Mesh-Link 快照 ID">{{ store.selected.snapshot_id ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="链路记录数">{{ store.selected.records_count ?? '--' }}</el-descriptions-item>
            <el-descriptions-item label="Parser">{{ store.selected.parser_version || '--' }}</el-descriptions-item>
          </template>
        </el-descriptions>

        <div v-if="store.selected.session_id" class="association-actions">
          <el-button type="primary" @click="openOnlineMr(store.selected)">查看 Online MR 实时展示</el-button>
          <el-button :icon="CopyDocument" @click="copyText(store.selected.session_id, 'Session ID 已复制')">复制 Session ID</el-button>
          <el-button :icon="CopyDocument" @click="copyText(acceptanceCommand(store.selected), '验收命令已复制')">复制验收命令</el-button>
        </div>
        <div class="association-actions">
          <el-tooltip :content="store.selected.cancel_reason" :disabled="store.selected.cancellable"><span><el-button type="danger" :disabled="!store.selected.cancellable" @click="cancelSelected">停止 / 取消</el-button></span></el-tooltip>
          <el-tooltip :content="store.selected.retry_reason" :disabled="store.selected.retryable"><span><el-button :disabled="!store.selected.retryable">重试</el-button></span></el-tooltip>
          <el-tooltip :content="store.selected.artifact_reason" :disabled="Boolean(store.selected.artifact_download)"><span><el-button :disabled="!store.selected.artifact_download" @click="downloadArtifact">Artifact 下载</el-button></span></el-tooltip>
          <template v-if="lastSavedCapability">
            <el-button @click="openSaved">打开文件</el-button>
            <el-button @click="revealSaved">打开所在目录</el-button>
          </template>
        </div>
        <el-alert v-if="nativeActionError" :title="nativeActionError" type="error" :closable="false" show-icon class="native-action-error" />

        <section class="log-section">
          <div class="log-heading">
            <div><h3>任务日志 tail</h3><p>默认隐藏；展开后每秒读取最后 300 条结构化事件。</p></div>
            <el-button @click="store.setLogsExpanded(!store.logsExpanded)">{{ store.logsExpanded ? '隐藏日志' : '显示日志' }}</el-button>
          </div>
          <template v-if="store.logsExpanded">
            <el-alert v-if="store.logError" :title="store.logError" type="error" :closable="false" show-icon />
            <div class="task-log">
              <div v-for="line in store.logs" :key="line.sequence" :class="['log-line', line.level.toLowerCase()]">
                <time>{{ formatTime(line.time) }}</time><span>{{ line.type }}</span><p>{{ line.message }}</p>
              </div>
              <el-empty v-if="!store.logs.length && !store.logError" description="暂无日志" :image-size="68" />
            </div>
          </template>
        </section>
      </template>
    </el-drawer>
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
.job-toolbar h2, .detail-heading h2, .log-heading h3 { margin: 0; }
.job-toolbar p, .detail-heading p, .log-heading p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.job-toolbar-actions { display: flex; align-items: center; gap: 10px; }
.job-error { margin: 12px 16px 0; width: auto; }
.cell-title, .cell-subtitle { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-subtitle { margin-top: 5px; color: var(--nc-text-tertiary); font-size: 11px; }
.detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.detail-alert { margin: 0 0 15px; }
.association-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.native-action-error { margin-top: 12px; }
.log-section { margin-top: 22px; }
.log-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.task-log { min-height: 150px; max-height: 360px; padding: 12px; overflow: auto; color: var(--nc-text-code); background: var(--nc-bg-code); border-radius: 8px; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; }
.log-line { display: grid; grid-template-columns: 155px 90px 1fr; gap: 10px; padding: 4px 2px; border-bottom: 1px solid var(--nc-border-code); }
.log-line time, .log-line span { color: var(--nc-text-code-muted); }
.log-line p { margin: 0; overflow-wrap: anywhere; }
.log-line.error p { color: var(--nc-text-code-danger); }
.log-line.warning p { color: var(--nc-text-code-warning); }
code { overflow-wrap: anywhere; font-family: Consolas, "Microsoft YaHei", monospace; }
@media (max-width: 1200px) {
  .job-metrics { grid-template-columns: repeat(3, 1fr); }
  .job-toolbar { align-items: flex-start; flex-direction: column; }
  .job-toolbar-actions { flex-wrap: wrap; width: 100%; }
}
</style>
