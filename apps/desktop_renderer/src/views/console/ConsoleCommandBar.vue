<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiRequest } from '../../api/client'
import { cloneTerminalSession, createTerminalSession, type TerminalSession, type TerminalSessionConnection } from '../../api/terminal'
import { downloadBackendResource } from '../../platform/runtime'

const props = defineProps<{ sessions: TerminalSession[]; active: TerminalSession | null; selected: string[]; selectedDevices: Array<{ device_uuid: string; name: string }> }>()
const emit = defineEmits<{ opened: [value: TerminalSessionConnection]; selection: [ids: string[]] }>()
type Button = { id: string; name: string; action: string; text: string; color: string; tooltip: string; disable_tooltip: boolean; order: number; enabled: boolean }
type Group = { id: string; name: string; buttons: Button[] }
type Document = { version: number; groups: Group[] }
type Job = { id: string; rows: Array<{ state: string; session_id?: string; name?: string; sent_segments?: number; error?: string }> }
const config = ref<Document>({ version: 1, groups: [] })
const groupId = ref('group-0')
const group = computed(() => config.value.groups.find(item => item.id === groupId.value))
const text = ref('')
const target = ref('current')
const mode = ref('lines')
const interval = ref(200)
const batchExpanded = ref(false)
const managing = ref(false)
const query = ref('')
const latestBatch = ref<Job | null>(null)
const batchActive = computed(() => latestBatch.value?.rows.some(row => ['WAITING', 'RUNNING'].includes(row.state)))
const preview = ref(false)
const pendingButton = ref<Button | null>(null)
const busy = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
let poll: ReturnType<typeof setInterval> | undefined
const pendingJobs = new Map<string, number>()
let refreshing = false
let disposed = false
const activeSessions = computed(() => props.sessions.filter(item => ['CONNECTED', 'RUNNING'].includes(item.state)))
const chosen = computed(() => target.value === 'all' ? activeSessions.value : target.value === 'selected' ? props.sessions.filter(item => props.selected.length ? props.selected.includes(item.session_id) : props.selectedDevices.some(device => device.device_uuid === item.device_uuid)) : props.active ? [props.active] : [])
const filteredButtons = computed(() => (group.value?.buttons || [])
  .filter(button => button.enabled && `${button.name} ${button.text}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))
  .sort((left, right) => left.order - right.order))
async function load() { config.value = await apiRequest<Document>('/api/terminal/quick-buttons'); if (!group.value) groupId.value = config.value.groups[0]?.id || '' }
onMounted(() => { void load().catch(error => ElMessage.error(String(error))) })
onBeforeUnmount(() => { disposed = true; pendingJobs.clear(); if (poll) clearInterval(poll) })
function newButton() {
  group.value?.buttons.push({ id: crypto.randomUUID(), name: '新按钮', action: 'SEND_STRING', text: 'display version\\r', color: '#409eff', tooltip: '', disable_tooltip: false, order: group.value.buttons.length, enabled: true })
}
function duplicate(button: Button) { group.value?.buttons.push({ ...button, id: crypto.randomUUID(), name: `${button.name} 副本`, order: group.value.buttons.length }) }
function reorder(index: number, delta: number) {
  const items = group.value?.buttons
  if (!items || index + delta < 0 || index + delta >= items.length) return
  const [item] = items.splice(index, 1); items.splice(index + delta, 0, item!)
  items.forEach((button, order) => { button.order = order })
}
async function save() { try { config.value = await apiRequest<Document>('/api/terminal/quick-buttons', { method: 'PUT', body: JSON.stringify(config.value) }); ElMessage.success('按钮配置已保存') } catch (error) { ElMessage.error(String(error)) } }
async function reset() { try { await ElMessageBox.confirm('恢复所有默认按钮组？', '恢复默认'); config.value = await apiRequest<Document>('/api/terminal/quick-buttons/reset', { method: 'POST' }) } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(String(error)) } }
async function importConfig(event: Event) {
  const input = event.target as HTMLInputElement
  try {
    const file = input.files?.[0]; if (!file) return
    if (file.size > 1024 * 1024) throw new Error('按钮配置超过 1 MiB')
    config.value = await apiRequest<Document>('/api/terminal/quick-buttons', { method: 'PUT', body: JSON.stringify(JSON.parse(await file.text())) })
    groupId.value = config.value.groups[0]?.id || ''
  } catch (error) { ElMessage.error(String(error)) } finally { input.value = '' }
}
async function exportConfig() { try { await downloadBackendResource({ apiPath: '/api/terminal/quick-buttons/export', suggestedName: 'console-quick-buttons.json' }) } catch (error) { ElMessage.error(String(error)) } }
function requestSend(button: Button | null = null) {
  pendingButton.value = button
  if (button && !batchExpanded.value) {
    target.value = 'current'
    void send()
  } else preview.value = true
}
async function cancelBatch() {
  const id = latestBatch.value?.id
  if (!id || !batchActive.value) return
  try {
    const updated = await apiRequest<Job>(`/api/terminal/batch-sends/${id}/cancel`, { method: 'POST' })
    if (latestBatch.value?.id === id) latestBatch.value = updated
  } catch (error) { ElMessage.error(String(error)) }
}
function reportCompletion(job: Job): boolean {
  if (job.rows.some(item => ['WAITING', 'RUNNING'].includes(item.state))) return false
  const sent = job.rows.filter(item => item.state === 'SENT').length
  const remaining = job.rows.length - sent
  if (!remaining && sent) ElMessage.success(`命令已写入 ${sent} 个终端`)
  else if (sent) ElMessage.warning(`命令已写入 ${sent} 个终端，${remaining} 个目标未确认发送`)
  else if (remaining) {
    const reason = job.rows.find(item => item.error)?.error
    ElMessage.error(reason || (job.rows.every(item => item.state === 'CANCELLED_PENDING') ? '发送已取消' : '发送失败'))
  }
  return true
}
async function refreshJobs() {
  if (refreshing || disposed) return
  refreshing = true
  try {
    await Promise.all([...pendingJobs.keys()].map(async id => {
      try {
        const result = await apiRequest<Job>(`/api/terminal/batch-sends/${id}`)
        if (disposed) return
        if (latestBatch.value?.id === id) latestBatch.value = result
        pendingJobs.set(id, 0)
        if (reportCompletion(result)) pendingJobs.delete(id)
      } catch {
        if (disposed) return
        const failures = (pendingJobs.get(id) || 0) + 1
        if (failures >= 10) {
          pendingJobs.delete(id)
          ElMessage.warning('暂时无法获取发送状态，请检查终端回显；不会自动重发命令')
        } else pendingJobs.set(id, failures)
      }
    }))
  } finally {
    refreshing = false
    if (!pendingJobs.size && poll) { clearInterval(poll); poll = undefined }
  }
}
async function waitConnected(created: TerminalSessionConnection) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    const result = await apiRequest<{ items: TerminalSession[] }>('/api/terminal/sessions')
    const session = result.items.find(item => item.session_id === created.session.session_id)
    if (session && ['CONNECTED', 'RUNNING'].includes(session.state)) return
    if (!session) {
      const detail = await apiRequest<TerminalSession>(`/api/terminal/history/${created.session.session_id}`)
      if (['FAILED', 'CLOSED', 'DISCONNECTED'].includes(detail.state)) throw new Error(detail.error_message || '新终端连接失败')
    }
    await new Promise(done => setTimeout(done, 150))
  }
  throw new Error('新终端连接超时，未发送命令')
}
async function send() {
  if (busy.value) return
  busy.value = true
  try {
    let ids = chosen.value.map(item => item.session_id)
    if (['new', 'window'].includes(target.value)) {
      if (target.value === 'window' && !window.netconsoleDesktop?.openTerminalWindow) throw new Error('独立终端窗口需要 Electron')
      const createdSessions: TerminalSessionConnection[] = []
      if (target.value === 'new' && props.selectedDevices.length) {
        for (const device of props.selectedDevices) {
          try { const created = await createTerminalSession(device.device_uuid); createdSessions.push(created); emit('opened', created) }
          catch (error) { ElMessage.error(`${device.name}: ${String(error)}`) }
        }
      } else {
        if (!props.active) throw new Error('请先选择目标会话')
        const created = await cloneTerminalSession(props.active.session_id)
        createdSessions.push(created)
        if (target.value === 'window') {
          const bridge = window.netconsoleDesktop
          try {
            const result = await bridge!.openTerminalWindow!(created.session.session_id)
            if (!result.success) throw new Error(result.error || '新窗口创建失败')
          } catch (error) {
            await apiRequest(`/api/terminal/sessions/${created.session.session_id}`, { method: 'DELETE' }).catch(() => undefined)
            throw error
          }
        } else emit('opened', created)
      }
      ids = []
      for (const created of createdSessions) {
        try { await waitConnected(created) }
        catch (error) { ElMessage.error(`${created.session.device_name}: ${String(error)}`) }
        if (disposed) return
        ids.push(created.session.session_id)
      }
    }
    if (!ids.length) throw new Error('未选择终端或没有可发送的目标')
    const button = pendingButton.value
    const submitted = await apiRequest<Job>('/api/terminal/batch-sends', { method: 'POST', body: JSON.stringify({ session_ids: ids, text: text.value, mode: mode.value, interval_ms: interval.value, scope: ['new', 'window'].includes(target.value) ? 'new' : target.value, ...(button ? { group_id: groupId.value, button_id: button.id } : {}) }) })
    if (batchExpanded.value) latestBatch.value = submitted
    preview.value = false
    if (!disposed && !reportCompletion(submitted)) {
      ElMessage.info('命令发送中')
      pendingJobs.set(submitted.id, 0)
      if (!poll) poll = setInterval(() => void refreshJobs(), 300)
    }
  } catch (error) { ElMessage.error(String(error)) } finally { busy.value = false }
}
async function newGroup() { const { value } = await ElMessageBox.prompt('按钮组名称', '新增按钮组'); const item = { id: crypto.randomUUID(), name: value, buttons: [] }; config.value.groups.push(item); groupId.value = item.id }
</script>

<template>
  <section class="command-bar">
    <div class="quick-buttons"><button type="button" @click="managing = true">管理按钮</button></div>
    <div v-show="batchExpanded" class="command-input"><select v-model="target" aria-label="发送目标"><option value="current">当前会话</option><option value="selected">选中会话</option><option value="all">所有已连接会话</option><option value="new">新建终端标签</option><option value="window">独立终端窗口</option></select><textarea v-model="text" rows="2" aria-label="批量命令" placeholder="输入或粘贴命令" @keydown.enter.exact.prevent="requestSend()" /><select v-model="mode" aria-label="发送模式"><option value="block">整段发送</option><option value="lines">逐行 + CR</option></select><select v-if="mode === 'lines'" v-model="interval" aria-label="发送间隔"><option :value="0">立即</option><option :value="200">200ms</option><option :value="500">500ms</option><option :value="1000">1000ms</option></select><el-button type="primary" :loading="busy" @click="requestSend()">预览发送</el-button></div>
    <el-dialog v-model="preview" title="发送预览" width="min(700px,90vw)"><p>{{ target }} · {{ target === 'new' && selectedDevices.length ? selectedDevices.length : chosen.length }} 个目标</p><div>{{ target === 'new' && selectedDevices.length ? selectedDevices.map(item => item.name).join('、') : chosen.map(item => item.session_name || item.device_name).join('、') }}</div><pre>{{ pendingButton?.text || text }}</pre><template #footer><el-button @click="preview = false">取消</el-button><el-button type="primary" :loading="busy" @click="send">确认发送</el-button></template></el-dialog>
    <section v-if="batchExpanded && latestBatch" class="dispatch-results" aria-label="批量写入状态">
      <button type="button" :disabled="!batchActive" @click="cancelBatch">取消剩余发送</button>
      <ul>
        <li v-for="row in latestBatch.rows" :key="row.session_id">
          <span>{{ row.name || row.session_id }}</span>
          <span>{{ row.state }} · {{ row.sent_segments || 0 }}</span>
          <span v-if="row.error">{{ row.error }}</span>
        </li>
      </ul>
    </section>
    <el-dialog v-model="managing" title="快捷按钮管理" width="min(1100px,96vw)">
      <div class="manage-toolbar">
        <input v-model="query" aria-label="搜索快捷命令" placeholder="搜索快捷命令" />
        <el-button @click="batchExpanded = !batchExpanded; managing = false">{{ batchExpanded ? '收起批量命令' : '批量命令' }}</el-button>
      </div>
      <div class="quick-buttons">
        <button v-for="button in filteredButtons" :key="button.id" type="button" :disabled="busy" :style="{ borderColor: button.color, color: button.color }" :title="button.disable_tooltip ? undefined : button.tooltip" @click="requestSend(button)">{{ button.name }}</button>
      </div>
      <div class="manage-toolbar"><select v-model="groupId"><option v-for="item in config.groups" :key="item.id" :value="item.id">{{ item.name }}</option></select><el-button @click="newGroup">新增组</el-button><el-input v-if="group" v-model="group.name" style="width:160px" /><el-button @click="newButton">新增按钮</el-button><el-button @click="importInput?.click()">导入 JSON</el-button><input ref="importInput" hidden type="file" accept=".json" @change="importConfig" /><el-button @click="exportConfig">导出 JSON</el-button><el-button @click="reset">恢复默认</el-button></div><div class="button-editor" v-for="(button,index) in group?.buttons" :key="button.id"><input v-model="button.name" aria-label="按钮名称" /><select v-model="button.action"><option value="SEND_STRING">Send String</option></select><textarea v-model="button.text" aria-label="发送字符串" rows="2" /><input v-model="button.color" type="color" aria-label="按钮颜色" /><input v-model="button.tooltip" placeholder="Tooltip" /><label><input v-model="button.disable_tooltip" type="checkbox" />不提示</label><label><input v-model="button.enabled" type="checkbox" />启用</label><button @click="duplicate(button)">复制</button><button @click="reorder(index,-1)">↑</button><button @click="reorder(index,1)">↓</button><button @click="group?.buttons.splice(index,1)">删除</button></div><template #footer><el-button @click="managing = false">关闭</el-button><el-button type="primary" @click="save">保存配置</el-button></template>
    </el-dialog>
  </section>
</template>
<style scoped>
.command-bar { border-top: 1px solid var(--nc-border); background: var(--nc-bg-code-header); color: var(--nc-text-primary); padding: 5px 8px; }
.quick-buttons,.command-input,.manage-toolbar { display:flex;align-items:center;gap:6px; }
.quick-buttons { overflow-x:auto;white-space:nowrap;margin-bottom:5px; }
.quick-buttons button { border:1px solid var(--nc-border);border-radius:4px;padding:3px 9px;background:var(--nc-bg-panel);cursor:pointer; }
.command-input textarea { flex:1;min-width:120px;resize:vertical;max-height:130px; }
textarea,select,input { background:var(--nc-bg-panel);color:var(--nc-text-primary);border:1px solid var(--nc-border);border-radius:4px;padding:4px; }
.button-editor { display:flex;align-items:center;gap:5px;min-width:950px;padding:8px 0; }
.button-editor textarea { flex:1; }.button-editor input:not([type]) { width:110px; }
pre { white-space:pre-wrap;max-height:50vh;overflow:auto; }
.dispatch-results { max-height: 9rem; overflow: auto; }
.dispatch-results li { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
