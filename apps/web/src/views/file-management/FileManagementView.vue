<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import {
  cancelFileDownload,
  connectDeviceFiles,
  disconnectDeviceFiles,
  fileDownloadUrl,
  getFileDownloadTask,
  getFileManagementStatus,
  listFileDownloads,
  listManagedFiles,
  listRemoteFiles,
  requestOpenResultDirectory,
  requestWinScp,
  startFileDownload,
  startRemoteFileDownload,
} from '../../api/fileManagement'
import { listDevices } from '../../api/deviceManagement'
import { isFeatureEnabled } from '../../features'
import type { DeviceListItem } from '../../types/deviceManagement'
import type { FileConnection, FileDownloadTask, ManagedFile, ManagedFileCategory, RemoteFileEntry, RemoteFilePage } from '../../types/fileManagement'

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
const devices = ref<DeviceListItem[]>([])
const selectedDeviceId = ref('')
const connection = ref<FileConnection | null>(null)
const remotePage = ref<RemoteFilePage | null>(null)
const remoteSelected = ref<RemoteFileEntry[]>([])
const remoteMeshOnly = ref(false)
const remoteLoading = ref(false)
const remoteError = ref('')
const filter = reactive({ site_id: '', category: '' as ManagedFileCategory, search: '' })
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const activeTasks = computed(() => tasks.value.filter((task) => ['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(task.status)))
const remoteItems = computed(() => {
  const items = remotePage.value?.items || []
  if (!remoteMeshOnly.value) return items
  return items.filter((item) => !item.is_dir && /meshlog\.log(?:\.gz)?$/i.test(item.name))
})

onMounted(async () => {
  restoreTasks()
  await refresh()
  await recoverTasks()
  scheduleTaskRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer) clearTimeout(refreshTimer)
  refreshTimer = null
  const connectionId = connection.value?.connection_id
  if (connectionId) void disconnectDeviceFiles(connectionId, siteId.value).catch(() => undefined)
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
    try { devices.value = (await listDevices({ page: 1, page_size: 200 })).items } catch { devices.value = [] }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文件列表加载失败'
  } finally {
    loading.value = false
  }
}

async function download(file: ManagedFile): Promise<void> {
  try {
    upsertTask(await startFileDownload(file.file_ref, siteId.value))
    persistTasks()
    scheduleTaskRefresh()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '文件下载任务创建失败'
  }
}

async function connectDevice(): Promise<void> {
  if (!selectedDeviceId.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    if (connection.value) await disconnectDeviceFiles(connection.value.connection_id, siteId.value)
    connection.value = await connectDeviceFiles(selectedDeviceId.value, siteId.value)
    await loadRemotePage(connection.value.root_entry_id)
  } catch (reason) {
    remoteError.value = reason instanceof Error ? reason.message : '设备文件连接失败'
    connection.value = null
    remotePage.value = null
  } finally {
    remoteLoading.value = false
  }
}

async function disconnectDevice(): Promise<void> {
  if (!connection.value) return
  try { await disconnectDeviceFiles(connection.value.connection_id, siteId.value) } catch { /* 会话已由服务端清理时仍清空页面状态 */ }
  connection.value = null
  remotePage.value = null
  remoteSelected.value = []
}

async function loadRemotePage(entryId = ''): Promise<void> {
  if (!connection.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    remotePage.value = await listRemoteFiles(connection.value.connection_id, entryId, siteId.value)
    remoteSelected.value = []
  } catch (reason) {
    remoteError.value = reason instanceof Error ? reason.message : '远程目录读取失败'
  } finally {
    remoteLoading.value = false
  }
}

function selectRemote(rows: RemoteFileEntry[]): void {
  remoteSelected.value = rows.filter((row) => !row.is_dir && row.downloadable)
}

function isRemoteSelectable(row: RemoteFileEntry): boolean {
  return row.downloadable
}

function openRemoteRow(row: RemoteFileEntry): void {
  if (row.is_dir) void loadRemotePage(row.entry_id)
}

function selectMeshLogs(): void {
  remoteMeshOnly.value = !remoteMeshOnly.value
  remoteSelected.value = remoteMeshOnly.value ? remoteItems.value.filter((row) => !row.is_dir && row.downloadable) : []
}

async function downloadRemote(): Promise<void> {
  if (!connection.value || !remoteSelected.value.length) return
  try {
    for (const row of remoteSelected.value) upsertTask(await startRemoteFileDownload(connection.value.connection_id, row.entry_id, siteId.value))
    persistTasks()
    scheduleTaskRefresh()
  } catch (reason) {
    remoteError.value = reason instanceof Error ? reason.message : '远程下载任务创建失败'
  }
}

async function recoverTasks(): Promise<void> {
  try { (await listFileDownloads(siteId.value)).forEach(upsertTask) } catch { /* 本地历史仍可用于展示 */ }
  await Promise.all(tasks.value.map(async (task) => {
    try { upsertTask(await getFileDownloadTask(task.task_id, siteId.value)) } catch { /* 任务已过期时保留本地历史 */ }
  }))
  persistTasks()
}

async function refreshTasks(): Promise<void> {
  try { (await listFileDownloads(siteId.value)).forEach(upsertTask) } catch {
    await Promise.all(activeTasks.value.map(async (task) => {
      try { upsertTask(await getFileDownloadTask(task.task_id, siteId.value)) } catch { /* 任务状态仍可在 Job Center 查询 */ }
    }))
  }
  persistTasks()
  scheduleTaskRefresh()
}

function scheduleTaskRefresh(): void {
  if (refreshTimer) clearTimeout(refreshTimer)
  if (!activeTasks.value.length) return
  refreshTimer = setTimeout(() => void refreshTasks(), 1_500)
}

async function cancelTask(task: FileDownloadTask): Promise<void> {
  try { upsertTask(await cancelFileDownload(task.task_id, siteId.value)); persistTasks(); scheduleTaskRefresh() } catch (reason) { error.value = reason instanceof Error ? reason.message : '下载任务取消失败' }
}

async function openResultDirectory(task: FileDownloadTask): Promise<void> {
  if (!task.result?.artifact_id) return
  try { error.value = (await requestOpenResultDirectory(task.result.artifact_id)).message } catch (reason) { error.value = reason instanceof Error ? reason.message : '结果目录动作不可用' }
}

async function openWinScp(): Promise<void> {
  if (!selectedDeviceId.value) return
  try { error.value = (await requestWinScp(selectedDeviceId.value, siteId.value)).message } catch (reason) { error.value = reason instanceof Error ? reason.message : 'WinSCP 动作不可用' }
}

function upsertTask(task: FileDownloadTask): void {
  const index = tasks.value.findIndex((item) => item.task_id === task.task_id)
  if (index < 0) tasks.value.unshift(task)
  else tasks.value[index] = task
  tasks.value = tasks.value.slice(0, 50)
}

function restoreTasks(): void {
  try {
    const values = JSON.parse(localStorage.getItem(storageKey) || '[]') as unknown
    if (Array.isArray(values)) tasks.value = values.filter((value): value is FileDownloadTask => Boolean(value && typeof value === 'object' && 'task_id' in value))
  } catch { tasks.value = [] }
}

function persistTasks(): void {
  localStorage.setItem(storageKey, JSON.stringify(tasks.value))
}

function formatBytes(value: number | null): string {
  if (value === null || value === undefined) return '-'
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
      <div><p class="eyebrow">CONTROLLED FILES / TRANSFER QUEUE</p><h1>文件管理</h1><p>按局点浏览本地文件与受控设备目录；只允许下载，不上传、不删除、不重命名。</p></div>
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

    <div class="content-card remote-card">
      <div class="section-heading"><h2>设备文件</h2><span>{{ connection ? `${connection.device_name} · ${remotePage?.current_label || '根目录'}` : '未连接' }}</span></div>
      <el-alert v-if="remoteError" :title="remoteError" type="error" :closable="false" show-icon />
      <div class="toolbar">
        <el-select v-model="selectedDeviceId" clearable placeholder="选择设备">
          <el-option v-for="device in devices" :key="device.device_uuid" :label="`${device.name} · ${device.primary_address}`" :value="device.device_uuid" />
        </el-select>
        <el-button type="primary" :loading="remoteLoading" :disabled="!selectedDeviceId" @click="connectDevice">连接设备</el-button>
        <el-button :disabled="!connection" @click="disconnectDevice">断开</el-button>
        <el-button :disabled="!selectedDeviceId" @click="openWinScp">WinSCP</el-button>
        <el-button :disabled="!connection" @click="loadRemotePage(remotePage?.current_entry_id)">刷新</el-button>
        <el-button :disabled="!connection || !remotePage || remotePage.current_entry_id === connection.root_entry_id" @click="loadRemotePage(remotePage?.parent_entry_id)">上级</el-button>
        <el-button :type="remoteMeshOnly ? 'primary' : 'default'" :disabled="!connection" @click="selectMeshLogs">Mesh 日志</el-button>
        <el-button type="primary" :disabled="!connection || !remoteSelected.length || !isFeatureEnabled('web.file_management_download')" @click="downloadRemote">下载选中</el-button>
      </div>
      <el-table :data="remoteItems" border stripe height="360" row-key="entry_id" empty-text="暂无远程文件或尚未连接" @selection-change="selectRemote" @row-dblclick="openRemoteRow">
        <el-table-column type="selection" width="48" :selectable="isRemoteSelectable" />
        <el-table-column prop="name" label="名称" min-width="240" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="110" />
        <el-table-column label="大小" width="110"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
        <el-table-column prop="modified_at" label="修改时间" width="180" />
      </el-table>
      <p class="result-count">远程 entry 仅在服务端会话内有效，浏览器不提交远程路径。</p>
    </div>

    <div class="content-card">
      <div class="section-heading"><h2>下载任务</h2><span>页面重载后会按任务 ID 恢复状态</span></div>
      <el-table :data="tasks" border empty-text="暂无下载任务">
        <el-table-column prop="task_id" label="任务 ID" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="taskType(row.status)">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="进度" width="180"><template #default="{ row }"><el-progress :percentage="row.progress" :status="row.status === 'FAILED' ? 'exception' : row.status === 'COMPLETED' ? 'success' : undefined" /></template></el-table-column>
        <el-table-column prop="message" label="信息" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="180"><template #default="{ row }"><a v-if="row.status === 'COMPLETED'" :href="fileDownloadUrl(row.task_id, row.site_id)">下载文件</a><el-button v-if="['PENDING', 'STARTING', 'RUNNING', 'STOPPING'].includes(row.status)" link type="warning" @click="cancelTask(row)">取消</el-button><el-button v-if="row.status === 'COMPLETED' && row.result?.artifact_id" link @click="openResultDirectory(row)">结果目录</el-button></template></el-table-column>
      </el-table>
    </div>
  </section>
</template>

<style scoped>
.file-management-page{display:flex;flex-direction:column;gap:16px;min-width:0}.page-heading,.toolbar,.section-heading{display:flex;align-items:center;gap:12px}.page-heading,.section-heading{justify-content:space-between}.page-heading h1,.section-heading h2{margin:2px 0 6px}.page-heading p,.section-heading span,.result-count{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.content-card{padding:14px 16px;background:var(--el-bg-color);border:1px solid var(--el-border-color-lighter);border-radius:12px;overflow:hidden}.toolbar{flex-wrap:wrap;margin-bottom:12px}.toolbar .el-input{width:240px}.toolbar .el-select{width:150px}.result-count{padding-top:12px;font-size:12px}.section-heading{margin-bottom:12px}.section-heading h2{margin:0}@media(max-width:900px){.page-heading{align-items:flex-start;flex-direction:column}.toolbar .el-input,.toolbar .el-select{width:100%}}
</style>
