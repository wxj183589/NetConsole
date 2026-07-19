<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useConfirm } from '../../components/feedback/useConfirm'

import {
  applyAcExtension,
  confirmAcActionPlan,
  createAcActionPlan,
  executeAcActionPlan,
  exportAcExtensions,
  getAcActionAudit,
  getAcActionPlan,
  getAcWebTask,
  listAcExtensions,
  previewAcExtension,
  recoverAcWebTasks,
  rollbackAcExtension,
  startAcLocalRebuild,
} from '../../api/acWebParity'
import { isFeatureEnabled } from '../../features'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import type { AcActionAudit, AcActionPlan, AcExtension, AcExtensionPreview, AcWebTask } from '../../types/acWebParity'

const taskStorageKey = 'netconsole.ac-web.last-task'
const actionPlanStorageKey = 'netconsole.ac-web.action-plan'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const extensions = ref<AcExtension[]>([])
const extensionPreview = ref<AcExtensionPreview | null>(null)
const lastAuditId = ref('')
const actionPlan = ref<AcActionPlan | null>(null)
const actionAudit = ref<AcActionAudit | null>(null)
const targetId = ref('')
const actionId = ref('persist_auto_ap')
const task = ref<AcWebTask | null>(null)
const error = ref('')
const loading = ref(false)
const taskBusy = ref(false)
const router = useRouter()
const { confirm } = useConfirm()
let pollTimer: number | undefined

const extensionColumns: NcTableColumn<AcExtension>[] = [
  { key: 'ap_name', label: 'AP', valueType: 'name' },
  { key: 'ap_mac_display', label: 'MAC', valueType: 'mac' },
  { key: 'station_name', label: '站点', valueType: 'text' },
  { key: 'section_name', label: '区间', valueType: 'text' },
  { key: 'match_status', label: '匹配', valueType: 'status' },
]

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
      if (terminalStates.has(task.value!.status)) await refreshActionAudit()
      else schedulePolling()
    } catch (cause) {
      error.value = message(cause, 'AC 任务状态读取失败')
    }
  }, 1000)
}

async function loadData(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    extensions.value = isFeatureEnabled('web.ac_extensions') ? (await listAcExtensions()).items : []
  } catch (cause) {
    error.value = message(cause, 'AC 本地资料加载失败')
  } finally {
    loading.value = false
  }
}

async function recoverTask(): Promise<void> {
  if (!isFeatureEnabled('web.ac_refresh')) return
  const savedTaskId = localStorage.getItem(taskStorageKey) || ''
  try {
    const recovered = await recoverAcWebTasks()
    const selected = recovered.find((item) => item.task_id === savedTaskId)
      || recovered.find((item) => !terminalStates.has(item.status))
      || recovered[0]
    rememberTask(selected || null)
    const savedPlanId = localStorage.getItem(actionPlanStorageKey) || ''
    if (savedPlanId) {
      actionPlan.value = await getAcActionPlan(savedPlanId)
      await refreshActionAudit()
    }
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
  try {
    if (!await confirm({ type: 'WARNING', title: '确认导入 AP 扩展资料', message: '确认把当前预览写入 AP 扩展资料？该操作会记录审计并可按审计记录回滚。', confirmText: '确认导入' })) return
  } catch {
    return
  }
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
  try {
    if (!await confirm({ type: 'WARNING', title: '确认回滚 AP 扩展导入', message: '确认回滚最近一次 AP 扩展导入？', confirmText: '确认回滚' })) return
  } catch {
    return
  }
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

function openTaskWindow(): void {
  const taskId = task.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'ac', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'ac', ...(taskId ? { task_id: taskId } : {}) } })
}

async function createPlan(): Promise<void> {
  error.value = ''
  try {
    actionPlan.value = await createAcActionPlan(targetId.value, actionId.value)
    actionAudit.value = null
    localStorage.setItem(actionPlanStorageKey, actionPlan.value.plan_id)
  }
  catch (cause) { error.value = message(cause, 'AC 动作计划创建失败') }
}

async function confirmPlan(): Promise<void> {
  if (!actionPlan.value) return
  try {
    if (!await confirm({
      type: 'DANGER',
      title: '确认 AC 写操作',
      message: `确认对所选 AC 执行以下固定命令？\n\n${actionPlan.value.command_summary.join('\n')}`,
      confirmText: '确认执行',
    })) return
  } catch {
    return
  }
  try { actionPlan.value = await confirmAcActionPlan(actionPlan.value) }
  catch (cause) { error.value = message(cause, 'AC 动作计划确认失败') }
}

async function executePlan(): Promise<void> {
  if (!actionPlan.value) return
  try {
    actionPlan.value = await executeAcActionPlan(actionPlan.value.plan_id)
    if (actionPlan.value.task_id) {
      rememberTask(await getAcWebTask(actionPlan.value.task_id))
      await refreshActionAudit()
      schedulePolling()
    }
  } catch (cause) { error.value = message(cause, 'AC 动作计划执行失败') }
}

async function refreshActionAudit(): Promise<void> {
  if (!actionPlan.value) return
  actionPlan.value = await getAcActionPlan(actionPlan.value.plan_id)
  actionAudit.value = await getAcActionAudit(actionPlan.value.plan_id)
}

onMounted(() => {
  void loadData()
  if (isFeatureEnabled('web.ac_refresh')) void recoverTask()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="ac-web-parity">
    <header class="heading"><div><p class="eyebrow">AC WEB · BOUNDED ENTRY</p><h1>AP 扩展、轨旁规划与本地任务</h1><p>只展示本页已接入能力；在线概览、光衰详情和配置对比继续复用既有成熟页面。</p></div><div class="actions"><el-button :loading="taskBusy" :disabled="!isFeatureEnabled('web.ac_extensions_export') || !isFeatureEnabled('web.ac_refresh')" @click="exportExtensions">导出扩展信息</el-button><el-button :loading="loading" @click="loadData">重新加载本地资料</el-button></div></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button link @click="recoverTask">重试任务恢复</el-button></el-alert>
    <div class="toolbar"><el-input v-model="targetId" placeholder="当前局点 AC UUID" /><template v-if="isFeatureEnabled('web.ac_dangerous_actions')"><el-select v-model="actionId"><el-option label="固化新 AP" value="persist_auto_ap" /><el-option label="开启 AP 远程登录" value="enable_ap_remote_login" /></el-select><el-button @click="createPlan">生成命令预览</el-button><el-button :disabled="!actionPlan" @click="confirmPlan">二次确认</el-button><el-button type="danger" :disabled="actionPlan?.status !== 'CONFIRMED'" @click="executePlan">执行真实任务</el-button></template><el-button :loading="taskBusy" :disabled="!isFeatureEnabled('web.ac_refresh')" @click="rebuild('optical')">本地重算光衰视图</el-button></div>
    <el-alert type="warning" title="本地重算只读取当前数据库与缓存，不连接真实 AC。" show-icon :closable="false" />
    <el-alert v-if="isFeatureEnabled('web.ac_dangerous_actions')" type="error" title="AC 写操作会连接真实设备；必须先核对固定命令预览并完成二次确认。" show-icon :closable="false" />
    <el-alert
      :title="task ? `AC 任务 · ${task.action} · ${task.status}` : 'AC 任务 · 暂无记录'"
      :description="task ? (task.error_message || task.message || task.task_id) : '停止、日志与 Artifact 操作统一在任务窗口完成'"
      type="info"
      show-icon
      :closable="false"
    ><el-button link type="primary" @click="openTaskWindow">打开任务窗口</el-button></el-alert>
    <el-card v-if="actionPlan" shadow="never" class="plan"><template #header>AC 动作计划 {{ actionPlan.plan_id }} · {{ actionPlan.status }}</template><p>审计摘要：{{ actionPlan.plan_digest }}</p><pre>{{ actionPlan.command_summary.join('\n') }}</pre></el-card>
    <el-card v-if="actionAudit" shadow="never" class="plan"><template #header>AC 动作审计 · {{ actionAudit.status }}</template><el-descriptions :column="3" border><el-descriptions-item label="目标">{{ actionAudit.target_id }}</el-descriptions-item><el-descriptions-item label="动作">{{ actionAudit.action_id }}</el-descriptions-item><el-descriptions-item label="任务状态">{{ actionAudit.task_status || '—' }}</el-descriptions-item><el-descriptions-item label="执行器">{{ actionAudit.executor }}</el-descriptions-item><el-descriptions-item label="Task">{{ actionAudit.task_id || '—' }}</el-descriptions-item><el-descriptions-item label="摘要">{{ actionAudit.plan_digest }}</el-descriptions-item></el-descriptions></el-card>
    <div class="grid">
      <el-card shadow="never"><template #header>AP 扩展导入预览 / 回滚</template><input type="file" accept=".csv,.xlsx" :disabled="!isFeatureEnabled('web.ac_extensions_preview')" @change="chooseFile"><el-alert v-if="extensionPreview" class="preview" type="info" :title="`${extensionPreview.file_name} · ${extensionPreview.row_count} 行 · 摘要 ${extensionPreview.preview_digest}`" :closable="false" /><div class="actions"><el-button type="primary" :loading="taskBusy" :disabled="!extensionPreview || !isFeatureEnabled('web.ac_extensions_apply')" @click="applyExtension">确认写入</el-button><el-button :loading="taskBusy" :disabled="!lastAuditId || !isFeatureEnabled('web.ac_extensions_rollback')" @click="rollbackExtension">回滚最近导入</el-button></div></el-card>
      <el-card shadow="never"><template #header>AP 扩展信息（{{ extensions.length }}）</template><NcDataTable table-id="ac-extension-records" route-key="/ac-management/parity" :data="extensions" :columns="extensionColumns" :height="320" empty-text="暂无 AP 扩展信息" /></el-card>
    </div>
  </section>
</template>

<style scoped>
.ac-web-parity { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.heading,.toolbar,.actions { display: flex; align-items: center; gap: 10px; }.heading { justify-content: space-between; }.heading h1 { margin: 4px 0; }.heading p { margin: 0; color: var(--el-text-color-secondary); }.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }.toolbar { flex-wrap: wrap; }.toolbar .el-input { width: 240px; }.toolbar .el-select { width: 190px; }.grid { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); gap: 16px; }.preview { margin: 14px 0; }.plan pre { max-height: 160px; overflow: auto; padding: 10px; background: var(--el-fill-color-light); }@media (max-width: 900px) { .heading { align-items: flex-start; flex-direction: column; }.grid { grid-template-columns: 1fr; } }
</style>
