<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CirclePlus, Edit, Refresh, Search, View } from '@element-plus/icons-vue'

import { probeUnsaved } from '../../api/agents'
import NcStatusTag from '../../components/NcStatusTag.vue'
import { useAgentStore } from '../../stores/agents'
import type { AgentFormValue, AgentItem, AgentProbeResult, AgentStatus } from '../../types/agent'

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
const formRef = ref<FormInstance>()
const form = reactive<AgentFormValue>(emptyForm())
const visibleAgents = computed(() => store.filtered(search.value, statusFilter.value, enabledFilter.value))
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
onBeforeUnmount(() => store.disconnectSocket())

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
  drawerVisible.value = true
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

function formatTime(value: string): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
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
      <el-table v-loading="store.loading" :data="visibleAgents" empty-text="暂无 Agent，请先添加" stripe>
        <el-table-column label="Agent" min-width="180"><template #default="{ row }"><strong>{{ row.name }}</strong><small class="secondary-text">{{ row.base_url }}</small></template></el-table-column>
        <el-table-column label="状态" width="104"><template #default="{ row }"><NcStatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="平台 / 版本" min-width="150"><template #default="{ row }">{{ row.platform || '--' }} {{ row.architecture || '' }}<small class="secondary-text">{{ row.version || '未获取版本' }}</small></template></el-table-column>
        <el-table-column label="延迟" width="90"><template #default="{ row }">{{ row.latency_ms === null ? '--' : `${row.latency_ms} ms` }}</template></el-table-column>
        <el-table-column label="最近在线" width="174"><template #default="{ row }">{{ formatTime(row.last_seen_at) }}</template></el-table-column>
        <el-table-column prop="note" label="备注" min-width="130" show-overflow-tooltip />
        <el-table-column label="最近错误" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ row.last_error_message || '--' }}</template></el-table-column>
        <el-table-column label="操作" width="275" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :icon="View" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" :disabled="!row.enabled" @click="probe(row)">测试</el-button>
            <el-button link :type="row.enabled ? 'warning' : 'success'" @click="toggle(row)">{{ row.enabled ? '禁用' : '启用' }}</el-button>
            <el-button link type="danger" @click="archive(row)">归档</el-button>
          </template>
        </el-table-column>
      </el-table>
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

    <el-drawer v-model="drawerVisible" title="Agent 详情" size="min(720px, 92vw)">
      <template v-if="selected">
        <div class="detail-heading"><div><h2>{{ selected.name }}</h2><p>{{ selected.base_url }}</p></div><NcStatusTag :status="selected.status" /></div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="启用状态">{{ selected.enabled ? '已启用' : '已禁用' }}</el-descriptions-item>
          <el-descriptions-item label="认证">{{ selected.authentication_type === 'token' ? (selected.has_credential ? 'Token 已加载' : 'Token 需重新录入') : '无认证' }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ selected.platform || '--' }}</el-descriptions-item><el-descriptions-item label="架构">{{ selected.architecture || '--' }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ selected.version || '--' }}</el-descriptions-item><el-descriptions-item label="延迟">{{ selected.latency_ms === null ? '--' : `${selected.latency_ms} ms` }}</el-descriptions-item>
          <el-descriptions-item label="最近在线">{{ formatTime(selected.last_seen_at) }}</el-descriptions-item><el-descriptions-item label="最近检查">{{ formatTime(selected.last_checked_at) }}</el-descriptions-item>
          <el-descriptions-item label="能力" :span="2">{{ capabilityText(selected.capabilities) }}</el-descriptions-item>
          <el-descriptions-item label="最近错误" :span="2">{{ selected.last_error_message || '--' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ selected.note || '--' }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </section>
</template>
