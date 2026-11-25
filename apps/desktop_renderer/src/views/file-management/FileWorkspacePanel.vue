<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { browseFileWorkspace, cancelFileWorkspaceTask, listFileWorkspaceTasks, operateFileWorkspace, uploadFileWorkspace, workspaceFileRequest, type FileRoot, type WorkspaceDirectory, type WorkspaceEntry, type WorkspaceFileTask } from '../../api/fileWorkspace'
import { downloadBackendResource } from '../../platform/runtime'
import { isFeatureEnabled } from '../../features'
import { createFileManagerTranslator } from './fileManagementI18n'

const t = createFileManagerTranslator()
const left = ref<WorkspaceDirectory>()
const right = ref<WorkspaceDirectory>()
const roots = ref<[FileRoot, FileRoot]>(['downloads', 'http'])
const selected = ref<[WorkspaceEntry | null, WorkspaceEntry | null]>([null, null])
const busy = ref<[boolean, boolean]>([false, false])
const errors = ref<[string, string]>(['', ''])
const tasks = ref<WorkspaceFileTask[]>([])
const sha = new Map<string, string>()
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const generation = [0, 0]

function directory(side: number) { return side ? right.value : left.value }
async function browse(side: number, id = '') {
  const request = ++generation[side]!
  busy.value[side] = true
  errors.value[side] = ''
  selected.value[side] = null
  try {
    const page = await browseFileWorkspace(roots.value[side]!, id)
    if (request !== generation[side] || disposed) return
    if (side) right.value = page
    else left.value = page
  } catch (cause) {
    if (request === generation[side]) {
      if (side) right.value = undefined
      else left.value = undefined
      errors.value[side] = cause instanceof Error ? cause.message : t('loadLocalFailed')
    }
  } finally { if (request === generation[side]) busy.value[side] = false }
}

async function refreshTasks() {
  try {
    const result = await listFileWorkspaceTasks()
    for (const task of result.items) {
      const entryId = sha.get(task.task_id)
      if (entryId && task.status === 'COMPLETED' && task.sha256) sha.set(entryId, task.sha256)
    }
    const completed = result.items.some(task => task.status === 'COMPLETED' && tasks.value.find(old => old.task_id === task.task_id)?.status !== 'COMPLETED')
    tasks.value = result.items
    if (completed) {
      await Promise.all([browse(0, left.value?.directory_id), browse(1, right.value?.directory_id)])
    }
  } catch (cause) {
    errors.value[0] = cause instanceof Error ? cause.message : t('loadLocalFailed')
  } finally {
    if (!disposed) timer = setTimeout(refreshTasks, 1000)
  }
}

async function operate(side: number, action: 'copy' | 'move' | 'rename' | 'delete' | 'mkdir' | 'checksum') {
  const entry = selected.value[side]
  const destination = directory(action === 'copy' || action === 'move' ? 1 - side : side)
  try {
    let name = entry?.name || ''
    let expected = ''
    let overwrite = false
    if (action === 'rename' || action === 'mkdir') name = (await ElMessageBox.prompt(t('name'), t(action === 'mkdir' ? 'newDirectory' : 'renameFile'))).value
    if (action === 'delete') {
      if (entry && !entry.directory) {
        const verified = await operateFileWorkspace({ action: 'checksum', source: entry.id })
        sha.set(verified.task_id, entry.id)
        ElMessage.info(t('verifyBeforeDelete'))
        return
      }
      await ElMessageBox.confirm(t('deleteEmptyConfirm'), t('deleteLocal'), { type: 'warning' })
    }
    if ((action === 'copy' || action === 'move') && destination && entry) {
      const collision = destination.items.find(item => item.name.toLocaleLowerCase() === name.toLocaleLowerCase())
      if (collision) {
        if (!sha.has(collision.id)) {
          const task = await operateFileWorkspace({ action: 'checksum', source: collision.id })
          sha.set(task.task_id, collision.id)
          ElMessage.info(t('verifyBeforeOverwrite'))
          return
        }
        expected = sha.get(collision.id)!
        await ElMessageBox.confirm(t('overwriteConfirm'), t('overwrite'), { type: 'warning' })
        overwrite = true
      }
    }
    const task = await operateFileWorkspace({ action, source: entry?.id, destination: destination?.directory_id, name, overwrite, expected_sha256: expected })
    if (action === 'checksum' && entry) sha.set(task.task_id, entry.id)
    tasks.value.unshift(task)
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : t('fileOperationFailed'))
  }
}

async function verifiedDelete(task: WorkspaceFileTask) {
  const entryId = sha.get(task.task_id)
  if (!entryId) return
  try {
    await ElMessageBox.confirm(t('deleteFileConfirm'), t('deleteLocal'), { type: 'warning' })
    tasks.value.unshift(await operateFileWorkspace({ action: 'delete', source: entryId, expected_sha256: task.sha256 }))
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(cause instanceof Error ? cause.message : t('fileOperationFailed'))
  }
}
async function cancel(task: WorkspaceFileTask) {
  try { await cancelFileWorkspaceTask(task.task_id) }
  catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : t('fileOperationFailed')) }
}
async function download(entry: WorkspaceEntry) {
  try {
    const result = await downloadBackendResource(workspaceFileRequest(entry))
    if (result.status === 'failed') ElMessage.error(result.error || t('downloadFailed'))
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : t('downloadFailed')) }
}
async function upload(side: number, event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const destination = directory(side)?.directory_id
  input.value = ''
  if (!destination || !files.length) return
  try {
    for (const file of files) tasks.value.unshift(await uploadFileWorkspace(destination, file))
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : t('uploadFailed')) }
}

onMounted(() => { void browse(0); void browse(1); void refreshTasks() })
onBeforeUnmount(() => { disposed = true; if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="workspace-file-panel">
    <div class="workspace-file-panes">
      <section v-for="side in [0, 1]" :key="side" class="workspace-file-pane">
        <header>
          <el-select v-model="roots[side]" :aria-label="t('fileRoot')" @change="browse(side)">
            <el-option v-for="root in (['downloads', 'tftp', 'ftp', 'http', 'https'] as const)" :key="root" :value="root" :label="root === 'downloads' ? t('localFiles') : root.toUpperCase()" />
          </el-select>
          <el-button :disabled="!directory(side)?.parent_id" @click="browse(side, directory(side)?.parent_id)">{{ t('up') }}</el-button>
          <el-button @click="browse(side, directory(side)?.directory_id)">{{ t('refresh') }}</el-button>
        </header>
        <span>{{ directory(side)?.label }}</span>
        <el-alert v-if="errors[side]" :title="errors[side]" type="error" :closable="false" />
        <div class="workspace-file-actions">
          <el-button :disabled="!selected[side]" @click="operate(side, 'checksum')">SHA-256</el-button>
          <el-button :disabled="!selected[side] || selected[side]?.directory" @click="selected[side] && download(selected[side]!)">{{ t('saveFile') }}</el-button>
          <template v-if="isFeatureEnabled('capability.file_management.local_write')">
            <label v-if="directory(side)?.writable">{{ t('uploadSelectedLocal') }}<input type="file" multiple @change="upload(side, $event)" /></label>
            <el-button :disabled="!selected[side] || !directory(1-side)?.writable" @click="operate(side, 'copy')">{{ t('copyLocal') }}</el-button>
            <el-button :disabled="!selected[side] || !directory(side)?.writable || !directory(1-side)?.writable" @click="operate(side, 'move')">{{ t('moveLocal') }}</el-button>
            <el-button :disabled="!selected[side] || !directory(side)?.writable" @click="operate(side, 'rename')">{{ t('renameFile') }}</el-button>
            <el-button :disabled="!directory(side)?.writable" @click="operate(side, 'mkdir')">{{ t('newDirectory') }}</el-button>
            <el-button type="danger" :disabled="!selected[side] || !directory(side)?.writable" @click="operate(side, 'delete')">{{ t('deleteLocal') }}</el-button>
          </template>
        </div>
        <el-table v-loading="busy[side]" :data="directory(side)?.items || []" height="100%" highlight-current-row @current-change="selected[side] = $event" @row-dblclick="(row: WorkspaceEntry) => row.directory && browse(side, row.id)">
          <el-table-column prop="name" :label="t('name')" min-width="130" sortable show-overflow-tooltip />
          <el-table-column prop="size" :label="t('size')" width="110" sortable />
          <el-table-column prop="mode" :label="t('permissions')" width="110" />
        </el-table>
      </section>
    </div>
    <section class="workspace-file-tasks">
      <article v-for="task in tasks" :key="task.task_id">
        <router-link :to="{ name: 'tasks', query: { task_id: task.task_id } }">{{ task.action }} · {{ task.status }}</router-link>
        <el-progress :percentage="task.total ? Math.min(100, task.current / task.total * 100) : task.status === 'COMPLETED' ? 100 : 0" />
        <span v-if="task.error">{{ task.error }}</span>
        <code v-if="task.sha256">{{ task.sha256 }}</code>
        <el-button v-if="['WAITING', 'RUNNING'].includes(task.status)" @click="cancel(task)">{{ t('cancelOperation') }}</el-button>
        <el-button v-if="task.action === 'checksum' && task.sha256 && sha.has(task.task_id)" @click="verifiedDelete(task)">{{ t('deleteVerified') }}</el-button>
      </article>
    </section>
  </section>
</template>

<style scoped>
.workspace-file-panel { display: flex; flex-direction: column; gap: 12px; min-height: 0; height: 100%; }
.workspace-file-panes { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 12px; flex: 1; min-height: 400px; }
.workspace-file-pane { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: hidden; }
header, .workspace-file-actions { display: flex; flex-wrap: wrap; gap: 6px; }
header .el-select { width: 160px; }
.workspace-file-tasks { max-height: 210px; overflow: auto; }
.workspace-file-tasks article { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 6px; }
.workspace-file-tasks .el-progress { width: 160px; }
code { overflow-wrap: anywhere; }
@media(max-width:760px) { .workspace-file-panes { grid-template-columns: 1fr; min-height: 700px; } }
</style>
