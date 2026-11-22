<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Back,
  Close,
  Delete,
  Download,
  FolderAdd,
  Refresh,
  RefreshRight,
  Upload,
} from '@element-plus/icons-vue'

import {
  cancelTerminalSftpTransfer,
  closeTerminalSftpSession,
  copyTerminalSftpEntry,
  createTerminalSftpDirectory,
  createTerminalSftpSession,
  deleteTerminalSftpEntries,
  listTerminalSftpEntries,
  listTerminalSftpTransfers,
  moveTerminalSftpEntry,
  renameTerminalSftpEntry,
  retryTerminalSftpTransfer,
  startTerminalSftpDownload,
  terminalSftpDownloadRequest,
  uploadTerminalSftpFile,
  type TerminalSftpEntry,
  type TerminalSftpSession,
  type TerminalSftpTransfer,
} from '../../api/terminal'
import { downloadBackendResource } from '../../platform/runtime'

const props = defineProps<{
  deviceUuid: string
  deviceName: string
}>()

const session = ref<TerminalSftpSession | null>(null)
const entries = ref<TerminalSftpEntry[]>([])
const transfers = ref<TerminalSftpTransfer[]>([])
const currentPath = ref('')
const search = ref('')
const selected = ref<string[]>([])
const connecting = ref(false)
const loading = ref(false)
const uploadInput = ref<HTMLInputElement | null>(null)
let pollTimer: number | null = null

const filteredEntries = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  return needle
    ? entries.value.filter((item) => item.name.toLocaleLowerCase().includes(needle))
    : entries.value
})

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

async function connect(): Promise<void> {
  if (!props.deviceUuid || connecting.value) return
  connecting.value = true
  try {
    session.value = await createTerminalSftpSession(props.deviceUuid)
    currentPath.value = session.value.root_path
    await Promise.all([refresh(), refreshTransfers()])
    startPolling()
  } catch (error) {
    ElMessage.error(message(error, 'SFTP 连接失败'))
  } finally {
    connecting.value = false
  }
}

async function disconnect(): Promise<void> {
  if (!session.value) return
  try {
    await closeTerminalSftpSession(session.value.session_id)
  } catch (error) {
    ElMessage.error(message(error, 'SFTP 断开失败'))
  } finally {
    stopPolling()
    session.value = null
    entries.value = []
    transfers.value = []
    selected.value = []
  }
}

async function refresh(path = currentPath.value): Promise<void> {
  if (!session.value) return
  loading.value = true
  try {
    const result = await listTerminalSftpEntries(session.value.session_id, path)
    session.value = result.session
    currentPath.value = result.path
    entries.value = result.items
    selected.value = []
  } catch (error) {
    ElMessage.error(message(error, '远程目录读取失败'))
  } finally {
    loading.value = false
  }
}

function parentPath(): string {
  const root = session.value?.root_path || '/'
  if (currentPath.value === root) return root
  const value = currentPath.value.replace(/\/$/, '')
  const separator = value.lastIndexOf('/')
  return separator <= 0 ? root : value.slice(0, separator)
}

function openEntry(entry: TerminalSftpEntry): void {
  if (entry.is_dir) void refresh(entry.remote_path)
}

function toggleSelection(entry: TerminalSftpEntry, checked: boolean): void {
  selected.value = checked
    ? [...new Set([...selected.value, entry.remote_path])]
    : selected.value.filter((value) => value !== entry.remote_path)
}

async function newDirectory(): Promise<void> {
  if (!session.value) return
  try {
    const { value } = await ElMessageBox.prompt('输入目录名称', '新建目录', {
      inputPattern: /^[^\\/:*?"<>|.][^\\/:*?"<>|]*$/,
      inputErrorMessage: '目录名称无效',
      confirmButtonText: '创建',
      cancelButtonText: '取消',
    })
    await createTerminalSftpDirectory(session.value.session_id, `${currentPath.value.replace(/\/$/, '')}/${value}`)
    await refresh()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, '目录创建失败'))
  }
}

async function renameSelected(): Promise<void> {
  if (!session.value || selected.value.length !== 1) return
  const source = selected.value[0]
  const currentName = source.split('/').pop() || source
  try {
    const { value } = await ElMessageBox.prompt('输入新名称', '重命名', {
      inputValue: currentName,
      confirmButtonText: '重命名',
      cancelButtonText: '取消',
    })
    const target = `${currentPath.value.replace(/\/$/, '')}/${value}`
    await renameTerminalSftpEntry(session.value.session_id, source, target)
    await refresh()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, '重命名失败'))
  }
}

async function copyOrMoveSelected(kind: 'copy' | 'move'): Promise<void> {
  if (!session.value || selected.value.length !== 1) return
  const source = selected.value[0]
  try {
    const { value } = await ElMessageBox.prompt('输入完整目标路径', kind === 'copy' ? '复制' : '移动', {
      inputValue: source,
      confirmButtonText: kind === 'copy' ? '复制' : '移动',
      cancelButtonText: '取消',
    })
    if (kind === 'copy') {
      await copyTerminalSftpEntry(session.value.session_id, source, value)
      await refreshTransfers()
      startPolling()
    } else {
      await moveTerminalSftpEntry(session.value.session_id, source, value)
      await refresh()
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, `${kind === 'copy' ? '复制' : '移动'}失败`))
  }
}

async function deleteSelected(): Promise<void> {
  if (!session.value || !selected.value.length) return
  try {
    await ElMessageBox.confirm(`删除选中的 ${selected.value.length} 个远程项目？目录将递归删除。`, '删除远程文件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await deleteTerminalSftpEntries(session.value.session_id, selected.value, true)
    await refresh()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, '删除失败'))
  }
}

async function downloadSelected(): Promise<void> {
  if (!session.value || !selected.value.length) return
  try {
    for (const path of selected.value) await startTerminalSftpDownload(session.value.session_id, path)
    await refreshTransfers()
    startPolling()
  } catch (error) {
    ElMessage.error(message(error, '下载任务创建失败'))
  }
}

async function uploadFiles(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const files = [...(input.files || [])]
  input.value = ''
  if (!session.value || !files.length) return
  try {
    for (const file of files) await uploadTerminalSftpFile(session.value.session_id, currentPath.value, file)
    await refreshTransfers()
    startPolling()
  } catch (error) {
    ElMessage.error(message(error, '上传任务创建失败'))
  }
}

async function refreshTransfers(): Promise<void> {
  if (!session.value) return
  try {
    transfers.value = (await listTerminalSftpTransfers(session.value.session_id)).items
    if (!transfers.value.some((item) => ['QUEUED', 'RUNNING'].includes(item.status))) stopPolling()
  } catch (error) {
    ElMessage.error(message(error, '传输队列读取失败'))
    stopPolling()
  }
}

function startPolling(): void {
  if (pollTimer !== null) return
  pollTimer = window.setInterval(() => void refreshTransfers(), 750)
}

function stopPolling(): void {
  if (pollTimer === null) return
  window.clearInterval(pollTimer)
  pollTimer = null
}

async function cancelTransfer(taskId: string): Promise<void> {
  await cancelTerminalSftpTransfer(taskId)
  await refreshTransfers()
}

async function retryTransfer(taskId: string): Promise<void> {
  await retryTerminalSftpTransfer(taskId)
  await refreshTransfers()
  startPolling()
}

async function saveDownload(task: TerminalSftpTransfer): Promise<void> {
  try {
    const result = await downloadBackendResource(terminalSftpDownloadRequest(task.task_id, task.result_name))
    ElMessage.success(result.status === 'saved' ? '文件已保存' : '浏览器已开始下载')
  } catch (error) {
    ElMessage.error(message(error, '文件保存失败'))
  }
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

watch(() => props.deviceUuid, () => void disconnect())
onBeforeUnmount(() => {
  stopPolling()
  void disconnect()
})
</script>

<template>
  <section class="sftp-panel">
    <header class="sftp-header">
      <strong>{{ deviceName || 'SFTP' }}</strong>
      <span v-if="session">{{ session.state }}</span>
      <el-button v-if="!session" type="primary" :loading="connecting" :disabled="!deviceUuid" @click="connect">连接 SFTP</el-button>
      <el-button v-else @click="disconnect"><el-icon><Close /></el-icon>断开</el-button>
    </header>

    <template v-if="session">
      <div class="sftp-toolbar">
        <el-button title="上级目录" :disabled="currentPath === session.root_path" @click="refresh(parentPath())"><el-icon><Back /></el-icon></el-button>
        <el-input v-model="currentPath" @keyup.enter="refresh()" />
        <el-button title="刷新" @click="refresh()"><el-icon><Refresh /></el-icon></el-button>
        <el-input v-model="search" placeholder="搜索" clearable class="sftp-search" />
      </div>
      <div class="sftp-actions">
        <el-button @click="uploadInput?.click()"><el-icon><Upload /></el-icon>上传</el-button>
        <input ref="uploadInput" class="sftp-file-input" type="file" multiple @change="uploadFiles" />
        <el-button @click="downloadSelected"><el-icon><Download /></el-icon>下载</el-button>
        <el-button @click="newDirectory"><el-icon><FolderAdd /></el-icon>新建目录</el-button>
        <el-button :disabled="selected.length !== 1" @click="renameSelected">重命名</el-button>
        <el-button :disabled="selected.length !== 1" @click="copyOrMoveSelected('copy')">复制</el-button>
        <el-button :disabled="selected.length !== 1" @click="copyOrMoveSelected('move')">移动</el-button>
        <el-button type="danger" :disabled="!selected.length" @click="deleteSelected"><el-icon><Delete /></el-icon>删除</el-button>
      </div>

      <el-table v-loading="loading" :data="filteredEntries" height="calc(100vh - 420px)" @row-dblclick="openEntry">
        <el-table-column width="42">
          <template #default="scope">
            <input type="checkbox" :checked="selected.includes(scope.row.remote_path)" @change="toggleSelection(scope.row, ($event.target as HTMLInputElement).checked)" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="230" />
        <el-table-column label="大小" width="100"><template #default="scope">{{ scope.row.is_dir ? '—' : formatBytes(scope.row.size || 0) }}</template></el-table-column>
        <el-table-column prop="permissions" label="权限" width="110" />
        <el-table-column prop="modified_time" label="修改时间" width="170" />
      </el-table>

      <section class="transfer-queue">
        <header><strong>传输队列</strong><el-button link @click="refreshTransfers"><el-icon><Refresh /></el-icon></el-button></header>
        <div v-for="task in transfers" :key="task.task_id" class="transfer-row">
          <span>{{ task.kind }}</span>
          <span class="transfer-name">{{ task.target }}</span>
          <el-progress :percentage="task.total_bytes ? Math.min(100, Math.round(task.transferred_bytes / task.total_bytes * 100)) : (task.status === 'COMPLETED' ? 100 : 0)" :status="task.status === 'FAILED' ? 'exception' : task.status === 'COMPLETED' ? 'success' : undefined" />
          <small>{{ formatBytes(task.bytes_per_second) }}/s · {{ task.status }}</small>
          <el-button v-if="['QUEUED', 'RUNNING'].includes(task.status)" link title="取消" @click="cancelTransfer(task.task_id)"><el-icon><Close /></el-icon></el-button>
          <el-button v-if="['FAILED', 'CANCELLED'].includes(task.status)" link title="重试" @click="retryTransfer(task.task_id)"><el-icon><RefreshRight /></el-icon></el-button>
          <el-button v-if="task.kind === 'DOWNLOAD' && task.status === 'COMPLETED'" link title="另存为" @click="saveDownload(task)"><el-icon><Download /></el-icon></el-button>
        </div>
        <span v-if="!transfers.length" class="transfer-empty">暂无传输任务</span>
      </section>
    </template>
    <div v-else class="sftp-empty">选择支持 SSH 的设备后建立独立 SFTP 会话。</div>
  </section>
</template>

<style scoped>
.sftp-panel { display: grid; gap: 10px; min-height: 0; }
.sftp-header, .sftp-toolbar, .sftp-actions, .transfer-queue header { display: flex; align-items: center; gap: 8px; }
.sftp-header span { color: var(--nc-success); font-size: 12px; }
.sftp-header .el-button:first-of-type { margin-left: auto; }
.sftp-toolbar .el-input { flex: 1; }
.sftp-toolbar .sftp-search { flex: 0 0 190px; }
.sftp-actions { flex-wrap: wrap; }
.sftp-file-input { display: none; }
.transfer-queue { min-height: 130px; border-top: 1px solid var(--nc-border); padding-top: 8px; }
.transfer-queue header { margin-bottom: 4px; }
.transfer-queue header .el-button { margin-left: auto; }
.transfer-row { display: grid; grid-template-columns: 70px minmax(120px, 1fr) minmax(140px, 220px) 130px 28px; align-items: center; gap: 8px; min-height: 32px; border-bottom: 1px solid var(--nc-border-subtle); font-size: 11px; }
.transfer-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.transfer-row small, .transfer-empty { color: var(--nc-text-secondary); }
.sftp-empty { display: grid; place-content: center; min-height: 340px; color: var(--nc-text-secondary); }
</style>
