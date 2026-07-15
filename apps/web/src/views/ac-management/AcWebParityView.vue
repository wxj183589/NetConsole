<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  applyAcExtension,
  cancelAcWebTask,
  confirmAcActionPlan,
  createAcActionPlan,
  downloadAcExtensionArtifact,
  executeAcActionPlan,
  exportAcExtensions,
  getAcWebTask,
  listAcExtensions,
  listAcTracksidePlan,
  previewAcExtension,
  recoverAcWebTasks,
  rollbackAcExtension,
  startAcLocalRebuild,
} from '../../api/acWebParity'
import type { AcActionPlan, AcExtension, AcExtensionPreview, AcTracksidePlan, AcWebTask } from '../../types/acWebParity'

const taskStorageKey = 'netconsole.ac-web.last-task'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const extensions = ref<AcExtension[]>([])
const tracksidePlan = ref<AcTracksidePlan[]>([])
const extensionPreview = ref<AcExtensionPreview | null>(null)
const lastAuditId = ref('')
const actionPlan = ref<AcActionPlan | null>(null)
const targetId = ref('')
const actionId = ref('save_config')
const task = ref<AcWebTask | null>(null)
const error = ref('')
const loading = ref(false)
const taskBusy = ref(false)
let pollTimer: number | undefined

const taskSummary = computed(() => Object.entries(task.value?.result_summary || {}).map(([key, value]) => ({ key, value: String(value) })))

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

function rememberTask(value: AcWebTask | null): void {
  task.value = value
  if (value) localStorage.setItem(taskStorageKey, value.task_id)
  else localStorage.removeItem(taskStorageKey)
}

function stopPolling(): void {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePolling(): void {
  stopPolling()
  if (!task.value || terminalStates.has(task.value.status)) return
  pollTimer = window.setTimeout(async () => {
    try {
      rememberTask(await getAcWebTask(task.value!.task_id))
      schedulePolling()
    } catch (cause) {
      error.value = message(cause, 'AC 任务状态读取失败')
    }
  }, 1000)
}

async function loadData(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [extensionPage, planPage] = await Promise.all([listAcExtensions(), listAcTracksidePlan()])
    extensions.value = extensionPage.items
    tracksidePlan.value = planPage.items
  } catch (cause) {
    error.value = message(cause, 'AC 本地资料加载失败')
  } finally {
    loading.value = false
  }
}

async function recoverTask(): Promise<void> {
  const savedTaskId = localStorage.getItem(taskStorageKey) || ''
  try {
    const recovered = await recoverAcWebTasks()
    const selected = recovered.find((item) => item.task_id === savedTaskId)
      || recovered.find((item) => !terminalStates.has(item.status))
      || recovered[0]
    rememberTask(selected || null)
    schedulePolling()
  } catch (cause) {
    error.value = message(cause, 'AC 任务恢复失败')
  }
}

async function chooseFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  error.value = ''
  try {
    extensionPreview.value = await previewAcExtension(file)
  } catch (cause) {
    error.value = message(cause, 'AP 扩展预览失败')
  }
}

async function applyExtension(): Promise<void> {
  if (!extensionPreview.value) return
  taskBusy.value = true
  error.value = ''
  try {
    const result = await applyAcExtension(extensionPreview.value)
    lastAuditId.value = result.audit_id
    extensionPreview.value = null
    await loadData()
  } catch (cause) {
    error.value = message(cause, 'AP 扩展写入失败')
  } finally {
    taskBusy.value = false
  }
}

async function rollbackExtension(): Promise<void> {
  if (!lastAuditId.value) return
  taskBusy.value = true
  error.value = ''
  try {
    await rollbackAcExtension(lastAuditId.value)
    await loadData()
  } catch (cause) {
    error.value = message(cause, 'AP 扩展回滚失败')
  } finally {
    taskBusy.value = false
  }
}

async function startTask(factory: () => Promise<AcWebTask>, fallback: string): Promise<void> {
  taskBusy.value = true
  error.value = ''
  try {
    rememberTask(await factory())
    schedulePolling()
  } catch (cause) {
    error.value = message(cause, fallback)
  } finally {
    taskBusy.value = false
  }
}

function rebuild(kind: Parameters<typeof startAcLocalRebuild>[0]): void {
  void startTask(() => startAcLocalRebuild(kind, targetId.value), 'AC 本地重算任务启动失败')
}

function exportExtensions(): void {
  void startTask(() => exportAcExtensions('', targetId.value), 'AP 扩展导出启动失败')
}

async function cancelTask(): Promise<void> {
  if (!task.value || terminalStates.has(task.value.status)) return
  await startTask(() => cancelAcWebTask(task.value!.task_id), 'AC 任务取消失败')
}

async function downloadArtifact(): Promise<void> {
  if (!task.value?.available || !task.value.artifact_id) return
  taskBusy.value = true
  error.value = ''
  try {
    await downloadAcExtensionArtifact(task.value.artifact_id)
  } catch (cause) {
    error.value = message(cause, 'AP 扩展报告下载失败')
  } finally {
    taskBusy.value = false
  }
}

async function createPlan(): Promise<void> {
  error.value = ''
  try { actionPlan.value = await createAcActionPlan(targetId.value, actionId.value) }
  catch (cause) { error.value = message(cause, 'AC Fake 计划创建失败') }
}

async function confirmPlan(): Promise<void> {
  if (!actionPlan.value) return
  try { actionPlan.value = await confirmAcActionPlan(actionPlan.value) }
  catch (cause) { error.value = message(cause, 'AC Fake 计划确认失败') }
}

async function executePlan(): Promise<void> {
  if (!actionPlan.value) return
  try { actionPlan.value = await executeAcActionPlan(actionPlan.value.plan_id) }
  catch (cause) { error.value = message(cause, 'AC Fake 计划执行失败') }
}

onMounted(() => { void loadData(); void recoverTask() })
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="ac-web-parity">
    <header class="heading"><div><p class="eyebrow">AC WEB · BOUNDED ENTRY</p><h1>AP 扩展、轨旁规划与本地任务</h1><p>只展示本页已接入能力；在线概览、光衰详情和配置对比继续复用既有成熟页面。</p></div><div class="actions"><el-button :loading="taskBusy" @click="exportExtensions">导出扩展信息</el-button><el-button :loading="loading" @click="loadData">重新加载本地资料</el-button></div></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button link @click="recoverTask">重试任务恢复</el-button></el-alert>
    <div class="toolbar"><el-input v-model="targetId" placeholder="可选：当前局点 AC UUID" /><el-select v-model="actionId"><el-option label="固化新 AP" value="persist_auto_ap" /><el-option label="save force" value="save_config" /><el-option label="开启 AP 远程登录" value="enable_ap_remote_login" /></el-select><el-button @click="createPlan">生成 Fake 计划</el-button><el-button :disabled="!actionPlan" @click="confirmPlan">二次确认</el-button><el-button type="danger" :disabled="actionPlan?.status !== 'CONFIRMED'" @click="executePlan">执行 Fake</el-button><el-button :loading="taskBusy" @click="rebuild('optical')">本地重算光衰视图</el-button></div>
    <el-alert type="warning" title="本地重算只读取当前数据库与缓存，不连接真实 AC。" show-icon :closable="false" />
    <el-card v-if="task" shadow="never" class="task-card"><template #header>任务 {{ task.task_id }}</template><el-descriptions :column="3" border><el-descriptions-item label="动作">{{ task.action }}</el-descriptions-item><el-descriptions-item label="状态">{{ task.status }}</el-descriptions-item><el-descriptions-item label="消息">{{ task.error_message || task.message || '—' }}</el-descriptions-item><el-descriptions-item label="Artifact">{{ task.artifact_id || '—' }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ task.sha256 || '—' }}</el-descriptions-item><el-descriptions-item label="大小">{{ task.size_bytes }}</el-descriptions-item></el-descriptions><el-table v-if="taskSummary.length" :data="taskSummary" size="small"><el-table-column prop="key" label="结果项" /><el-table-column prop="value" label="值" /></el-table><div class="actions"><el-button :disabled="terminalStates.has(task.status)" @click="cancelTask">取消任务</el-button><el-button :disabled="!task.available" @click="downloadArtifact">受控下载</el-button></div></el-card>
    <el-card v-if="actionPlan" shadow="never" class="plan"><template #header>Fake 计划 {{ actionPlan.plan_id }} · {{ actionPlan.status }}</template><p>摘要：{{ actionPlan.plan_digest }}</p><pre>{{ actionPlan.command_summary.join('\n') }}</pre></el-card>
    <div class="grid"><el-card shadow="never"><template #header>AP 扩展导入预览 / 回滚</template><input type="file" accept=".csv,.xlsx" @change="chooseFile"><el-alert v-if="extensionPreview" class="preview" type="info" :title="`${extensionPreview.file_name} · ${extensionPreview.row_count} 行 · 摘要 ${extensionPreview.preview_digest}`" :closable="false" /><div class="actions"><el-button type="primary" :loading="taskBusy" :disabled="!extensionPreview" @click="applyExtension">确认写入</el-button><el-button :loading="taskBusy" :disabled="!lastAuditId" @click="rollbackExtension">回滚最近导入</el-button></div></el-card><el-card shadow="never"><template #header>AP 扩展信息（{{ extensions.length }}）</template><el-table :data="extensions" height="320" empty-text="暂无 AP 扩展信息"><el-table-column prop="ap_name" label="AP" /><el-table-column prop="ap_mac_display" label="MAC" /><el-table-column prop="station_name" label="站点" /><el-table-column prop="section_name" label="区间" /><el-table-column prop="match_status" label="匹配" /></el-table></el-card></div>
    <el-card shadow="never"><template #header>轨旁 AP 规划（{{ tracksidePlan.length }}）</template><el-table :data="tracksidePlan" height="320" empty-text="暂无轨旁 AP 规划"><el-table-column prop="station_name" label="站点" /><el-table-column prop="ap_count" label="AP 数" width="90" /><el-table-column prop="ap_start_address" label="起始地址" /><el-table-column prop="mask_length" label="掩码" width="80" /><el-table-column prop="ap_gateway" label="网关" /><el-table-column prop="ap_management_vlans" label="管理 VLAN" /><el-table-column prop="remark" label="备注" /></el-table></el-card>
  </section>
</template>

<style scoped>
.ac-web-parity { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.heading,.toolbar,.actions { display: flex; align-items: center; gap: 10px; }.heading { justify-content: space-between; }.heading h1 { margin: 4px 0; }.heading p { margin: 0; color: var(--el-text-color-secondary); }.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }.toolbar { flex-wrap: wrap; }.toolbar .el-input { width: 240px; }.toolbar .el-select { width: 190px; }.grid { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); gap: 16px; }.preview { margin: 14px 0; }.plan pre { max-height: 160px; overflow: auto; padding: 10px; background: var(--el-fill-color-light); }.task-card .actions { margin-top: 12px; }@media (max-width: 900px) { .heading { align-items: flex-start; flex-direction: column; }.grid { grid-template-columns: 1fr; } }
</style>
