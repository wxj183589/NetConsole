<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CirclePlus, CopyDocument, Edit, Link, Refresh, Search, View } from '@element-plus/icons-vue'

import {
  getAgentRemoteStatus,
  getAgentRemoteTask,
  getAgentRemoteTaskLogs,
  getAgentRemoteTools,
  listAgentRemotePackages,
  listAgentRemoteTasks,
  probeUnsaved,
} from '../../api/agents'
import NcStatusTag from '../../components/NcStatusTag.vue'
import NcDataTable from '../../components/table/NcDataTable.vue'
import type { NcTableColumn } from '../../components/table/NcTableColumn'
import { useAgentStore } from '../../stores/agents'
import type {
  AgentFormValue,
  AgentItem,
  AgentProbeResult,
  AgentRemotePackage,
  AgentRemoteStatus,
  AgentRemoteTask,
  AgentStatus,
  AgentToolStatus,
  AgentToolsStatus,
} from '../../types/agent'

type AgentToolRow = AgentToolStatus & { name: string }

const store = useAgentStore()
const search = ref('')
const statusFilter = ref<AgentStatus | ''>('')
const enabledFilter = ref<'' | 'enabled' | 'disabled'>('')
const dialogVisible = ref(false)
const drawerVisible = ref(false)
const saving = ref(false)
const probing = ref(false)
const editingId = ref('')
const selected = ref<AgentItem | null>(null)
const probeResult = ref<AgentProbeResult | null>(null)
const remoteTab = ref('overview')
const remoteStatus = ref<AgentRemoteStatus | null>(null)
const remoteTools = ref<AgentToolsStatus | null>(null)
const remoteTasks = ref<AgentRemoteTask[]>([])
const remotePackages = ref<AgentRemotePackage[]>([])
const remoteLoading = ref(false)
const remoteError = ref('')
const remoteFailures = ref(0)
const taskDialogVisible = ref(false)
const selectedTask = ref<AgentRemoteTask | null>(null)
const taskLogs = ref<string[]>([])
const taskDetailLoading = ref(false)
let remoteTimer: number | undefined
let taskTimer: number | undefined
const formRef = ref<FormInstance>()
const form = reactive<AgentFormValue>(emptyForm())
const visibleAgents = computed(() => store.filtered(search.value, statusFilter.value, enabledFilter.value))
const toolRows = computed<AgentToolRow[]>(() => remoteTools.value ? [
  { name: 'MR Collector', ...remoteTools.value.mr_collector },
  { name: 'fping', ...remoteTools.value.fping },
  { name: 'iPerf3', ...remoteTools.value.iperf3 },
] : [])
const agentColumns: NcTableColumn<AgentItem>[] = [
  { key: 'agent', label: 'Agent', valueType: 'name', fixed: 'left' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'platform', label: '平台 / 版本', valueType: 'text' },
  { key: 'latency_ms', label: '延迟', valueType: 'duration', displayValue: (row) => row.latency_ms === null ? '—' : `${row.latency_ms} ms` },
  { key: 'last_seen_at', label: '最近在线', valueType: 'datetime', displayValue: (row) => formatTime(row.last_seen_at) },
  { key: 'note', label: '备注', valueType: 'description', align: 'left', alignmentReason: 'description' },
  { key: 'last_error_message', label: '最近错误', valueType: 'error', align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情', '编辑', '测试', '禁用', '归档'] },
]
const toolColumns: NcTableColumn<AgentToolRow>[] = [
  { key: 'name', label: '工具', valueType: 'name' },
  { key: 'ready', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'version', label: '版本', valueType: 'text' },
  { key: 'path', label: '路径', valueType: 'description', align: 'left', alignmentReason: 'path' },
  { key: 'warning', label: '提示', valueType: 'error', align: 'left', alignmentReason: 'long-text' },
]
const remoteTaskColumns: NcTableColumn<AgentRemoteTask>[] = [
  { key: 'task_id', label: '任务 ID', valueType: 'text' }, { key: 'task_type', label: '类型', valueType: 'text' },
  { key: 'status', label: '状态', valueType: 'status', cellKind: 'tag' },
  { key: 'start_time', label: '开始时间', valueType: 'datetime', displayValue: (row) => formatTime(row.start_time || row.created_at) },
  { key: 'end_time', label: '结束时间', valueType: 'datetime', displayValue: (row) => formatTime(row.end_time) },
  { key: 'error_message', label: '错误摘要', valueType: 'error', align: 'left', alignmentReason: 'long-text' },
  { key: 'actions', label: '操作', valueType: 'actions', cellKind: 'actions', actionLabels: ['详情'] },
]
const packageColumns: NcTableColumn<AgentRemotePackage>[] = [
  { key: 'package_id', label: '采集包 ID', valueType: 'text' }, { key: 'task_type', label: '任务类型', valueType: 'text' },
  { key: 'task_id', label: '任务 ID', valueType: 'text' },
  { key: 'size', label: '大小', valueType: 'number', displayValue: (row) => formatBytes(row.size) },
  { key: 'start_time', label: '开始时间', valueType: 'datetime', displayValue: (row) => formatTime(row.start_time) },
  { key: 'end_time', label: '结束时间', valueType: 'datetime', displayValue: (row) => formatTime(row.end_time) },
]
const rules: FormRules<AgentFormValue> = {
  name: [{ required: true, message: '请输入 Agent 名称', trigger: 'blur' }],
  base_url: [
    { required: true, message: '请输入 Agent 地址', trigger: 'blur' },
    { pattern: /^https?:\/\/[^\s/]+\/?$/i, message: '请输入 http/https 服务根地址', trigger: 'blur' },
  ],
}
const statusOptions: AgentStatus[] = ['ONLINE', 'OFFLINE', 'UNAUTHORIZED', 'UNKNOWN', 'DISABLED']

onMounted(async () => {
  await store.refresh()
  store.connectSocket()
})
onBeforeUnmount(() => {
  store.disconnectSocket()
  clearRemoteTimer()
  clearTaskTimer()
})

watch([drawerVisible, remoteTab], ([visible]) => {
  clearRemoteTimer()
  if (!visible) return
  void refreshRemote()
  const interval = remoteTab.value === 'tasks' ? 2000 : remoteTab.value === 'packages' ? 10000 : 5000
  remoteTimer = window.setInterval(() => void refreshRemote(), interval)
})

watch(taskDialogVisible, (visible) => {
  clearTaskTimer()
  if (!visible) return
  void refreshTaskDetail()
  taskTimer = window.setInterval(() => void refreshTaskDetail(), 1000)
})

function emptyForm(): AgentFormValue {
  return { name: '', base_url: 'http://127.0.0.1:18080', enabled: true, authentication_type: 'none', token: '', tags: [], note: '' }
}

function openCreate(): void {
  editingId.value = ''
  Object.assign(form, emptyForm())
  probeResult.value = null
  dialogVisible.value = true
}

function openEdit(agent: AgentItem): void {
  editingId.value = agent.agent_id
  Object.assign(form, {
    name: agent.name,
    base_url: agent.base_url,
    enabled: agent.enabled,
    authentication_type: agent.authentication_type,
    token: '',
    tags: [...agent.tags],
    note: agent.note,
  })
  probeResult.value = null
  dialogVisible.value = true
}

function openDetail(agent: AgentItem): void {
  selected.value = agent
  remoteTab.value = 'overview'
  remoteStatus.value = null
  remoteTools.value = null
  remoteTasks.value = []
  remotePackages.value = []
  remoteError.value = ''
  remoteFailures.value = 0
  drawerVisible.value = true
}

function clearRemoteTimer(): void {
  if (remoteTimer !== undefined) window.clearInterval(remoteTimer)
  remoteTimer = undefined
}

function clearTaskTimer(): void {
  if (taskTimer !== undefined) window.clearInterval(taskTimer)
  taskTimer = undefined
}

async function refreshRemote(): Promise<void> {
  const agent = selected.value
  if (!agent || remoteLoading.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    if (remoteTab.value === 'overview') remoteStatus.value = await getAgentRemoteStatus(agent.agent_id)
    else if (remoteTab.value === 'tools') remoteTools.value = await getAgentRemoteTools(agent.agent_id)
    else if (remoteTab.value === 'tasks') remoteTasks.value = await listAgentRemoteTasks(agent.agent_id)
    else if (remoteTab.value === 'packages') remotePackages.value = await listAgentRemotePackages(agent.agent_id)
    remoteFailures.value = 0
  } catch (cause) {
    remoteFailures.value += 1
    const message = cause instanceof Error ? cause.message : '读取 Agent 远端状态失败'
    remoteError.value = remoteFailures.value >= 3 ? `连续 ${remoteFailures.value} 次读取失败，远端状态异常：${message}` : message
  } finally {
    remoteLoading.value = false
  }
}

function openTask(task: AgentRemoteTask): void {
  selectedTask.value = task
  taskLogs.value = []
  taskDialogVisible.value = true
}

async function refreshTaskDetail(): Promise<void> {
  const agent = selected.value
  const task = selectedTask.value
  if (!agent || !task || taskDetailLoading.value) return
  taskDetailLoading.value = true
  try {
    const [detail, logs] = await Promise.all([
      getAgentRemoteTask(agent.agent_id, task.task_id),
      getAgentRemoteTaskLogs(agent.agent_id, task.task_id),
    ])
    selectedTask.value = detail
    taskLogs.value = logs.lines
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '读取远端任务详情失败')
    clearTaskTimer()
  } finally {
    taskDetailLoading.value = false
  }
}

function openAgentWeb(): void {
  if (!selected.value) return
  window.open(selected.value.base_url, '_blank', 'noopener,noreferrer')
}

async function copyAgentUrl(): Promise<void> {
  if (!selected.value) return
  try {
    await navigator.clipboard.writeText(selected.value.base_url)
    ElMessage.success('Agent Web 地址已复制')
  } catch {
    ElMessage.error('复制失败，请手工复制地址')
  }
}

async function testFormConnection(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  probing.value = true
  probeResult.value = null
  try {
    probeResult.value = await probeUnsaved({ base_url: form.base_url, authentication_type: form.authentication_type, token: form.token })
    ElMessage.success('连接测试成功')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '连接测试失败')
  } finally {
    probing.value = false
  }
}

async function save(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const payload = { ...form, tags: [...form.tags] }
    if (!payload.token) delete payload.token
    await store.save(payload, editingId.value)
    dialogVisible.value = false
    ElMessage.success(editingId.value ? 'Agent 已更新' : 'Agent 已添加')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '保存 Agent 失败')
  } finally {
    saving.value = false
  }
}

async function probe(agent: AgentItem): Promise<void> {
  try {
    const result = await store.probe(agent.agent_id)
    selected.value = result
    ElMessage.success('Agent 状态已更新')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : 'Agent 探测失败')
  }
}

async function toggle(agent: AgentItem): Promise<void> {
  try {
    await store.toggle(agent)
    ElMessage.success(agent.enabled ? 'Agent 已禁用' : 'Agent 已启用')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '状态修改失败')
  }
}

async function archive(agent: AgentItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`归档 Agent“${agent.name}”？历史任务不会被删除。`, '归档 Agent', { type: 'warning' })
    await store.archive(agent.agent_id)
    ElMessage.success('Agent 已归档')
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    ElMessage.error(cause instanceof Error ? cause.message : '归档失败')
  }
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MiB`
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GiB`
}

function normalizedStatus(value: string): string {
  return value.toUpperCase()
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function capabilityText(capabilities: Record<string, unknown>): string {
  const entries = Object.entries(capabilities)
  if (!entries.length) return '未知（旧 Agent 未上报）'
  return entries.map(([name, value]) => `${name}: ${typeof value === 'boolean' ? (value ? '支持' : '不可用') : JSON.stringify(value)}`).join('；')
}
</script>

<template>
  <section class="agent-center">
    <div class="agent-summary">
      <div><span>Agent 总数</span><strong>{{ store.agents.length }}</strong></div>
      <div><span>在线</span><strong class="success-text">{{ store.onlineCount }}</strong></div>
      <div><span>需关注</span><strong class="danger-text">{{ store.attentionCount }}</strong></div>
      <p><span :class="['status-dot', store.socketConnected ? 'online' : 'offline']"></span>{{ store.socketConnected ? '状态事件已连接' : '状态事件重连中' }}</p>
    </div>

    <el-alert title="连接测试由 NetConsole 后端所在主机发起，浏览器不会直接访问 Agent。" type="info" show-icon :closable="false" />
    <div class="content-card agent-table-card">
      <div class="table-toolbar">
        <div><h2>Agent 管理</h2><p>仅管理控制面与健康状态，本阶段不提供任务启动能力。</p></div>
        <div class="toolbar-actions">
          <el-input v-model="search" :prefix-icon="Search" placeholder="搜索名称、地址、标签" clearable style="width: 230px" />
          <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 138px">
            <el-option v-for="status in statusOptions" :key="status" :label="status" :value="status" />
          </el-select>
          <el-select v-model="enabledFilter" placeholder="全部启用状态" clearable style="width: 150px">
            <el-option label="已启用" value="enabled" /><el-option label="已禁用" value="disabled" />
          </el-select>
          <el-button :icon="Refresh" :loading="store.loading" @click="store.refresh">刷新</el-button>
          <el-button type="primary" :icon="CirclePlus" @click="openCreate">新增 Agent</el-button>
        </div>
      </div>
      <el-alert v-if="store.error" :title="store.error" type="error" show-icon :closable="false" />
      <NcDataTable v-loading="store.loading" table-id="agent-list" route-key="/agents" :data="visibleAgents" :columns="agentColumns" empty-text="暂无 Agent，请先添加">
        <template #cell-agent="{ row }"><strong>{{ row.name }}</strong><small class="secondary-text">{{ row.base_url }}</small></template>
        <template #cell-status="{ row }"><NcStatusTag :status="row.status" /></template>
        <template #cell-platform="{ row }">{{ row.platform || '—' }} {{ row.architecture || '' }}<small class="secondary-text">{{ row.version || '未获取版本' }}</small></template>
        <template #cell-actions="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" :disabled="!row.enabled" @click="probe(row)">测试</el-button>
            <el-button link :type="row.enabled ? 'warning' : 'success'" @click="toggle(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
            <el-button link type="danger" @click="archive(row)">归档</el-button>
        </template>
      </NcDataTable>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑 Agent' : '新增 Agent'" width="min(640px, 92vw)" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" maxlength="120" /></el-form-item>
        <el-form-item label="Agent 地址" prop="base_url"><el-input v-model="form.base_url" placeholder="http://192.168.1.20:18080" /></el-form-item>
        <el-form-item label="认证方式"><el-radio-group v-model="form.authentication_type"><el-radio value="none">无认证</el-radio><el-radio value="token">Token</el-radio></el-radio-group></el-form-item>
        <el-form-item v-if="form.authentication_type === 'token'" label="Agent Token">
          <el-input v-model="form.token" type="password" show-password autocomplete="new-password" placeholder="留空表示编辑时不替换现有会话凭据" />
          <div class="form-hint">Token 仅保存在当前 NetConsole 后端进程内，不写入 agents.db。</div>
        </el-form-item>
        <el-form-item label="标签"><el-select v-model="form.tags" multiple filterable allow-create default-first-option placeholder="输入后回车" style="width: 100%" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="3" maxlength="1000" show-word-limit /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <el-card v-if="probeResult" class="probe-result" shadow="never">
        <strong>连接成功：{{ probeResult.remote_name || probeResult.remote_agent_id }}</strong>
        <p>{{ probeResult.platform }} / {{ probeResult.architecture }} · {{ probeResult.version }} · {{ probeResult.latency_ms }} ms</p>
        <p>{{ capabilityText(probeResult.capabilities) }}</p>
      </el-card>
      <template #footer><el-button :loading="probing" @click="testFormConnection">测试连接</el-button><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" title="Agent 控制中心（只读）" size="min(980px, 96vw)">
      <template v-if="selected">
        <div class="detail-heading">
          <div><h2>{{ selected.name }}</h2><p>{{ selected.base_url }}</p></div>
          <div class="detail-actions">
            <NcStatusTag :status="selected.status" />
            <el-button :icon="Link" @click="openAgentWeb">打开 Agent Web</el-button>
            <el-button :icon="CopyDocument" @click="copyAgentUrl">复制地址</el-button>
            <el-button :icon="Refresh" :loading="remoteLoading" @click="refreshRemote">刷新</el-button>
          </div>
        </div>
        <el-alert v-if="remoteError" :title="remoteError" type="error" show-icon :closable="false" />
        <el-tabs v-model="remoteTab" class="agent-remote-tabs">
          <el-tab-pane label="概览" name="overview">
            <div v-loading="remoteLoading" class="remote-tab-body">
              <el-empty v-if="!remoteStatus" description="暂未读取 Agent 运行状态" :image-size="72" />
              <el-descriptions v-else :column="2" border>
                <el-descriptions-item label="远端 Agent">{{ remoteStatus.agent_name || remoteStatus.agent_id }}</el-descriptions-item>
                <el-descriptions-item label="版本">{{ remoteStatus.version }}</el-descriptions-item>
                <el-descriptions-item label="系统">{{ remoteStatus.os }} / {{ remoteStatus.arch }}</el-descriptions-item>
                <el-descriptions-item label="运行时间">{{ remoteStatus.uptime || '--' }}</el-descriptions-item>
                <el-descriptions-item label="当前任务">{{ remoteStatus.current_tasks }}</el-descriptions-item>
                <el-descriptions-item label="历史任务">{{ remoteStatus.task_count }}</el-descriptions-item>
                <el-descriptions-item label="采集包">{{ remoteStatus.package_count }}</el-descriptions-item>
                <el-descriptions-item label="监听地址">{{ remoteStatus.listen || '--' }}</el-descriptions-item>
                <el-descriptions-item label="数据目录" :span="2">{{ remoteStatus.data_dir || '--' }}</el-descriptions-item>
                <el-descriptions-item label="采集包目录" :span="2">{{ remoteStatus.package_dir || '--' }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </el-tab-pane>
          <el-tab-pane label="工具状态" name="tools">
            <div v-loading="remoteLoading" class="remote-tab-body">
              <el-empty v-if="!remoteTools" description="暂未读取工具状态" :image-size="72" />
              <NcDataTable v-else table-id="agent-tool-status" route-key="/agents" :data="toolRows" :columns="toolColumns" :show-column-settings="false">
                <template #cell-ready="{ row }"><el-tag :type="row.ready ? 'success' : 'danger'">{{ row.ready ? 'READY' : '不可用' }}</el-tag></template>
              </NcDataTable>
            </div>
          </el-tab-pane>
          <el-tab-pane label="远端任务" name="tasks">
            <div v-loading="remoteLoading" class="remote-tab-body">
              <NcDataTable table-id="agent-remote-tasks" route-key="/agents" :data="remoteTasks" :columns="remoteTaskColumns" empty-text="Agent 暂无任务">
                <template #cell-status="{ row }"><NcStatusTag :status="normalizedStatus(row.status)" /></template>
                <template #cell-actions="{ row }"><el-button link type="primary" @click="openTask(row)">详情</el-button></template>
              </NcDataTable>
            </div>
          </el-tab-pane>
          <el-tab-pane label="采集包" name="packages">
            <div v-loading="remoteLoading" class="remote-tab-body">
              <el-alert title="本页只读；下载导入请暂用桌面端现有 Agent 包导入入口。" type="info" show-icon :closable="false" />
              <NcDataTable table-id="agent-remote-packages" route-key="/agents" :data="remotePackages" :columns="packageColumns" empty-text="Agent 暂无采集包" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>

    <el-dialog v-model="taskDialogVisible" title="Agent 任务详情（只读）" width="min(900px, 94vw)" destroy-on-close>
      <div v-if="selectedTask" v-loading="taskDetailLoading">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务 ID" :span="2">{{ selectedTask.task_id }}</el-descriptions-item>
          <el-descriptions-item label="任务类型">{{ selectedTask.task_type }}</el-descriptions-item>
          <el-descriptions-item label="状态"><NcStatusTag :status="normalizedStatus(selectedTask.status)" /></el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(selectedTask.start_time || selectedTask.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(selectedTask.end_time) }}</el-descriptions-item>
          <el-descriptions-item label="采集包">{{ selectedTask.package_id || '--' }}</el-descriptions-item>
          <el-descriptions-item label="错误码">{{ selectedTask.error_code || '--' }}</el-descriptions-item>
          <el-descriptions-item label="错误摘要" :span="2">{{ selectedTask.error_message || '--' }}</el-descriptions-item>
        </el-descriptions>
        <h3 class="remote-section-title">脱敏任务参数</h3>
        <pre class="remote-json">{{ prettyJson(selectedTask.params) }}</pre>
        <h3 class="remote-section-title">日志 tail（每秒刷新）</h3>
        <pre class="remote-log">{{ taskLogs.join('\n') || '暂无日志' }}</pre>
      </div>
    </el-dialog>
  </section>
</template>
