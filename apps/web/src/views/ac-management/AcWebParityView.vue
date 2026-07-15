<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  applyAcExtension,
  confirmAcActionPlan,
  createAcActionPlan,
  executeAcActionPlan,
  exportAcExtensions,
  listAcExtensions,
  previewAcExtension,
  rollbackAcExtension,
  startAcRefresh,
} from '../../api/acWebParity'
import type { AcActionPlan, AcExtension, AcExtensionPreview, AcWebTask } from '../../types/acWebParity'

const extensions = ref<AcExtension[]>([])
const extensionPreview = ref<AcExtensionPreview | null>(null)
const lastAuditId = ref('')
const actionPlan = ref<AcActionPlan | null>(null)
const targetId = ref('')
const actionId = ref('save_config')
const task = ref<AcWebTask | null>(null)
const error = ref('')
const loading = ref(false)

async function loadExtensions(): Promise<void> {
  loading.value = true
  try {
    extensions.value = (await listAcExtensions()).items
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AP 扩展信息加载失败'
  } finally {
    loading.value = false
  }
}

async function chooseFile(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    extensionPreview.value = await previewAcExtension(file)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'AP 扩展预览失败'
  }
}

async function applyExtension(): Promise<void> {
  if (!extensionPreview.value) return
  const result = await applyAcExtension(extensionPreview.value)
  lastAuditId.value = result.audit_id
  extensionPreview.value = null
  await loadExtensions()
}

async function rollbackExtension(): Promise<void> {
  if (!lastAuditId.value) return
  await rollbackAcExtension(lastAuditId.value)
  await loadExtensions()
}

async function refresh(kind: Parameters<typeof startAcRefresh>[0]): Promise<void> {
  task.value = await startAcRefresh(kind, targetId.value)
}

async function exportExtensions(): Promise<void> {
  task.value = await exportAcExtensions('', targetId.value)
}

async function createPlan(): Promise<void> {
  actionPlan.value = await createAcActionPlan(targetId.value, actionId.value)
}

async function confirmPlan(): Promise<void> {
  if (actionPlan.value) actionPlan.value = await confirmAcActionPlan(actionPlan.value)
}

async function executePlan(): Promise<void> {
  if (actionPlan.value) actionPlan.value = await executeAcActionPlan(actionPlan.value.plan_id)
}

onMounted(() => { void loadExtensions() })
</script>

<template>
  <section class="ac-web-parity">
    <header class="heading"><div><p class="eyebrow">AC WEB · CONTROLLED</p><h1>AC 扩展与受控动作</h1><p>复用正式 AC Query/Import/Task；危险动作只生成固定计划并交给 Fake Executor。</p></div><div class="actions"><el-button @click="exportExtensions">受控导出</el-button><el-button :loading="loading" @click="loadExtensions">刷新扩展信息</el-button></div></header>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <div class="toolbar"><el-input v-model="targetId" placeholder="AC 目标 ID，例如 ac-1" /><el-select v-model="actionId"><el-option label="固化新 AP" value="persist_auto_ap" /><el-option label="save force" value="save_config" /><el-option label="开启 AP 远程登录" value="enable_ap_remote_login" /></el-select><el-button @click="createPlan">生成计划</el-button><el-button :disabled="!actionPlan" @click="confirmPlan">二次确认</el-button><el-button type="danger" :disabled="actionPlan?.status !== 'CONFIRMED'" @click="executePlan">执行 Fake</el-button><el-button @click="refresh('optical')">刷新光衰任务</el-button></div>
    <el-card v-if="actionPlan" shadow="never" class="plan"><template #header>计划 {{ actionPlan.plan_id }} · {{ actionPlan.status }}</template><p>摘要：{{ actionPlan.plan_digest }}</p><p>令牌仅用于本次确认，过期或篡改会被拒绝。</p><pre>{{ actionPlan.command_summary.join('\n') }}</pre><p v-if="task">任务：{{ task.task_id }} / {{ task.status }}</p></el-card>
    <div class="grid"><el-card shadow="never"><template #header>AP 扩展导入预览 / 回滚</template><input type="file" accept=".csv,.xlsx" @change="chooseFile"><el-alert v-if="extensionPreview" class="preview" type="info" :title="`${extensionPreview.file_name} · ${extensionPreview.row_count} 行 · 摘要 ${extensionPreview.preview_digest}`" :closable="false" /><div class="actions"><el-button type="primary" :disabled="!extensionPreview" @click="applyExtension">确认写入</el-button><el-button :disabled="!lastAuditId" @click="rollbackExtension">回滚最近导入</el-button></div></el-card><el-card shadow="never"><template #header>扩展信息（{{ extensions.length }}）</template><el-table :data="extensions" height="360" empty-text="暂无 AP 扩展信息"><el-table-column prop="ap_name" label="AP" /><el-table-column prop="ap_mac_display" label="MAC" /><el-table-column prop="station_name" label="站点" /><el-table-column prop="section_name" label="区间" /><el-table-column prop="match_status" label="匹配" /></el-table></el-card></div>
  </section>
</template>

<style scoped>
.ac-web-parity { display: flex; flex-direction: column; gap: 16px; min-width: 0; }.heading,.toolbar,.actions { display: flex; align-items: center; gap: 10px; }.heading { justify-content: space-between; }.heading h1 { margin: 4px 0; }.heading p { margin: 0; color: var(--el-text-color-secondary); }.eyebrow { color: var(--el-color-primary) !important; font-size: 12px; font-weight: 700; letter-spacing: .08em; }.toolbar { flex-wrap: wrap; }.toolbar .el-input { width: 220px; }.toolbar .el-select { width: 190px; }.grid { display: grid; grid-template-columns: minmax(300px, .8fr) minmax(420px, 1.2fr); gap: 16px; }.preview { margin: 14px 0; }.plan pre { max-height: 160px; overflow: auto; padding: 10px; background: var(--el-fill-color-light); }@media (max-width: 900px) { .heading { align-items: flex-start; flex-direction: column; }.grid { grid-template-columns: 1fr; } }
</style>
