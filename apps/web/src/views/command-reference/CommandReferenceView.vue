<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  cancelCommandReferenceExport,
  commandReferenceArtifactDownloadRequest,
  getCommandReferenceExport,
  listCommandReferences,
  startCommandReferenceExport,
} from '../../api/commandReference'
import { downloadBackendResource } from '../../platform/runtime'
import type { CommandReference, CommandReferenceExportTask, CommandReferencePage } from '../../types/commandReference'

const taskStorageKey = 'netconsole.command-reference.export-task-id'
const terminalStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const filters = reactive({ query: '', module: '', device_scope: '', vendor: '', protocol: '', category: '', risk_level: '' })
const page = ref<CommandReferencePage | null>(null)
const selected = ref<CommandReference | null>(null)
const task = ref<CommandReferenceExportTask | null>(null)
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
let pollTimer: number | undefined

const state = computed(() => error.value ? 'error' : loading.value ? 'loading' : page.value?.items.length ? 'success' : 'empty')
const artifactId = computed(() => String(task.value?.result?.artifact_id || ''))
const artifactName = computed(() => String(task.value?.result?.artifact_name || ''))
const artifactSha256 = computed(() => String(task.value?.result?.sha256 || ''))
const artifactAvailable = computed(() => task.value?.status === 'COMPLETED' && Boolean(artifactId.value) && task.value?.result?.artifact_pending !== true)

async function loadReferences(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    page.value = await listCommandReferences(filters)
    selected.value = page.value.items.find((item) => item.id === selected.value?.id) || page.value.items[0] || null
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '命令说明加载失败'
  } finally {
    loading.value = false
  }
}

async function copyCommand(): Promise<void> {
  if (!selected.value) {
    ElMessage.warning('请先选择一条命令说明')
    return
  }
  try {
    await navigator.clipboard.writeText(selected.value.command_template)
    ElMessage.success('命令模板已复制')
  } catch {
    ElMessage.error('复制失败，请检查剪贴板权限')
  }
}

async function startExport(): Promise<void> {
  if (!page.value || exporting.value) return
  exporting.value = true
  try {
    task.value = await startCommandReferenceExport(page.value.items.map((item) => item.id))
    window.localStorage.setItem(taskStorageKey, task.value.id)
    schedulePoll()
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '导出启动失败')
  } finally {
    exporting.value = false
  }
}

async function refreshTask(): Promise<void> {
  if (!task.value?.id) return
  try {
    task.value = await getCommandReferenceExport(task.value.id)
    if (!terminalStates.has(task.value.status)) schedulePoll()
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '导出状态恢复失败')
    window.localStorage.removeItem(taskStorageKey)
  }
}

function schedulePoll(): void {
  window.clearTimeout(pollTimer)
  if (task.value && !terminalStates.has(task.value.status)) pollTimer = window.setTimeout(refreshTask, 800)
}

async function cancelExport(): Promise<void> {
  if (!task.value?.cancellable) return
  try {
    await cancelCommandReferenceExport(task.value.id)
    task.value = await getCommandReferenceExport(task.value.id)
    schedulePoll()
  } catch (reason) {
    ElMessage.error(reason instanceof Error ? reason.message : '取消导出失败')
  }
}

async function downloadArtifact(): Promise<void> {
  if (!artifactAvailable.value) return
  const result = await downloadBackendResource(commandReferenceArtifactDownloadRequest(artifactId.value, artifactName.value))
  if (result.status === 'saved') ElMessage.success('Markdown 已保存')
  else if (result.status === 'failed') ElMessage.error(result.error || 'Artifact 下载失败')
}

onMounted(async () => {
  await loadReferences()
  const taskId = window.localStorage.getItem(taskStorageKey)
  if (taskId) {
    task.value = { id: taskId } as CommandReferenceExportTask
    await refreshTask()
  }
})
onUnmounted(() => window.clearTimeout(pollTimer))
</script>

<template>
  <section class="command-reference" :data-state="state">
    <header class="heading">
      <div><p class="eyebrow">REFERENCE ONLY · 不执行设备命令</p><h1>命令说明</h1><p>查询版本化命令资源，复制模板或导出当前筛选结果。</p></div>
      <div class="actions"><el-button @click="loadReferences">刷新</el-button><el-button :disabled="!selected" @click="copyCommand">复制命令模板</el-button><el-button type="primary" :loading="exporting" @click="startExport">导出 Markdown</el-button></div>
    </header>

    <el-card shadow="never">
      <div class="filters">
        <el-input v-model="filters.query" clearable placeholder="搜索命令、用途、模块、源码位置" @keyup.enter="loadReferences" @clear="loadReferences" />
        <el-select v-for="field in [
          ['module', '模块', page?.filters.modules], ['device_scope', '设备类型', page?.filters.device_scopes],
          ['vendor', '厂商', page?.filters.vendors], ['protocol', '协议', page?.filters.protocols],
          ['category', '类别', page?.filters.categories], ['risk_level', '风险级别', page?.filters.risk_levels],
        ]" :key="String(field[0])" v-model="filters[field[0] as keyof typeof filters]" clearable :placeholder="String(field[1])" @change="loadReferences">
          <el-option v-for="value in field[2] as string[] || []" :key="value" :label="value" :value="value" />
        </el-select>
        <el-button @click="loadReferences">搜索</el-button>
      </div>
      <p v-if="page" class="summary">已归档 {{ page.summary.total }} 条，当前显示 {{ page.summary.shown }} 条；交换机 {{ page.summary.switch_count }} 条，非 CLI / 本地工具 {{ page.summary.non_cli_count }} 条。</p>
    </el-card>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button @click="loadReferences">重试</el-button></el-alert>
    <div v-loading="loading" class="content">
      <el-empty v-if="!loading && !error && !page?.items.length" description="当前筛选没有命令说明" />
      <template v-else-if="page?.items.length">
        <el-card shadow="never" class="table-card">
          <el-table :data="page.items" highlight-current-row height="100%" @current-change="selected = $event">
            <el-table-column prop="category" label="类别" width="140" /><el-table-column prop="command_template" label="命令" min-width="260" show-overflow-tooltip />
            <el-table-column prop="purpose" label="当前用途" min-width="220" show-overflow-tooltip /><el-table-column prop="module" label="模块" width="160" />
            <el-table-column prop="device_scope" label="设备类型" width="140" /><el-table-column prop="vendor" label="厂商" width="110" />
            <el-table-column prop="risk_level" label="风险级别" width="120" /><el-table-column prop="notes" label="备注" min-width="220" show-overflow-tooltip />
          </el-table>
        </el-card>
        <el-card shadow="never" class="detail-card"><template #header>命令详情</template>
          <el-descriptions v-if="selected" :column="1" border>
            <el-descriptions-item label="命令模板"><code>{{ selected.command_template }}</code></el-descriptions-item>
            <el-descriptions-item label="模块 / 类别">{{ selected.module }} / {{ selected.category }}</el-descriptions-item>
            <el-descriptions-item label="设备 / 厂商 / 协议">{{ selected.device_scope }} / {{ selected.vendor }} / {{ selected.protocol }}</el-descriptions-item>
            <el-descriptions-item label="当前用途">{{ selected.purpose || '—' }}</el-descriptions-item>
            <el-descriptions-item label="风险">{{ selected.risk_level }}；交互确认：{{ selected.interactive_input ? '是' : '否' }}；CLI：{{ selected.is_cli ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="参数"><div v-if="selected.parameters.length"><p v-for="parameter in selected.parameters" :key="`${parameter.name}-${parameter.description}`">{{ parameter.name }}：{{ parameter.description }}</p></div><span v-else>—</span></el-descriptions-item>
            <el-descriptions-item label="前置命令">{{ selected.pre_commands.join(', ') || '—' }}</el-descriptions-item>
            <el-descriptions-item label="输出 / 日志">{{ selected.output_log || '—' }}</el-descriptions-item>
            <el-descriptions-item label="解析器 / 消费模块">{{ selected.parser || '—' }} / {{ selected.consumer || '—' }}</el-descriptions-item>
            <el-descriptions-item label="源码位置">{{ selected.source_locations.join(', ') || '—' }}</el-descriptions-item>
            <el-descriptions-item label="Comware / ZTE">{{ selected.comware_command || '—' }} / {{ selected.zte_command || '—' }}</el-descriptions-item>
            <el-descriptions-item label="适配状态">ZTE：{{ selected.zte_adaptation_status }}；解析器：{{ selected.parser_status || '—' }}</el-descriptions-item>
            <el-descriptions-item label="注意事项">{{ selected.notes || '—' }}</el-descriptions-item>
          </el-descriptions>
          <el-empty v-else description="选择左侧命令后查看详情" />
        </el-card>
      </template>
    </div>

    <el-card v-if="task" shadow="never"><template #header>Markdown 导出</template>
      <el-descriptions :column="3" border><el-descriptions-item label="任务">{{ task.id }}</el-descriptions-item><el-descriptions-item label="状态">{{ task.status }}</el-descriptions-item><el-descriptions-item label="条数">{{ task.total || '—' }}</el-descriptions-item><el-descriptions-item label="消息">{{ task.error_message || task.message || '—' }}</el-descriptions-item><el-descriptions-item label="Artifact">{{ artifactName || '生成中' }}</el-descriptions-item><el-descriptions-item label="SHA-256">{{ artifactSha256 || '—' }}</el-descriptions-item></el-descriptions>
      <div class="task-actions"><el-button :disabled="!task.cancellable" @click="cancelExport">取消</el-button><el-button type="primary" :disabled="!artifactAvailable" @click="downloadArtifact">下载 Artifact</el-button></div>
    </el-card>
  </section>
</template>

<style scoped>
.command-reference{display:flex;flex-direction:column;gap:16px;min-width:0}.heading,.actions,.filters,.task-actions{display:flex;align-items:center;gap:10px}.heading{justify-content:space-between}.heading h1{margin:4px 0}.heading p,.summary{margin:0;color:var(--el-text-color-secondary)}.eyebrow{color:var(--el-color-primary)!important;font-size:12px;font-weight:700;letter-spacing:.08em}.filters{flex-wrap:wrap}.filters .el-input{width:300px}.filters .el-select{width:150px}.summary{margin-top:12px}.content{display:grid;grid-template-columns:minmax(620px,3fr) minmax(360px,2fr);gap:16px;min-height:520px}.table-card,.detail-card{min-width:0;height:520px}.detail-card{overflow:auto}.detail-card p{margin:0}.task-actions{margin-top:12px}@media(max-width:1000px){.heading{align-items:flex-start;flex-direction:column}.content{grid-template-columns:1fr}.table-card,.detail-card{height:auto;min-height:360px}}
</style>
