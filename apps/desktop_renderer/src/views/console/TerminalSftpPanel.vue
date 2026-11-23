<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
  clearTerminalSftpTransfers,
  recordTerminalSftpSave,
  pauseTerminalSftpTransfer,
  closeTerminalSftpSession,
  copyTerminalSftpEntry,
  createTerminalSftpDirectory,
  createTerminalSftpSession,
  deleteTerminalSftpEntries,
  listTerminalSftpEntries,
  listTerminalSftpSessions,
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
import { downloadBackendResource, getPlatformAdapter } from '../../platform/runtime'

const props = defineProps<{
  deviceUuid: string
  deviceName: string
  workspaceId?: string
}>()
const emit = defineEmits<{ activity: [count: number] }>()
const queueOpen = ref(true)
const queueMode = ref('active')
const scopedTransfers = computed(() => transfers.value.filter(task => props.workspaceId ? task.session_id === session.value?.session_id : task.device_uuid === props.deviceUuid || (!task.device_uuid && task.session_id === session.value?.session_id)))
const queueTransfers = computed(() => scopedTransfers.value.filter(task => queueMode.value === 'history' ? ['COMPLETED', 'FAILED', 'CANCELLED', 'SKIPPED'].includes(task.status) : !['COMPLETED', 'CANCELLED', 'SKIPPED'].includes(task.status)))
const dragId = ref('')
const preparingDrag = ref(false)

const session = ref<TerminalSftpSession | null>(null)
const sessions = new Map<string, TerminalSftpSession>()
const entries = ref<TerminalSftpEntry[]>([])
const transfers = ref<TerminalSftpTransfer[]>([])
watch(scopedTransfers, items => emit('activity', items.filter(task => ['WAITING', 'RUNNING', 'PAUSED', 'READY'].includes(task.status)).length))
const currentPath = ref('')
const search = ref('')
const fileType = ref('all')
const showHidden = ref(false)
const pathInput = ref('')
const details = ref<TerminalSftpTransfer | null>(null)
const conflictVisible = ref(false)
const conflictPolicy = ref('rename')
const uploadSubmitting = ref(false)
let pendingUploads: File[] = []
const pendingUploadCount = ref(0)
const contextMenu = ref({ visible: false, x: 0, y: 0 })
const saving = ref(new Set<string>())
const selected = ref<string[]>([])
const connecting = ref(false)
const loading = ref(false)
const uploadInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
let pollTimer: number | null = null
let generation = 0
let polling = false
const stateLabel: Record<string, string> = { WAITING: '等待', QUEUED: '等待', RUNNING: '传输中', PAUSED: '已暂停', READY: '待保存', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消', SKIPPED: '已跳过' }
const breadcrumbs = computed(() => {
  const root = session.value?.root_path || '/'
  const tail = currentPath.value.slice(root.length).split('/').filter(Boolean)
  return [{ label: root, path: root }, ...tail.map((label, index) => ({ label, path: `${root.replace(/\/$/, '')}/${tail.slice(0, index + 1).join('/')}` }))]
})

const filteredEntries = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  return entries.value.filter(item => (showHidden.value || !item.name.startsWith('.')) &&
    (fileType.value === 'all' || (fileType.value === 'directory' ? item.is_dir : !item.is_dir)) &&
    item.name.toLocaleLowerCase().includes(needle))
})

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

async function connect(): Promise<void> {
  if (!props.deviceUuid || connecting.value) return
  connecting.value = true
  const deviceUuid = props.deviceUuid
  try {
    const connected = await createTerminalSftpSession(deviceUuid, props.workspaceId || '')
    sessions.set(deviceUuid, connected)
    if (props.deviceUuid === deviceUuid) {
      session.value = connected
      await refresh(connected.root_path)
    }
    await refreshTransfers()
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
    if (transfers.value.some(task => task.session_id === session.value?.session_id && ['WAITING', 'QUEUED', 'RUNNING'].includes(task.status))) {
      await ElMessageBox.confirm('断开将取消此 SFTP 会话的传输任务。', '断开 SFTP', { type: 'warning' })
    }
    await closeTerminalSftpSession(session.value.session_id)
    sessions.delete(session.value.device_uuid)
    session.value = null
    entries.value = []; selected.value = []
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, 'SFTP 断开失败'))
  }
}

async function refresh(path = pathInput.value): Promise<void> {
  if (!session.value) return
  const id = session.value.session_id
  const request = ++generation
  loading.value = true
  try {
    const result = await listTerminalSftpEntries(id, path)
    if (request !== generation || session.value?.session_id !== id) return
    session.value = result.session
    sessions.set(result.session.device_uuid, result.session)
    currentPath.value = pathInput.value = result.path
    entries.value = result.items
    selected.value = []
  } catch (error) {
    ElMessage.error(message(error, '远程目录读取失败'))
  } finally {
    if (request === generation) loading.value = false
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
    const recursive = entries.value.some(item => item.is_dir && selected.value.includes(item.remote_path))
    if (recursive) await ElMessageBox.confirm('目录及全部内容将被递归删除，无法撤销。', '再次确认递归删除', { type: 'warning', confirmButtonText: '递归删除' })
    await deleteTerminalSftpEntries(session.value.session_id, selected.value, recursive)
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
  chooseUploads(files)
}

function chooseUploads(files: File[]) {
  if (!session.value || !files.length || uploadSubmitting.value) return
  if (files.length > 10000 || files.reduce((sum, file) => sum + file.size, 0) > 64 * 1024 ** 3) {
    ElMessage.error('上传最多 10000 个文件、64 GiB'); return
  }
  pendingUploads = files
  pendingUploadCount.value = files.length
  conflictVisible.value = true
}

async function dropFiles(event: DragEvent) {
  if (!session.value || !event.dataTransfer) return
  const files: Array<{ file: File; relative: string }> = []
  let bytes = 0
  let entryCount = 0
  async function visit(entry: FileSystemEntry, relative: string, depth: number): Promise<void> {
    if (depth > 64 || ++entryCount > 10000) throw new Error('拖入目录超过限制')
    if (entry.name === '.' || entry.name === '..' || /[\\/:]/.test(entry.name)) throw new Error('文件路径无效')
    const path = relative ? `${relative}/${entry.name}` : entry.name
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => (entry as FileSystemFileEntry).file(resolve, reject))
      bytes += file.size
      if (bytes > 64 * 1024 ** 3) throw new Error('拖入文件超过 64 GiB')
      files.push({ file, relative: path })
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      while (true) {
        const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
        if (!entries.length) break
        for (const child of entries) await visit(child, path, depth + 1)
      }
    }
  }
  try {
    // Entry handles authorize content only; never derive or ask Main to read a path.
    const roots = [...event.dataTransfer.items].map(item => item.webkitGetAsEntry()).filter(Boolean) as FileSystemEntry[]
    if (roots.length) for (const entry of roots) await visit(entry, '', 0)
    else for (const file of event.dataTransfer.files) files.push({ file, relative: file.name })
    if (window.netconsoleDesktop?.validateDroppedFiles) await window.netconsoleDesktop.validateDroppedFiles(files.map(item => item.file))
    else if (roots.some(item => item.isDirectory)) throw new Error('文件夹拖入需要 Electron 本地路径校验')
    const id = session.value.session_id, directory = currentPath.value
    for (const { file, relative } of files) await uploadTerminalSftpFile(id, directory, file, false, relative, 'rename')
    await refreshTransfers()
    queueOpen.value = true
  } catch (error) { ElMessage.error(message(error, '拖入上传失败')) }
}

async function prepareDrag() {
  if (!session.value || !selected.value.length || preparingDrag.value) return
  preparingDrag.value = true
  dragId.value = ''
  const sessionId = session.value.session_id
  try {
    const adapter = getPlatformAdapter()
    if (!adapter.prepareSftpDrag) throw new Error('请在 Electron 中拖出文件')
    const requests = []
    for (const path of selected.value) {
      let task = await startTerminalSftpDownload(sessionId, path)
      while (['WAITING', 'RUNNING'].includes(task.status)) {
        await new Promise(done => setTimeout(done, 300))
        const items = (await listTerminalSftpTransfers(sessionId)).items
        const updated = items.find(item => item.task_id === task.task_id)
        if (!updated) throw new Error('拖出任务已不存在')
        task = updated
      }
      if (task.status !== 'READY') throw new Error(task.error_message || '远端文件下载失败')
      requests.push(terminalSftpDownloadRequest(task.task_id, task.result_name, task.result_size, task.result_sha256))
    }
    const prepared = await adapter.prepareSftpDrag(requests)
    if (session.value?.session_id === sessionId) dragId.value = prepared.dragId
    await refreshTransfers()
  } catch (error) { ElMessage.error(message(error, '准备拖出失败')) }
  finally { preparingDrag.value = false }
}
function startDrag(event: DragEvent) {
  event.preventDefault()
  if (dragId.value) getPlatformAdapter().startSftpDrag?.(dragId.value)
}
watch(selected, () => { dragId.value = '' })

function showFileMenu(row: TerminalSftpEntry, _column: unknown, event: MouseEvent) {
  event.preventDefault()
  if (!selected.value.includes(row.remote_path)) selected.value = [row.remote_path]
  contextMenu.value = { visible: true, x: Math.min(event.clientX, window.innerWidth - 160), y: Math.min(event.clientY, window.innerHeight - 270) }
}

async function submitUploads() {
  const files = pendingUploads
  if (!session.value || !files.length) return
  const id = session.value.session_id
  const directory = currentPath.value
  uploadSubmitting.value = true
  try {
    const policy = conflictPolicy.value
    for (const file of files) await uploadTerminalSftpFile(id, directory, file, policy === 'overwrite', file.webkitRelativePath || '', policy)
    await refreshTransfers()
    startPolling()
    conflictVisible.value = false
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(message(error, '上传任务创建失败'))
  } finally { pendingUploads = []; pendingUploadCount.value = 0; uploadSubmitting.value = false }
}

async function refreshTransfers(): Promise<void> {
  if (polling) return
  polling = true
  try {
    transfers.value = (await listTerminalSftpTransfers()).items
  } catch (error) {
    // Keep retrying after a temporary Backend interruption.
  } finally { polling = false }
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
  try { await cancelTerminalSftpTransfer(taskId); await refreshTransfers() }
  catch (error) { ElMessage.error(message(error, '取消失败')) }
}

async function pauseTransfer(taskId: string) {
  try { await pauseTerminalSftpTransfer(taskId); await refreshTransfers() }
  catch (error) { ElMessage.error(message(error, '暂停失败')) }
}

async function retryTransfer(taskId: string): Promise<void> {
  try { await retryTerminalSftpTransfer(taskId); await refreshTransfers(); startPolling() }
  catch (error) { ElMessage.error(message(error, '重试失败')) }
}

async function saveDownload(task: TerminalSftpTransfer): Promise<void> {
  if (saving.value.has(task.task_id)) return
  saving.value.add(task.task_id)
  try {
    const result = await downloadBackendResource(terminalSftpDownloadRequest(task.task_id, task.result_name, task.result_size, task.result_sha256))
    if (result.status === 'cancelled') return
    if (result.status === 'started') { ElMessage.info('浏览器已开始下载，本地保存尚未验证'); return }
    if (result.status !== 'saved' || result.sizeBytes !== task.result_size || result.sha256 !== task.result_sha256) throw new Error(result.error || '本地文件完整性校验失败')
    await recordTerminalSftpSave(task, true)
    ElMessage.success('文件已保存并校验')
  } catch (error) {
    await recordTerminalSftpSave(task, false).catch(() => undefined)
    ElMessage.error(message(error, '文件保存失败'))
  } finally { saving.value.delete(task.task_id); await refreshTransfers() }
}

async function clearCompleted() { await clearTerminalSftpTransfers(props.deviceUuid); await refreshTransfers() }
async function exportLog() {
  try {
    const result = await downloadBackendResource({ apiPath: '/api/terminal/sftp/transfer-log', suggestedName: 'sftp-transfer-log.jsonl' })
    if (result.status === 'failed') throw new Error(result.error || '日志保存失败')
    if (result.status === 'saved') ElMessage.success('传输日志已保存')
  } catch (error) { ElMessage.error(message(error, '日志保存失败')) }
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  const units = ['B', 'KiB', 'MiB', 'GiB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`
}

watch(() => props.deviceUuid, () => {
  generation++; entries.value = []; selected.value = []; loading.value = false
  session.value = sessions.get(props.deviceUuid) || null
  if (session.value) void refresh(session.value.current_path)
})
onMounted(async () => {
  startPolling()
  try {
    for (const existing of (await listTerminalSftpSessions()).items.filter(item => (item.workspace_id || '') === (props.workspaceId || ''))) sessions.set(existing.device_uuid, existing)
    session.value = sessions.get(props.deviceUuid) || null
    if (session.value) await refresh(session.value.current_path)
    await refreshTransfers()
  } catch (error) { ElMessage.error(message(error, 'SFTP 状态读取失败')) }
})
onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="sftp-panel" @click="contextMenu.visible = false" @keydown.esc="contextMenu.visible = false">
    <header class="sftp-header">
      <strong>{{ deviceName || 'SFTP' }}</strong>
      <span v-if="session">{{ session.state }}</span>
      <el-button v-if="!session" type="primary" :loading="connecting" :disabled="!deviceUuid" @click="connect">连接 SFTP</el-button>
      <el-button v-else @click="disconnect"><el-icon><Close /></el-icon>断开</el-button>
    </header>

    <template v-if="session">
      <nav class="sftp-breadcrumb"><button v-for="crumb in breadcrumbs" :key="crumb.path" @click="refresh(crumb.path)">{{ crumb.label }}</button></nav>
      <div class="sftp-toolbar">
        <el-button title="上级目录" :disabled="currentPath === session.root_path" @click="refresh(parentPath())"><el-icon><Back /></el-icon></el-button>
        <el-input v-model="pathInput" aria-label="远程路径" @keyup.enter="refresh()" />
        <el-button title="刷新" @click="refresh()"><el-icon><Refresh /></el-icon></el-button>
      </div>
      <div class="sftp-actions">
        <el-button @click="uploadInput?.click()"><el-icon><Upload /></el-icon>上传</el-button>
        <input ref="uploadInput" class="sftp-file-input" type="file" multiple @change="uploadFiles" />
        <el-button @click="folderInput?.click()">上传文件夹</el-button>
        <input ref="folderInput" class="sftp-file-input" type="file" multiple webkitdirectory @change="uploadFiles" />
        <el-button @click="downloadSelected"><el-icon><Download /></el-icon>下载</el-button>
        <el-button :loading="preparingDrag" :disabled="!selected.length" @click="prepareDrag">准备拖出</el-button>
        <button v-if="dragId" draggable="true" class="native-drag" title="拖至资源管理器；目录以 ZIP 传出" @dragstart="startDrag">拖到桌面 / 文件夹</button>
        <el-button @click="newDirectory"><el-icon><FolderAdd /></el-icon>新建目录</el-button>
        <el-button :disabled="selected.length !== 1" @click="renameSelected">重命名</el-button>
        <el-button :disabled="selected.length !== 1" @click="copyOrMoveSelected('copy')">复制</el-button>
        <el-button :disabled="selected.length !== 1" @click="copyOrMoveSelected('move')">移动</el-button>
        <el-button type="danger" :disabled="!selected.length" @click="deleteSelected"><el-icon><Delete /></el-icon>删除</el-button>
      </div>

      <div class="sftp-toolbar"><el-input v-model="search" placeholder="文件名搜索" clearable /><select v-model="fileType" aria-label="文件类型"><option value="all">全部</option><option value="directory">目录</option><option value="file">文件</option></select><label><input v-model="showHidden" type="checkbox" />隐藏文件</label></div>
      <el-table v-loading="loading" :data="filteredEntries" height="100%" class="sftp-files" empty-text="目录为空或无匹配项目" @dragover.prevent @drop.prevent="dropFiles" @row-dblclick="openEntry" @row-contextmenu="showFileMenu">
        <el-table-column width="42">
          <template #default="scope">
            <input type="checkbox" :checked="selected.includes(scope.row.remote_path)" @change="toggleSelection(scope.row, ($event.target as HTMLInputElement).checked)" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" sortable min-width="160"><template #default="scope"><span :draggable="Boolean(dragId) && selected.includes(scope.row.remote_path)" @dragstart="startDrag">{{ scope.row.is_dir ? '📁' : '·' }} {{ scope.row.name }}</span></template></el-table-column>
        <el-table-column prop="size" label="大小" sortable width="100"><template #default="scope">{{ scope.row.is_dir ? '—' : formatBytes(scope.row.size || 0) }}</template></el-table-column>
        <el-table-column prop="permissions" label="权限" width="110" />
        <el-table-column prop="modified_time" label="修改时间" sortable width="170" />
      </el-table>

      <small class="sftp-capability">{{ filteredEntries.length }} 项 · 权限修改 / 上传续传不可用</small>
    </template>
    <div v-else class="sftp-empty">选择支持 SSH 的设备后建立独立 SFTP 会话。</div>
    <div v-if="contextMenu.visible" class="sftp-context-menu" :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }" role="menu">
      <button @click="downloadSelected">下载选中</button><button @click="uploadInput?.click()">上传文件</button><button @click="newDirectory">新建目录</button><button :disabled="selected.length !== 1" @click="renameSelected">重命名</button><button :disabled="selected.length !== 1" @click="copyOrMoveSelected('copy')">复制</button><button :disabled="selected.length !== 1" @click="copyOrMoveSelected('move')">移动</button><button @click="refresh()">刷新</button><button @click="deleteSelected">删除选中</button>
    </div>
      <section v-if="session || scopedTransfers.length" class="transfer-queue" :class="{ collapsed: !queueOpen }">
        <header><button @click="queueOpen = !queueOpen">{{ queueOpen ? '▾' : '▸' }} 传输 · {{ scopedTransfers.length }}</button><el-button link @click="queueMode = queueMode === 'active' ? 'history' : 'active'">{{ queueMode === 'active' ? '历史' : '队列' }}</el-button><el-button link @click="clearCompleted">清除</el-button><el-button link @click="exportLog">日志</el-button></header>
        <div v-show="queueOpen" class="transfer-list">
        <div v-for="task in queueTransfers" :key="task.task_id" class="transfer-row">
          <span>{{ task.kind }}</span>
          <button class="transfer-name" :title="task.target" @click="details = task">{{ task.result_name || task.target.split('/').pop() }}</button>
          <el-progress :percentage="task.total_bytes ? Math.min(100, Math.round(task.transferred_bytes / task.total_bytes * 100)) : (task.status === 'COMPLETED' ? 100 : 0)" :status="task.status === 'FAILED' ? 'exception' : task.status === 'COMPLETED' ? 'success' : undefined" />
          <small>{{ formatBytes(task.transferred_bytes) }} / {{ formatBytes(task.total_bytes) }} · {{ formatBytes(task.bytes_per_second) }}/s · {{ task.remaining_seconds == null ? '—' : `${task.remaining_seconds}s` }} · {{ stateLabel[task.status] || task.status }}</small>
          <el-button v-if="['WAITING', 'QUEUED', 'RUNNING', 'READY', 'PAUSED'].includes(task.status)" link title="取消" @click="cancelTransfer(task.task_id)"><el-icon><Close /></el-icon></el-button>
          <el-button v-if="task.status === 'RUNNING' && task.resumable" link title="暂停" @click="pauseTransfer(task.task_id)">暂停</el-button>
          <el-button v-if="['FAILED', 'CANCELLED', 'PAUSED'].includes(task.status) && !task.result_name && !(task.kind === 'UPLOAD' && task.status === 'CANCELLED')" link title="重试" @click="retryTransfer(task.task_id)">{{ task.resumable ? '继续' : '重试' }}</el-button>
          <el-button v-if="task.kind === 'DOWNLOAD' && task.result_name" :loading="saving.has(task.task_id)" link title="保存" @click="saveDownload(task)">{{ task.status === 'COMPLETED' ? '另存为' : '保存' }}</el-button>
        </div>
        <span v-if="!queueTransfers.length" class="transfer-empty">暂无传输任务</span>
        </div>
      </section>
  </section>
  <el-dialog :model-value="Boolean(details)" title="传输详情" width="min(620px, 90vw)" @update:model-value="!$event && (details = null)"><template v-if="details"><p>{{ details.source }} → {{ details.target }}</p><p>{{ stateLabel[details.status] }} · {{ details.error_code }}</p><p>{{ details.error_message }}</p><p v-if="details.result_sha256">SHA-256: {{ details.result_sha256 }}</p></template></el-dialog>
  <el-dialog v-model="conflictVisible" title="上传文件" width="420px" :close-on-click-modal="!uploadSubmitting" @closed="pendingUploads = []; pendingUploadCount = 0">
    <p>{{ pendingUploadCount }} 个文件</p><el-radio-group v-model="conflictPolicy" class="conflict-options"><el-radio value="rename">同名文件保留副本</el-radio><el-radio value="skip">跳过同名文件</el-radio><el-radio value="overwrite">覆盖同名文件</el-radio><el-radio value="error">遇到冲突停止</el-radio></el-radio-group>
    <template #footer><el-button :disabled="uploadSubmitting" @click="conflictVisible = false">取消</el-button><el-button type="primary" :loading="uploadSubmitting" @click="submitUploads">上传</el-button></template>
  </el-dialog>
</template>

<style scoped>
.sftp-panel { display: flex; flex-direction: column; gap: 8px; min-height: 0; height: 100%; padding: 10px; overflow: hidden; background: var(--nc-bg-panel); }
.sftp-files { flex: 1; min-height: 120px; width: 100%; }
.sftp-breadcrumb { display: flex; flex-wrap: wrap; gap: 3px; }
.sftp-breadcrumb button { border: 0; background: transparent; color: var(--nc-primary); cursor: pointer; }
.sftp-toolbar { flex-wrap: wrap; }
.sftp-toolbar label { white-space: nowrap; font-size: 11px; }
.sftp-header strong { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.sftp-capability { color: var(--nc-text-secondary); font-size: 10px; }
.conflict-options { display: flex; flex-direction: column; align-items: flex-start; }
.sftp-context-menu { position: fixed; z-index: 2500; width: 150px; padding: 5px; display: grid; border: 1px solid var(--nc-border); background: var(--nc-bg-panel); box-shadow: var(--nc-shadow-floating); border-radius: 5px; }
.sftp-context-menu button { text-align: left; padding: 6px 10px; border: 0; background: transparent; color: inherit; cursor: pointer; }
.sftp-context-menu button:hover { background: var(--nc-bg-muted); }
.sftp-header, .sftp-toolbar, .sftp-actions, .transfer-queue header { display: flex; align-items: center; gap: 8px; }
.sftp-header span { color: var(--nc-success); font-size: 12px; }
.sftp-header .el-button:first-of-type { margin-left: auto; }
.sftp-toolbar .el-input { flex: 1; }
.sftp-toolbar .sftp-search { flex: 0 0 190px; }
.sftp-actions { flex-wrap: wrap; }
.sftp-file-input { display: none; }
.transfer-queue { flex: 0 0 auto; display: flex; flex-direction: column; max-height: 220px; border-top: 1px solid var(--nc-border); padding: 8px 0; background: var(--nc-bg-panel); }
.transfer-queue.collapsed { max-height: 40px; }
.transfer-queue header { flex-wrap: wrap; }
.transfer-queue header button { border: 0; background: transparent; color: inherit; cursor: pointer; }
.transfer-list { flex: 1; overflow: auto; }
.transfer-queue header { margin-bottom: 4px; }
.transfer-queue header strong { flex: 1; }
.transfer-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 6px 0; border-bottom: 1px solid var(--nc-border-subtle); font-size: 11px; }
.transfer-row .el-progress { flex: 1; min-width: 80px; }
.transfer-row small { flex-basis: 100%; }
.transfer-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.transfer-row small, .transfer-empty { color: var(--nc-text-secondary); }
.sftp-empty { display: grid; place-content: center; min-height: 340px; color: var(--nc-text-secondary); }
</style>
