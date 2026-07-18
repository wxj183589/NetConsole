<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { isFeatureEnabled } from '../../features'
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import {
  cancelMaintenanceTask,
  clearLogs,
  getAbout,
  getChangelog,
  getLogs,
  getMaintenanceTask,
  maintenanceArtifactDownloadRequest,
  openMaintenanceDirectory,
  recoverMaintenanceTasks,
  requestAboutLink,
  requestOpenSourceLink,
  startCleanup,
  startLogExport,
  startOpenSourceExport,
  startOpenSourceScan,
  type AboutInfo,
  type Changelog,
  type CleanupItem,
  type CleanupItemId,
  type LogEntry,
  type MaintenanceTask,
  type OpenSourceComponent,
} from '../../api/systemMaintenance'

const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const activeTab = ref('logs')
const loading = ref(false)
const logs = ref<LogEntry[]>([])
const keyword = ref('')
const level = ref('')
const page = ref(1)
const pageSize = ref<50 | 100 | 200 | 500>(200)
const total = ref(0)
const tasks = ref<MaintenanceTask[]>([])
const currentTask = ref<MaintenanceTask>()
const cleanupItems = ref<CleanupItem[]>([])
const retentionDays = ref(3)
const selectedCleanupItemIds = ref<CleanupItemId[]>([])
const components = ref<OpenSourceComponent[]>([])
const openSourceTaskId = ref('')
const changelog = ref<Changelog>()
const about = ref<AboutInfo>()
let pollTimer: ReturnType<typeof setTimeout> | undefined

const taskBusy = computed(() => Boolean(currentTask.value && !terminalStates.has(currentTask.value.status)))
const logColumns: NcTableColumn<LogEntry>[] = [
  { key: 'time', label: '时间', valueType: 'datetime', fixed: 'left' },
  { key: 'display_level', label: '级别', valueType: 'status' },
  { key: 'display_event', label: '事件', valueType: 'description', alignmentReason: 'description' },
  { key: 'display_detail', label: '详情', valueType: 'description', alignmentReason: 'long-text' },
  { key: 'actions', label: '复制', valueType: 'actions', cellKind: 'actions', actionLabels: ['整行', '原始事件', '原始详情'] },
]
const cleanupColumns: NcTableColumn<CleanupItem>[] = [
  { key: 'selected', label: '选择', valueType: 'selection', hideable: false },
  { key: 'title', label: '类别', valueType: 'name' },
  { key: 'description', label: '范围', valueType: 'description', alignmentReason: 'description' },
  { key: 'retention_policy', label: '策略', valueType: 'text' },
  { key: 'file_count', label: '文件数', valueType: 'number' },
  { key: 'total_bytes', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.total_bytes) },
  { key: 'status', label: '状态', valueType: 'status' },
]
const componentColumns: NcTableColumn<OpenSourceComponent>[] = [
  { key: 'name', label: '组件名称', valueType: 'name', fixed: 'left' },
  { key: 'version', label: '版本', valueType: 'text' },
  { key: 'license', label: '许可证', valueType: 'text' },
  { key: 'purpose', label: '用途', valueType: 'description', alignmentReason: 'description' },
  { key: 'homepage', label: '项目地址', valueType: 'description', alignmentReason: 'path' },
  { key: 'note', label: '备注', valueType: 'description', alignmentReason: 'description' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['复制', '打开'] },
]

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : '操作失败'
}

async function loadLogs(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  try {
    const result = await getLogs({ page: page.value, page_size: pageSize.value, keyword: keyword.value.trim(), level: level.value })
    logs.value = result.items
    page.value = result.page
    pageSize.value = result.page_size
    total.value = result.total
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    loading.value = false
  }
}

async function confirmClearLogs(): Promise<void> {
  try {
    await ElMessageBox.confirm('只清空日志中心记录，不删除采集数据、原始日志或报告。', '清空日志', { type: 'warning' })
    const result = await clearLogs()
    ElMessage.success(result.message)
    await loadLogs(true)
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(errorMessage(cause))
  }
}

async function copyText(text: string, message = '已复制'): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(message)
  } catch {
    ElMessage.error('剪贴板不可用')
  }
}

function copyLogRow(row: LogEntry): Promise<void> {
  return copyText(`时间: ${row.time}\n级别: ${row.display_level}\n事件: ${row.display_event}\n详情: ${row.display_detail}`, '整行已复制')
}

function copyCell(row: LogEntry, column: { property?: keyof LogEntry }, _cell: unknown, event: MouseEvent): void {
  event.preventDefault()
  const property = column.property
  if (property) void copyText(String(row[property] ?? ''), '单元格已复制')
}

function applyTaskResult(task: MaintenanceTask): void {
  currentTask.value = task
  tasks.value = [task, ...tasks.value.filter((item) => item.task_id !== task.task_id)].slice(0, 20)
  if (task.cleanup_items.length) cleanupItems.value = task.cleanup_items
  if (
    task.action === 'cleanup_scan'
    && task.status === 'COMPLETED'
    && task.cleanup_items.length
  ) {
    selectedCleanupItemIds.value = task.cleanup_items
      .filter((item) => item.file_count > 0)
      .map((item) => item.item_id)
  }
  if (task.components.length) {
    components.value = task.components
    openSourceTaskId.value = task.task_id
  }
  if (terminalStates.has(task.status)) {
    if (task.status === 'FAILED') ElMessage.error(task.error_message || '任务失败')
    else if (task.status === 'CANCELLED') ElMessage.warning('任务已取消')
    else ElMessage.success(task.message || '任务完成')
    return
  }
  pollTimer = setTimeout(() => void pollTask(task.task_id), 800)
}

async function pollTask(taskId: string): Promise<void> {
  try {
    applyTaskResult(await getMaintenanceTask(taskId))
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function scanCleanup(): Promise<void> {
  if (taskBusy.value) return
  try {
    selectedCleanupItemIds.value = []
    applyTaskResult(await startCleanup({ mode: 'scan', retention_days: retentionDays.value }))
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function confirmCleanup(): Promise<void> {
  if (taskBusy.value) return
  if (!selectedCleanupItemIds.value.length) {
    ElMessage.warning('请先扫描并选择至少一个可清理类别')
    return
  }
  const selectedNames = cleanupItems.value
    .filter((item) => selectedCleanupItemIds.value.includes(item.item_id))
    .map((item) => item.title)
    .join('、')
  try {
    await ElMessageBox.confirm(
      `将重新扫描并清理“${selectedNames}”中超过 ${retentionDays.value} 天的文件。后台任务、导入预览和取消文件不会删除。`,
      '确认安全清理',
      { type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消' },
    )
    applyTaskResult(await startCleanup({
      mode: 'clean',
      retention_days: retentionDays.value,
      selected_item_ids: [...selectedCleanupItemIds.value],
      confirmed: true,
    }))
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(errorMessage(cause))
  }
}

function setCleanupSelected(itemId: CleanupItemId, selected: string | number | boolean): void {
  if (Boolean(selected)) {
    if (!selectedCleanupItemIds.value.includes(itemId)) {
      selectedCleanupItemIds.value = [...selectedCleanupItemIds.value, itemId]
    }
    return
  }
  selectedCleanupItemIds.value = selectedCleanupItemIds.value.filter((value) => value !== itemId)
}

async function scanOpenSource(): Promise<void> {
  if (taskBusy.value) return
  try {
    applyTaskResult(await startOpenSourceScan())
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function runLogExport(scope: 'current' | 'all'): Promise<void> {
  if (taskBusy.value) return
  try {
    applyTaskResult(await startLogExport({ scope, keyword: keyword.value.trim(), level: level.value, page: page.value, page_size: pageSize.value }))
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function runOpenSourceExport(format: 'txt' | 'xlsx'): Promise<void> {
  if (taskBusy.value) return
  try {
    applyTaskResult(await startOpenSourceExport(format))
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function cancelCurrentTask(): Promise<void> {
  if (!currentTask.value) return
  try {
    applyTaskResult(await cancelMaintenanceTask(currentTask.value.task_id))
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function downloadArtifact(task: MaintenanceTask): Promise<void> {
  if (!task.available) return
  const result = await downloadBackendResource(maintenanceArtifactDownloadRequest(task))
  if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
  else if (result.status !== 'cancelled') ElMessage.success('Artifact 已保存')
}

async function openDirectory(kind: 'logs' | 'cache'): Promise<void> {
  try {
    const result = await openMaintenanceDirectory(kind)
    if (result.success) ElMessage.success('目录已打开')
    else ElMessage.error(result.message || '目录打开失败')
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function openAboutLink(linkId: string): Promise<void> {
  try {
    const { url } = await requestAboutLink(linkId)
    const result = await getPlatformAdapter().openExternalUrl(url)
    if (!result.success) ElMessage.error(result.error || '外链打开失败')
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function openComponentLink(index: number): Promise<void> {
  if (!openSourceTaskId.value) return
  try {
    const { url } = await requestOpenSourceLink(openSourceTaskId.value, index)
    const result = await getPlatformAdapter().openExternalUrl(url)
    if (!result.success) ElMessage.error(result.error || '外链打开失败')
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

function componentText(item: OpenSourceComponent): string {
  return `组件名称：${item.name}\n版本：${item.version}\n许可证：${item.license}\n用途：${item.purpose}\n项目地址：${item.homepage}\n备注：${item.note}`
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 ** 2).toFixed(1)} MB`
}

onMounted(async () => {
  const results = await Promise.allSettled([loadLogs(), getChangelog(), getAbout(), recoverMaintenanceTasks()])
  if (results[1].status === 'fulfilled') changelog.value = results[1].value
  if (results[2].status === 'fulfilled') about.value = results[2].value
  if (results[3].status === 'fulfilled') {
    tasks.value = results[3].value
    const completedScan = tasks.value.find((task) => task.action === 'open_source_scan' && task.components.length)
    const completedCleanup = tasks.value.find((task) => task.cleanup_items.length)
    if (completedScan) {
      components.value = completedScan.components
      openSourceTaskId.value = completedScan.task_id
    }
    if (completedCleanup) {
      cleanupItems.value = completedCleanup.cleanup_items
      if (completedCleanup.action === 'cleanup_scan') {
        selectedCleanupItemIds.value = completedCleanup.cleanup_items
          .filter((item) => item.file_count > 0)
          .map((item) => item.item_id)
      }
    }
    const active = tasks.value.find((task) => !terminalStates.has(task.status))
    if (active) applyTaskResult(active)
  }
})

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<template>
  <section class="maintenance-page">
    <header class="page-heading">
      <div><p class="eyebrow">SYSTEM / SAFE MAINTENANCE</p><h1>应用日志与安全维护</h1><p>日志、清理、更新记录、开源许可与关于信息均来自现有 Python 事实源。</p></div>
      <div class="actions"><el-button :loading="loading" @click="loadLogs()">刷新日志</el-button></div>
    </header>

    <el-alert title="清理仅作用于软件运行日志与缓存白名单；采集数据、MR 原始日志、数据库、报告和导入文件不会被删除。" type="info" show-icon :closable="false" />

    <el-card v-if="currentTask" shadow="never" class="task-card">
      <template #header><div class="card-header"><span>后台任务 · {{ currentTask.action }}</span><el-tag>{{ currentTask.status }}</el-tag></div></template>
      <el-progress :percentage="currentTask.progress" :status="currentTask.status === 'FAILED' ? 'exception' : undefined" />
      <p>{{ currentTask.error_message || currentTask.message || currentTask.stage || '任务已提交' }}</p>
      <div class="actions"><el-button :disabled="!taskBusy" @click="cancelCurrentTask">取消</el-button><el-button v-if="currentTask.available" type="primary" @click="downloadArtifact(currentTask)">下载 Artifact</el-button></div>
    </el-card>

    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="运行日志" name="logs">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索事件或详情" @keyup.enter="loadLogs(true)" />
          <el-select v-model="level" clearable placeholder="全部级别"><el-option label="信息" value="INFO" /><el-option label="警告" value="WARNING" /><el-option label="错误" value="ERROR" /><el-option label="调试" value="DEBUG" /><el-option label="严重" value="CRITICAL" /></el-select>
          <el-button @click="loadLogs(true)">查询</el-button>
          <el-button :disabled="!isFeatureEnabled('desktop.native_bridge')" @click="openDirectory('logs')">打开日志目录</el-button>
          <el-button type="danger" plain @click="confirmClearLogs">清空记录</el-button>
          <el-button :disabled="taskBusy || !isFeatureEnabled('web.logs_export')" @click="runLogExport('current')">导出当前页</el-button>
          <el-button :disabled="taskBusy || !isFeatureEnabled('web.logs_export')" @click="runLogExport('all')">导出全部筛选结果</el-button>
        </div>
        <NcDataTable v-loading="loading" :data="logs" :columns="logColumns" table-id="system-log-entries" route-key="/logs" height="520" empty-text="暂无日志记录" @cell-contextmenu="copyCell">
          <template #cell-actions="{ row }"><el-button link @click="copyLogRow(row)">整行</el-button><el-button link @click="copyText(row.raw_event, '原始事件已复制')">原始事件</el-button><el-button link @click="copyText(row.raw_detail, '原始详情已复制')">原始详情</el-button></template>
        </NcDataTable>
        <div class="pagination"><span>共 {{ total }} 条</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[50, 100, 200, 500]" layout="sizes, prev, pager, next" :total="total" @change="loadLogs()" /></div>
        <p class="hint">右键任意表格单元格可复制该单元格；Web 展示与导出会隐藏秘密、私有地址和本机绝对路径。</p>
      </el-tab-pane>

      <el-tab-pane label="安全清理" name="cleanup">
        <div class="toolbar"><span>保留最近</span><el-input-number v-model="retentionDays" :min="1" :max="365" controls-position="right" /><span>天</span><el-button :loading="taskBusy" :disabled="!isFeatureEnabled('system.disk_cleanup')" @click="scanCleanup">扫描白名单</el-button><el-button type="danger" plain :loading="taskBusy" :disabled="!isFeatureEnabled('system.disk_cleanup') || !selectedCleanupItemIds.length" @click="confirmCleanup">清理所选项目</el-button><el-button :disabled="!isFeatureEnabled('desktop.native_bridge')" @click="openDirectory('cache')">打开缓存目录</el-button></div>
        <NcDataTable :data="cleanupItems" :columns="cleanupColumns" table-id="system-cleanup-items" route-key="/logs" empty-text="请先扫描白名单">
          <template #cell-selected="{ row }"><el-checkbox :model-value="selectedCleanupItemIds.includes(row.item_id)" :disabled="row.file_count === 0" @change="setCleanupSelected(row.item_id, $event)" /></template>
        </NcDataTable>
        <p v-if="currentTask?.action === 'cleanup_clean'" class="hint">已处理 {{ currentTask.processed_files }} 项，已删除 {{ currentTask.deleted_files }} 项，失败 {{ currentTask.failed_count }} 项，释放 {{ formatBytes(currentTask.freed_bytes) }}。</p>
      </el-tab-pane>

      <el-tab-pane label="版本更新日志" name="changelog">
        <pre class="document">{{ changelog?.content || '更新日志暂不可用' }}</pre>
      </el-tab-pane>

      <el-tab-pane label="开源许可" name="open-source">
        <div class="toolbar"><el-button :loading="taskBusy" :disabled="!isFeatureEnabled('system.open_source')" @click="scanOpenSource">刷新组件列表</el-button><el-button :disabled="taskBusy || !isFeatureEnabled('system.open_source')" @click="runOpenSourceExport('txt')">导出 TXT</el-button><el-button :disabled="taskBusy || !isFeatureEnabled('system.open_source')" @click="runOpenSourceExport('xlsx')">导出 XLSX</el-button></div>
        <NcDataTable :data="components" :columns="componentColumns" table-id="system-open-source-components" route-key="/logs" height="520" empty-text="请先扫描运行依赖">
          <template #cell-actions="{ row, $index }"><el-button link @click="copyText(componentText(row), '组件信息已复制')">复制</el-button><el-button link :disabled="!row.homepage" @click="openComponentLink($index)">打开</el-button></template>
        </NcDataTable>
      </el-tab-pane>

      <el-tab-pane label="关于" name="about">
        <el-descriptions v-if="about" :column="1" border><el-descriptions-item label="应用">{{ about.title }}</el-descriptions-item><el-descriptions-item label="版本">{{ about.version }}</el-descriptions-item><el-descriptions-item label="作者">{{ about.author }}</el-descriptions-item><el-descriptions-item label="外部工具说明">{{ about.external_tool_notice }}</el-descriptions-item></el-descriptions>
        <el-card v-for="repository in about?.repositories || []" :key="repository.link_id" shadow="never" class="repository"><span>{{ repository.label }}</span><div><el-button link @click="copyText(repository.label, '仓库地址已复制')">复制</el-button><el-button link @click="openAboutLink(repository.link_id)">浏览器打开</el-button></div></el-card>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.maintenance-page { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.page-heading, .card-header, .repository, .pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-heading h1 { margin: 2px 0 6px; }
.page-heading p, .task-card p, .hint { margin: 0; color: var(--el-text-color-secondary); }
.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }
.toolbar, .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.toolbar .el-input { width: min(360px, 100%); }
.toolbar .el-select { width: 140px; }
.pagination { padding-top: 12px; }
.document { max-height: 620px; overflow: auto; margin: 0; padding: 18px; border-radius: 8px; background: var(--el-fill-color-light); white-space: pre-wrap; line-height: 1.65; }
.repository { margin-top: 10px; }
.hint { padding-top: 8px; font-size: 12px; }
@media (max-width: 900px) { .page-heading, .repository { align-items: flex-start; flex-direction: column; } .pagination { align-items: flex-start; flex-direction: column; } }
</style>
