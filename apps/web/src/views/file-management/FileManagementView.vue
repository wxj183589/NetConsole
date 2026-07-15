<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fileDownloadRequest, getFileDownloadTask, getFileManagementStatus, listManagedFiles, startFileDownload } from '../../api/fileManagement'
import { isFeatureEnabled } from '../../features'
import { downloadBackendResource } from '../../platform/runtime'
import type { FileDownloadTask, ManagedFile, ManagedFileCategory } from '../../types/fileManagement'

const storageKey = 'netconsole.file-management.download-tasks'
const siteId = ref('')
const category = ref<ManagedFileCategory>('')
const search = ref('')
const loading = ref(false)
const error = ref('')
const files = ref<ManagedFile[]>([])
const total = ref(0)
const localAvailable = ref(true)
const deviceFilesMessage = ref('')
const tasks = ref<FileDownloadTask[]>([])
const filter = reactive({ site_id: '', category: '' as ManagedFileCategory, search: '' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const activeTasks = computed(() => tasks.value.filter((task) => ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(task.status)))

onMounted(async () => {
  restoreTasks()
  await refresh()
  await recoverTasks()
  scheduleTaskRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
})

async function refresh(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = ''
  filter.site_id = siteId.value.trim()
  filter.category = category.value
  filter.search = search.value.trim()
  try {
    const [status, page] = await Promise.all([
      getFileManagementStatus(filter.site_id),
      listManagedFiles({ site_id: filter.site_id, category: filter.category, search: filter.search, limit: 500 }),
    ])
    siteId.value = status.site_id
    localAvailable.value = status.local_files.available
    deviceFilesMessage.value = status.device_files.message
    files.value = page.items
    total.value = page.total
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文件列表加载失败'
  } finally {
    loading.value = false
  }
}

async function download(file: ManagedFile): Promise<void> {
  try {
    const task = await startFileDownload(file.file_ref, siteId.value)
    upsertTask(task)
    persistTasks()
    scheduleTaskRefresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文件下载任务创建失败'
  }
}

async function saveDownload(task: FileDownloadTask): Promise<void> {
  if (!task.result) return
  error.value = ''
  try {
    const result = await downloadBackendResource(
      fileDownloadRequest(task.task_id, task.site_id, task.result.name),
    )
    if (result.status === 'failed') error.value = result.error || '文件下载失败'
    else if (result.status === 'saved') ElMessage.success('文件已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
  } catch {
    error.value = '文件下载失败'
  }
}

async function recoverTasks(): Promise<void> {
  await Promise.all(tasks.value.map(async (task) => {
    try { upsertTask(await getFileDownloadTask(task.task_id, siteId.value)) } catch { /* 任务已过期时保留本地历史 */ }
  }))
  persistTasks()
}

async function refreshTasks(): Promise<void> {
  await Promise.all(activeTasks.value.map(async (task) => {
    try { upsertTask(await getFileDownloadTask(task.task_id, siteId.value)) } catch { /* 任务状态可从 Job Center 恢复 */ }
  }))
  persistTasks()
  scheduleTaskRefresh()
}

function scheduleTaskRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (!activeTasks.value.length) return
  refreshTimer = setTimeout(() => void refreshTasks(), 1_500)
}

function upsertTask(task: FileDownloadTask): void {
  const index = tasks.value.findIndex((item) => item.task_id === task.task_id)
  if (index < 0) tasks.value.unshift(task)
  else tasks.value[index] = task
  tasks.value = tasks.value.slice(0, 20)
}

function restoreTasks(): void {
  try {
    const values = JSON.parse(localStorage.getItem(storageKey) || '[]') as unknown
    if (Array.isArray(values)) tasks.value = values.filter((value): value is FileDownloadTask => Boolean(value && typeof value === 'object' && 'task_id' in value))
  } catch { tasks.value = [] }
}

function persistTasks(): void {
  localStorage.setItem(storageKey, JSON.stringify(tasks.value.map((task) => ({ task_id: task.task_id, site_id: task.site_id, status: task.status, progress: task.progress, stage: task.stage, message: task.message, result: task.result }))))
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function taskType(status: FileDownloadTask['status']): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'CANCELLED') return 'warning'
  return 'info'
}
</script>

<template>
  <section class="file-management-page">
    <header class="page-heading">
      <div><p class="eyebrow">LOCAL FILES / READ ONLY</p><h1>文件管理</h1><p>按局点查看本地 Session、Raw、采集包和报告 Artifact；不上传、不删除、不重命名。</p></div>
      <el-button :loading="loading" @click="refresh">刷新</el-button>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="deviceFilesMessage" :title="deviceFilesMessage" type="info" :closable="false" show-icon />
    <el-alert v-if="!localAvailable" title="当前局点暂无本地文件目录" type="info" :closable="false" show-icon />

    <div class="content-card" v-loading="loading">
      <div class="toolbar">
        <el-input v-model="siteId" clearable placeholder="局点（留空为当前）" @keyup.enter="refresh" />
        <el-select v-model="category" clearable placeholder="文件分类" @change="refresh">
          <el-option label="全部" value="" /><el-option label="Session" value="session" /><el-option label="Raw" value="raw" /><el-option label="ZIP / 采集包" value="package" /><el-option label="报告 / Artifact" value="artifact" />
        </el-select>
        <el-input v-model="search" clearable placeholder="搜索文件名或相对路径" @keyup.enter="refresh" />
        <el-button type="primary" @click="refresh">查询</el-button>
      </div>
      <el-table :data="files" border stripe height="460" empty-text="暂无符合条件的本地文件">
        <el-table-column prop="name" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column prop="relative_path" label="相对路径" min-width="320" show-overflow-tooltip />
        <el-table-column label="大小" width="110"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
        <el-table-column prop="modified_at" label="修改时间" width="180" />
        <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" :disabled="!row.downloadable || !isFeatureEnabled('web.file_management_download')" @click="download(row)">下载</el-button></template></el-table-column>
      </el-table>
      <p class="result-count">共 {{ total }} 个文件；当前只返回受控 ref，不返回本机绝对路径。</p>
    </div>

    <div class="content-card">
      <div class="section-heading"><h2>下载任务</h2><span>页面重载后会按任务 ID 恢复状态</span></div>
      <el-table :data="tasks" border empty-text="暂无下载任务">
        <el-table-column prop="task_id" label="任务 ID" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="taskType(row.status)">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="进度" width="180"><template #default="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'FAILED' ? 'exception' : row.status === 'COMPLETED' ? 'success' : undefined" /></template></el-table-column>
        <el-table-column prop="message" label="信息" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="row.status === 'COMPLETED' && row.result" link type="primary" @click="saveDownload(row)">下载文件</el-button></template></el-table-column>
      </el-table>
    </div>
  </section>
</template>

<style scoped>
.file-management-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.toolbar,.section-heading{display:flex;align-items:center;gap:12px}.page-heading,.section-heading{justify-content:space-between}.page-heading h1,.section-heading h2{margin:2px 0 6px}.page-heading p,.section-heading span,.result-count{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.content-card{padding:14px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;overflow:hidden}.toolbar{flex-wrap:wrap;margin-bottom:12px}.toolbar .el-input{width:240px}.toolbar .el-select{width:150px}.result-count{padding-top:12px;font-size:12px}.section-heading{margin-bottom:12px}.section-heading h2{margin:0}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.toolbar .el-input,.toolbar .el-select{width:100%}}
</style>
