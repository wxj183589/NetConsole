<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Download, Folder, FolderAdd, Refresh, Upload } from '@element-plus/icons-vue'

import { createLocalDirectory, listLocalFiles, listRemoteDevices } from '../../api/fileManagement'
import { readSftpTextFile, startManagedSftpDownload, uploadManagedSftpFile, writeSftpTextFile } from '../../api/terminal'
import { isFeatureEnabled } from '../../features'
import { activeSiteContext } from '../../stores/siteContext'
import type { FileRemoteDevice, LocalFileEntry, LocalFilePage } from '../../types/fileManagement'
import TerminalSftpPanel from '../console/TerminalSftpPanel.vue'
import FileManagerSyncDialog from './FileManagerSyncDialog.vue'
import { createFileManagerTranslator } from './fileManagementI18n'

const t = createFileManagerTranslator()
const route = useRoute()
const page = ref<LocalFilePage>()
const localBusy = ref(false)
const error = ref('')
const devices = ref<FileRemoteDevice[]>([])
const tabs = ref<FileRemoteDevice[]>([])
const deviceId = ref('')
const selected = ref<string[]>([])
const filter = ref('')
const uploading = ref(false)
const downloading = ref(false)
const conflict = ref<'error' | 'skip' | 'rename' | 'overwrite'>('error')
const editorVisible = ref(false)
const editorBusy = ref(false)
const editorPath = ref('')
const editorText = ref('')
const editorRevision = ref('')
const editorOriginal = ref<{ text: string; digest: string; mode: number; uid: number; gid: number; newline: '\n' | '\r\n'; bom: boolean }>()
const editorDirty = ref(false)
const editorSessionId = ref('')
const siteId = computed(() => activeSiteContext.value?.siteId || '')
const canConnect = computed(() => isFeatureEnabled('capability.file_management.remote'))
const availableRows = computed(() => page.value?.items.filter(row =>
  row.name.toLocaleLowerCase().includes(filter.value.trim().toLocaleLowerCase())) ?? [])
let generation = 0

function openDevice(id: string): void {
  const device = devices.value.find(item => item.device_id === id)
  if (!device || !canConnect.value) return
  if (!tabs.value.some(tab => tab.device_id === id)) tabs.value.push(device)
  deviceId.value = id
}

function openRequestedDevice(): void {
  const value = route.query.device_uuid
  if (typeof value === 'string') openDevice(value)
}

async function resetSite(): Promise<void> {
  const request = ++generation
  page.value = undefined
  selected.value = []
  tabs.value = []
  deviceId.value = ''
  devices.value = []
  void browse()
  if (!canConnect.value) return
  try {
    const next = await listRemoteDevices()
    if (request === generation) {
      devices.value = next
      openRequestedDevice()
    }
  } catch (cause) {
    if (request === generation) ElMessage.error(errorText(cause, t('loadDevicesFailed')))
  }
}

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

let browseGeneration = 0
async function browse(directory = '', pageNumber = 1): Promise<void> {
  const request = ++browseGeneration
  localBusy.value = true
  error.value = ''
  try {
    const result = await listLocalFiles({ directory_id: directory, page: pageNumber, limit: 200 })
    if (request !== browseGeneration) return
    page.value = result
    selected.value = []
  } catch (cause) {
    if (request === browseGeneration) error.value = errorText(cause, t('loadLocalFailed'))
  } finally {
    if (request === browseGeneration) localBusy.value = false
  }
}

function openLocal(row: LocalFileEntry): void {
  if (row.is_dir) void browse(row.entry_id)
}

function selectLocal(rows: LocalFileEntry[]): void {
  selected.value = rows.filter(row => !row.is_dir).map(row => row.entry_id)
}

const editableExtensions = new Set(['.cfg', '.conf', '.ini', '.json', '.log', '.md', '.properties', '.sh', '.txt', '.yaml', '.yml'])
async function editRemoteFile(sessionId: string, path: string): Promise<void> {
  const extension = path.slice(path.lastIndexOf('.')).toLocaleLowerCase()
  if (!editableExtensions.has(extension)) {
    ElMessage.warning(t('editUnsupported'))
    return
  }
  editorBusy.value = true
  try {
    const file = await readSftpTextFile(sessionId, path)
    editorSessionId.value = sessionId
    editorPath.value = file.path
    editorText.value = file.text
    editorRevision.value = file.revision
    editorOriginal.value = { ...file.original, text: file.text, digest: file.revision }
    editorDirty.value = false
    editorVisible.value = true
  } catch (cause) {
    ElMessage.error(errorText(cause, t('editFailed')))
  } finally {
    editorBusy.value = false
  }
}

async function saveRemoteFile(): Promise<void> {
  if (!editorDirty.value || editorBusy.value) return
  editorBusy.value = true
  try {
    if (!editorOriginal.value) return
    const result = await writeSftpTextFile(editorSessionId.value, editorPath.value, editorRevision.value, editorText.value, editorOriginal.value)
    editorRevision.value = result.revision
    editorDirty.value = false
    editorVisible.value = false
    ElMessage.success(t('editSaved'))
  } catch (cause) {
    ElMessage.error(errorText(cause, t('editFailed')))
  } finally {
    editorBusy.value = false
  }
}

async function newLocalFolder(): Promise<void> {
  if (!page.value) return
  const context = page.value
  try {
    const name = (await ElMessageBox.prompt(t('folderName'), t('newDirectory'))).value.trim()
    if (!name || context !== page.value) return
    await createLocalDirectory({ site_id: context.site_id, directory_id: context.current_entry_id, name })
    if (context === page.value) await browse(context.current_entry_id, context.page)
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(errorText(cause, t('folderFailed')))
  }
}

async function uploadLocal(sessionId: string, directory: string, refresh: () => Promise<void>): Promise<void> {
  if (!selected.value.length || uploading.value) return
  const entries = [...selected.value]
  const policy = conflict.value
  const siteGeneration = generation
  uploading.value = true
  try {
    if (policy === 'overwrite') {
      await ElMessageBox.confirm(t('overwriteConfirm'), t('overwrite'), { type: 'warning' })
    }
    for (const entryId of entries) {
      if (siteGeneration !== generation) break
      await uploadManagedSftpFile(sessionId, directory, entryId, policy)
    }
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') ElMessage.error(errorText(cause, t('uploadFailed')))
  } finally {
    uploading.value = false
    if (siteGeneration === generation) await refresh()
  }
}

async function downloadToLocal(sessionId: string, paths: string[], refresh: () => Promise<void>): Promise<void> {
  if (!page.value || !paths.length || downloading.value) return
  const directoryId = page.value.current_entry_id
  const siteGeneration = generation
  downloading.value = true
  try {
    for (const path of [...paths]) {
      if (siteGeneration !== generation) break
      await startManagedSftpDownload(sessionId, path, directoryId)
    }
  } catch (cause) {
    ElMessage.error(errorText(cause, t('downloadFailed')))
  } finally {
    downloading.value = false
    if (siteGeneration === generation) await refresh()
  }
}

function closeTab(id: string | number): void {
  tabs.value = tabs.value.filter(tab => tab.device_id !== id)
  if (deviceId.value === id) deviceId.value = tabs.value[0]?.device_id || ''
}

watch([siteId, canConnect], () => void resetSite(), { immediate: true })
watch(() => route.query.device_uuid, openRequestedDevice)
</script>

<template>
  <section class="file-manager-workspace">
    <div class="file-manager-command">
      <el-select v-if="canConnect" :model-value="deviceId" filterable :placeholder="t('selectDevice')" :aria-label="t('selectDevice')" @change="openDevice">
        <el-option v-for="device in devices" :key="device.device_id" :label="`${device.name} · ${device.address}`" :value="device.device_id" />
      </el-select>
    </div>
    <div class="file-manager-panes">
      <section class="local-pane" :aria-label="t('localFiles')">
        <header class="local-toolbar">
          <strong>{{ t('localFiles') }}</strong>
          <el-button :icon="ArrowLeft" :title="t('up')" :aria-label="t('up')" :disabled="!page || page.current_entry_id === page.root_entry_id" @click="browse(page?.parent_entry_id)" />
          <el-button :icon="Refresh" :title="t('refresh')" :aria-label="t('refresh')" @click="browse(page?.current_entry_id, page?.page)" />
          <el-button v-if="isFeatureEnabled('capability.file_management.local_write')" :icon="FolderAdd" :title="t('newDirectory')" :aria-label="t('newDirectory')" :disabled="!page" @click="newLocalFolder" />
        </header>
        <div class="local-toolbar local-location">
          <span>{{ page?.current_label }}</span>
          <el-input v-model="filter" clearable :placeholder="t('filter')" :aria-label="t('filter')" />
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <el-table v-loading="localBusy" :data="availableRows" row-key="entry_id" height="100%" @row-dblclick="openLocal" @selection-change="selectLocal">
          <el-table-column type="selection" width="40" :selectable="(row: LocalFileEntry) => !row.is_dir" />
          <el-table-column prop="name" :label="t('name')" min-width="130" sortable show-overflow-tooltip>
            <template #default="{ row }">
              <button v-if="row.is_dir" class="directory-link" type="button" @click="openLocal(row)"><el-icon><Folder /></el-icon>{{ row.name }}</button>
              <span v-else>{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="size_bytes" :label="t('size')" width="102" sortable />
          <el-table-column prop="modified_at" :label="t('modified')" width="175" sortable />
        </el-table>
        <el-pagination v-if="page && page.total > page.limit" small layout="prev, pager, next" :current-page="page.page" :page-size="page.limit" :total="page.total" @current-change="browse(page?.current_entry_id, $event)" />
      </section>
      <section v-if="canConnect" class="remote-pane" :aria-label="t('remoteFiles')">
        <el-tabs v-if="tabs.length" v-model="deviceId" type="card" closable @tab-remove="closeTab">
          <el-tab-pane v-for="tab in tabs" :key="tab.device_id" :name="tab.device_id" :label="tab.name" />
        </el-tabs>
        <TerminalSftpPanel v-if="deviceId || !tabs.length" :key="siteId" workspace-id="file-manager" :device-uuid="deviceId" :device-name="tabs.find(tab => tab.device_id === deviceId)?.name || ''" all-workspace-transfers @managed-download="browse(page?.current_entry_id, page?.page)">
          <template #managed-actions="{ sessionId, directory, selectedRemote, selectedEntries = [], refreshTransfers }">
            <el-button :icon="Upload" :loading="uploading" :disabled="!selected.length" @click="uploadLocal(sessionId, directory, refreshTransfers)">{{ t('uploadSelectedLocal') }}</el-button>
            <el-button v-if="isFeatureEnabled('capability.file_management.download')" :icon="Download" :loading="downloading" :disabled="!page || !selectedRemote.length" @click="downloadToLocal(sessionId, selectedRemote, refreshTransfers)">{{ t('downloadToLocal') }}</el-button>
            <el-button :disabled="selectedEntries.length !== 1 || selectedEntries[0].is_dir || editorBusy" @click="editRemoteFile(sessionId, selectedEntries[0]?.remote_path || '')">{{ t('editRemote') }}</el-button>
            <el-select v-model="conflict" class="conflict-select" :aria-label="t('conflict')">
              <el-option v-for="action in (['error', 'skip', 'rename', 'overwrite'] as const)" :key="action" :label="t(action)" :value="action" />
            </el-select>
            <FileManagerSyncDialog v-if="page" :key="`${sessionId}-${page.current_entry_id}-${directory}`" :session-id="sessionId" :remote-directory="directory" :local-directory-id="page.current_entry_id" :local-directory-label="page.current_label" :allow-download="isFeatureEnabled('capability.file_management.download')" @submitted="refreshTransfers" />
          </template>
        </TerminalSftpPanel>
      </section>
    </div>
  </section>
  <el-dialog v-model="editorVisible" :title="editorPath" width="min(900px, 94vw)" :close-on-click-modal="!editorDirty && !editorBusy" :close-on-press-escape="!editorDirty && !editorBusy">
    <el-input v-model="editorText" type="textarea" :rows="22" :maxlength="262144" show-word-limit :disabled="editorBusy" @input="editorDirty = true" />
    <template #footer><el-button :disabled="editorBusy" @click="editorVisible = false">{{ t('cancel') }}</el-button><el-button type="primary" :loading="editorBusy" :disabled="!editorDirty" @click="saveRemoteFile">{{ t('save') }}</el-button></template>
  </el-dialog>
</template>

<style scoped>
.file-manager-workspace { display: flex; flex-direction: column; gap: 10px; height: 100%; min-height: 0; overflow: auto; }
.file-manager-command, .local-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.file-manager-command .el-select { width: min(360px, 100%); }
.file-manager-command a { color: var(--nc-primary); }
.file-manager-panes { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); flex: 1; min-height: 500px; }
.local-pane, .remote-pane { display: flex; min-width: 0; min-height: 0; flex-direction: column; gap: 8px; overflow: hidden; }
.local-pane { padding: 10px; border-right: 1px solid var(--nc-border); }
.local-pane .el-table, .remote-pane .sftp-panel { flex: 1; min-height: 0; }
.local-location .el-input { flex: 1; min-width: 105px; }
.directory-link { display: inline-flex; align-items: center; gap: 6px; border: 0; padding: 0; background: transparent; color: var(--nc-primary); cursor: pointer; }
.remote-pane :deep(.el-tabs__header) { margin-bottom: 0; }
.remote-pane :deep(.el-tabs__content) { display: none; }
.conflict-select { width: 120px; }
@media (max-width: 760px) {
  .file-manager-panes { grid-template-columns: minmax(0, 1fr); min-height: 780px; grid-template-rows: minmax(270px, 2fr) minmax(500px, 3fr); }
  .local-pane { border-right: 0; border-bottom: 1px solid var(--nc-border); }
}
</style>
