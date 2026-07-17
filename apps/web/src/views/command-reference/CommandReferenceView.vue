<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { ApiRequestError } from '../../api/client'
import {
  cancelCommandReferenceExport,
  commandReferenceArtifactDownloadRequest,
  getCommandReferenceExport,
  listCommandReferences,
  startCommandReferenceExport,
} from '../../api/commandReference'
import { downloadBackendResource, getPlatformAdapter, getRuntimeConfig } from '../../platform/runtime'
import type { CommandReference, CommandReferenceExportTask, CommandReferencePage } from '../../types/commandReference'
import { createCommandReferenceTranslator } from './commandReferenceI18n'

type TaskWindowStatus = 'PENDING' | 'STARTING' | 'RUNNING' | 'STOPPING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
const searchDelayMs = 250
const exportPollDelayMs = 1_000
const exportTaskStorageKey = 'netconsole.command-reference.current-export-task-id.v1'
const exportTaskIdPattern = /^command-reference-export-[0-9a-f]{32}$/
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const taskWindowStatuses = new Set<TaskWindowStatus>(['PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'FAILED', 'CANCELLED'])
const t = createCommandReferenceTranslator()
const route = useRoute()
const router = useRouter()
const filters = reactive({ query: '', module: '', device_scope: '', vendor: '', protocol: '', category: '', risk_level: '' })
const page = ref<CommandReferencePage | null>(null)
const selected = ref<CommandReference | null>(null)
const task = ref<CommandReferenceExportTask | null>(null)
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null
let exportPollTimer: ReturnType<typeof setTimeout> | null = null
let exportPollGeneration = 0
let componentActive = true
let requestGeneration = 0

const state = computed(() => error.value ? 'error' : loading.value ? 'loading' : page.value?.items.length ? 'success' : 'empty')
const artifactId = computed(() => String(task.value?.result?.artifact_id || ''))
const artifactName = computed(() => String(task.value?.result?.artifact_name || ''))
const artifactAvailable = computed(() => task.value?.status === 'COMPLETED' && Boolean(artifactId.value) && task.value?.result?.artifact_pending !== true)
const filterFields = computed(() => [
  ['module', t('module'), page.value?.filters.modules],
  ['device_scope', t('deviceScope'), page.value?.filters.device_scopes],
  ['vendor', t('vendor'), page.value?.filters.vendors],
  ['protocol', t('protocol'), page.value?.filters.protocols],
  ['category', t('category'), page.value?.filters.categories],
  ['risk_level', t('riskLevel'), page.value?.filters.risk_levels],
] as const)

watch(() => filters.query, scheduleSearch)

async function loadReferences(): Promise<void> {
  const generation = ++requestGeneration
  loading.value = true
  error.value = ''
  try {
    const result = await listCommandReferences({ ...filters })
    if (generation !== requestGeneration) return
    page.value = result
    selected.value = result.items.find((item) => item.id === selected.value?.id) || result.items[0] || null
  } catch (reason) {
    if (generation === requestGeneration) error.value = reason instanceof Error ? reason.message : t('loadFailed')
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

function scheduleSearch(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    void loadReferences()
  }, searchDelayMs)
}

function searchNow(): void {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = null
  void loadReferences()
}

async function copyCommand(): Promise<void> {
  if (!selected.value) {
    ElMessage.warning(t('selectFirst'))
    return
  }
  try {
    await navigator.clipboard.writeText(selected.value.command_template)
    ElMessage.success(t('copied'))
  } catch {
    ElMessage.error(t('copyFailed'))
  }
}

async function startExport(): Promise<void> {
  if (!page.value || exporting.value) return
  exporting.value = true
  try {
    setExportTask(await startCommandReferenceExport(page.value.items.map((item) => item.id)))
    ElMessage.success(t('taskSubmitted'))
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : t('exportFailed'))
  } finally {
    exporting.value = false
  }
}

async function recoverTask(taskId: string): Promise<void> {
  stopExportPolling()
  try {
    setExportTask(await getCommandReferenceExport(taskId))
  } catch (reason) {
    if (reason instanceof ApiRequestError && reason.status === 404) {
      clearPersistedExportTask(taskId)
      task.value = null
    }
    ElMessage.error(reason instanceof Error ? reason.message : t('restoreFailed'))
  }
}

async function cancelExport(): Promise<void> {
  if (!task.value?.cancellable) return
  const taskId = task.value.id
  stopExportPolling()
  try {
    const response = await cancelCommandReferenceExport(taskId)
    if (task.value?.id === taskId) {
      task.value = { ...task.value, status: response.status, cancellable: false, message: response.message }
    }
  } catch (reason) {
    if (task.value?.id === taskId && !terminalStates.has(task.value.status)) startExportPolling(taskId)
    ElMessage.error(reason instanceof Error ? reason.message : t('cancelFailed'))
  }
}

async function downloadArtifact(): Promise<void> {
  if (!artifactAvailable.value) return
  const result = await downloadBackendResource(commandReferenceArtifactDownloadRequest(artifactId.value))
  if (result.status === 'saved') ElMessage.success(t('downloadSaved'))
  else if (result.status === 'failed') ElMessage.error(result.error || t('downloadFailed'))
}

async function openTaskWindow(): Promise<void> {
  if (!task.value || !taskWindowStatuses.has(task.value.status as TaskWindowStatus)) return
  const context = {
    taskId: task.value.id,
    status: task.value.status as TaskWindowStatus,
  }
  if (getRuntimeConfig().hostType === 'electron') {
    try {
      const result = await getPlatformAdapter().openTaskWindow(context)
      if (!result.success) ElMessage.error(result.error || t('taskWindowFailed'))
    } catch (reason) {
      ElMessage.error(reason instanceof Error ? reason.message : t('taskWindowFailed'))
    }
    return
  }
  await router.push({ name: 'tasks', query: { task_id: context.taskId, module: 'command-reference', status: context.status } })
}

function setExportTask(snapshot: CommandReferenceExportTask): void {
  task.value = snapshot
  persistExportTask(snapshot.id)
  if (terminalStates.has(snapshot.status)) stopExportPolling()
  else startExportPolling(snapshot.id)
}

function startExportPolling(taskId: string): void {
  stopExportPolling()
  const generation = exportPollGeneration
  scheduleExportPoll(taskId, generation)
}

function scheduleExportPoll(taskId: string, generation: number): void {
  exportPollTimer = setTimeout(() => void pollExportTask(taskId, generation), exportPollDelayMs)
}

async function pollExportTask(taskId: string, generation: number): Promise<void> {
  if (!componentActive || generation !== exportPollGeneration) return
  exportPollTimer = null
  try {
    const snapshot = await getCommandReferenceExport(taskId)
    if (!componentActive || generation !== exportPollGeneration) return
    task.value = snapshot
    persistExportTask(snapshot.id)
    if (terminalStates.has(snapshot.status)) stopExportPolling()
    else scheduleExportPoll(taskId, generation)
  } catch (reason) {
    if (!componentActive || generation !== exportPollGeneration) return
    stopExportPolling()
    if (reason instanceof ApiRequestError && reason.status === 404) {
      clearPersistedExportTask(taskId)
      task.value = null
    }
    ElMessage.error(reason instanceof Error ? reason.message : t('restoreFailed'))
  }
}

function stopExportPolling(): void {
  exportPollGeneration += 1
  if (exportPollTimer) clearTimeout(exportPollTimer)
  exportPollTimer = null
}

function persistedExportTask(): string {
  try {
    const taskId = localStorage.getItem(exportTaskStorageKey) || ''
    if (!taskId || exportTaskIdPattern.test(taskId)) return taskId
    localStorage.removeItem(exportTaskStorageKey)
  } catch {
    // 浏览器禁用存储时仍允许当前页面使用导出任务。
  }
  return ''
}

function persistExportTask(taskId: string): void {
  if (!exportTaskIdPattern.test(taskId)) return
  try {
    localStorage.setItem(exportTaskStorageKey, taskId)
  } catch {
    // 持久化不可用不影响当前页面轮询。
  }
}

function clearPersistedExportTask(taskId: string): void {
  try {
    if (localStorage.getItem(exportTaskStorageKey) === taskId) localStorage.removeItem(exportTaskStorageKey)
  } catch {
    // 无需处理不可用的浏览器存储。
  }
}

function readOnlyText(item: CommandReference): string {
  return item.read_only === null ? t('conditional') : item.read_only ? t('yes') : t('no')
}

function riskText(value: string): string {
  return ({
    read_only: t('riskReadOnly'), config_write: t('riskConfigWrite'), interactive: t('riskInteractive'),
    external_tool: t('riskExternalTool'), unknown: t('riskUnknown'),
  } as Record<string, string>)[value] || value
}

function zteStatusText(value: string): string {
  return ({
    not_applicable: t('zteNotApplicable'), phase_1_reference: t('ztePhase1'), phase_2_reference: t('ztePhase2'),
  } as Record<string, string>)[value] || value
}

onMounted(async () => {
  await loadReferences()
  const taskId = typeof route.query.task_id === 'string' ? route.query.task_id : persistedExportTask()
  if (taskId) await recoverTask(taskId)
})

onUnmounted(() => {
  componentActive = false
  if (searchTimer) clearTimeout(searchTimer)
  stopExportPolling()
  requestGeneration += 1
})
</script>

<template>
  <section class="command-reference" :data-state="state">
    <header class="heading">
      <div><p class="eyebrow">{{ t('referenceOnly') }}</p><h1>{{ t('title') }}</h1><p>{{ t('subtitle') }}</p></div>
      <div class="actions"><el-button @click="loadReferences">{{ t('refresh') }}</el-button><el-button :disabled="!selected" @click="copyCommand">{{ t('copy') }}</el-button><el-button type="primary" :loading="exporting" @click="startExport">{{ t('exportMarkdown') }}</el-button></div>
    </header>

    <el-card shadow="never">
      <div class="filters">
        <el-input v-model="filters.query" clearable :placeholder="t('searchPlaceholder')" @keyup.enter="searchNow" />
        <el-select v-for="field in filterFields" :key="field[0]" v-model="filters[field[0]]" clearable :placeholder="field[1]" @change="loadReferences">
          <el-option v-for="value in field[2] || []" :key="value" :label="value" :value="value" />
        </el-select>
        <el-button @click="searchNow">{{ t('search') }}</el-button>
      </div>
      <p v-if="page" class="summary">{{ t('archived') }} {{ page.summary.total }} {{ t('itemUnit') }}，{{ t('shown') }} {{ page.summary.shown }} {{ t('itemUnit') }}；{{ t('switch') }} {{ page.summary.switch_count }} {{ t('itemUnit') }}，{{ t('nonCli') }} {{ page.summary.non_cli_count }} {{ t('itemUnit') }}。</p>
    </el-card>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button @click="loadReferences">{{ t('retry') }}</el-button></el-alert>
    <div v-loading="loading" class="content">
      <el-empty v-if="!loading && !error && !page?.items.length" :description="t('empty')" />
      <template v-else-if="page?.items.length">
        <el-card shadow="never" class="table-card">
          <el-table :data="page.items" highlight-current-row height="100%" @current-change="selected = $event">
            <el-table-column prop="category" :label="t('category')" width="140" /><el-table-column prop="command_template" :label="t('command')" min-width="260" show-overflow-tooltip />
            <el-table-column prop="purpose" :label="t('purpose')" min-width="220" show-overflow-tooltip /><el-table-column prop="module" :label="t('module')" width="160" />
            <el-table-column prop="pre_commands" :label="t('prerequisites')" min-width="180"><template #default="scope">{{ scope.row.pre_commands.join(', ') || t('none') }}</template></el-table-column>
            <el-table-column prop="device_scope" :label="t('deviceScope')" width="140" /><el-table-column prop="vendor" :label="t('vendor')" width="110" />
            <el-table-column prop="risk_level" :label="t('riskLevel')" width="120"><template #default="scope">{{ riskText(scope.row.risk_level) }}</template></el-table-column><el-table-column prop="notes" :label="t('notes')" min-width="220" show-overflow-tooltip />
          </el-table>
        </el-card>
        <el-card shadow="never" class="detail-card"><template #header>{{ t('details') }}</template>
          <el-descriptions v-if="selected" :column="1" border>
            <el-descriptions-item :label="t('commandTemplate')"><code>{{ selected.command_template }}</code></el-descriptions-item>
            <el-descriptions-item :label="t('moduleCategory')">{{ selected.module }} / {{ selected.category }}</el-descriptions-item>
            <el-descriptions-item :label="t('deviceVendorProtocol')">{{ selected.device_scope }} / {{ selected.vendor }} / {{ selected.protocol }}</el-descriptions-item>
            <el-descriptions-item :label="t('purpose')">{{ selected.purpose || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('readOnly')">{{ readOnlyText(selected) }}</el-descriptions-item>
            <el-descriptions-item :label="t('modifiesConfig')">{{ selected.modifies_device_config ? t('yes') : t('no') }}</el-descriptions-item>
            <el-descriptions-item :label="t('interactive')">{{ selected.requires_interactive_confirmation ? t('yes') : t('no') }}</el-descriptions-item>
            <el-descriptions-item :label="t('riskCli')">{{ riskText(selected.risk_level) }} / {{ selected.is_cli ? t('yes') : t('no') }}</el-descriptions-item>
            <el-descriptions-item :label="t('parameters')"><div v-if="selected.parameters.length"><p v-for="parameter in selected.parameters" :key="`${parameter.name}-${parameter.description}`">{{ parameter.name }}：{{ parameter.description }}</p></div><span v-else>{{ t('none') }}</span></el-descriptions-item>
            <el-descriptions-item :label="t('preCommands')">{{ selected.pre_commands.join(', ') || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('outputLog')">{{ selected.output_log || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('parserConsumer')">{{ selected.parser || t('none') }} / {{ selected.consumer || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('sourceLocations')">{{ selected.source_locations.join(', ') || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('comwareZte')">{{ selected.comware_command || t('none') }} / {{ selected.zte_command || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('adaptationStatus')">{{ t('zte') }}：{{ zteStatusText(selected.zte_adaptation_status) }}；{{ t('parser') }}：{{ selected.parser_status || t('none') }}</el-descriptions-item>
            <el-descriptions-item :label="t('cautions')">{{ selected.notes || t('none') }}</el-descriptions-item>
          </el-descriptions>
          <el-empty v-else :description="t('selectDetails')" />
        </el-card>
      </template>
    </div>

    <el-alert v-if="task" type="success" :closable="false" show-icon :title="t('taskSubmitted')">
      <span class="task-summary">{{ t('task') }} {{ task.id }} · {{ t('status') }} {{ task.status }} · {{ t('artifact') }} {{ artifactName || t('none') }}</span>
      <el-button :disabled="!task.cancellable || terminalStates.has(task.status)" @click="cancelExport">{{ t('cancel') }}</el-button>
      <el-button :disabled="!artifactAvailable" @click="downloadArtifact">{{ t('download') }}</el-button>
      <el-button type="primary" @click="openTaskWindow">{{ t('openTaskWindow') }}</el-button>
    </el-alert>
  </section>
</template>

<style scoped>
.command-reference{display:flex;flex-direction:column;gap:16px;min-width:0}.heading,.actions,.filters{display:flex;align-items:center;gap:10px}.heading{justify-content:space-between}.heading h1{margin:4px 0}.heading p,.summary{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:0}.filters{flex-wrap:wrap}.filters .el-input{width:300px}.filters .el-select{width:150px}.summary{margin-top:12px}.content{display:grid;grid-template-columns:minmax(620px,3fr) minmax(360px,2fr);gap:16px;min-height:520px}.table-card,.detail-card{min-width:0;height:520px}.detail-card{overflow:auto}.detail-card p{margin:0}.task-summary{margin-right:12px}@media(max-width:1000px){.heading{align-items:flex-start;flex-direction:column}.content{grid-template-columns:1fr}.table-card,.detail-card{height:auto;min-height:360px}}
</style>
