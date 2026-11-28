<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiRequest } from '../../api/client'
import { cloneTerminalSession, createTerminalSession, type TerminalSession, type TerminalSessionConnection } from '../../api/terminal'
import { downloadBackendResource } from '../../platform/runtime'
import { launchExternalTool, listExternalTools } from '../../api/externalTools'
import type { ExternalToolView } from '../../types/externalTools'
import { consoleToolNeedsPassword, MENU_FUNCTIONS, parseSendString, validateConsoleButtonBar, type ConsoleButtonBarDocument } from './consoleButtonBar'
import { parseConsoleRunScriptJson } from './consoleRunScript'
import { consoleBatchStatusLabel, t } from '../../i18n/runtime'

const props = defineProps<{ sessions: TerminalSession[]; active: TerminalSession | null; selected: string[]; selectedDevices: Array<{ device_uuid: string; name: string }> }>()
const emit = defineEmits<{ opened: [value: TerminalSessionConnection]; selection: [ids: string[]]; menuAction: [id: typeof MENU_FUNCTIONS[number]] }>()
type Button = ConsoleButtonBarDocument['groups'][number]['buttons'][number]
type Group = ConsoleButtonBarDocument['groups'][number]
type Document = ConsoleButtonBarDocument
type Job = { id: string; state?: string; rows: Array<{ state: string; session_id?: string; name?: string; address?: string; sent_segments?: number; error?: string; command?: string; output?: string; duration_ms?: number }> }
const config = ref<Document>({ version: 2, groups: [] })
const externalTools = ref<ExternalToolView[]>([])
const groupId = ref('group-0')
const group = computed(() => config.value.groups.find(item => item.id === groupId.value))
const text = ref('')
const target = ref('current')
const mode = ref('lines')
const interval = ref(200)
const executionMode = ref<'sequential' | 'concurrent'>('concurrent')
const maxConcurrency = ref(4)
const deviceTimeout = ref(15)
const totalTimeout = ref(300)
const maxRetries = ref(0)
const failPolicy = ref<'continue' | 'stop'>('continue')
const batchExpanded = ref(false)
const buttonBarExpanded = ref(false)
const managing = ref(false)
const query = ref('')
const latestBatch = ref<Job | null>(null)
const batchActive = computed(() => latestBatch.value?.rows.some(row => ['WAITING', 'RUNNING'].includes(row.state)))
const batchPaused = computed(() => latestBatch.value?.state === 'PAUSED')
const preview = ref(false)
const pendingButton = ref<Button | null>(null)
const busy = ref(false)
const importInput = ref<HTMLInputElement | null>(null)
const scriptInput = ref<HTMLInputElement | null>(null)
const selectedScriptButton = ref<Button | null>(null)
const scriptDialog = ref(false)
const scriptRunning = ref(false)
const scriptOutput = ref<string[]>([])
const scriptStatus = ref('')
let stopScriptRequested = false
let activeScriptJobId = ''
let poll: ReturnType<typeof setInterval> | undefined
const pendingJobs = new Map<string, number>()
let refreshing = false
let disposed = false
const activeSessions = computed(() => props.sessions.filter(item => ['CONNECTED', 'RUNNING'].includes(item.state)))
const chosen = computed(() => target.value === 'all' ? activeSessions.value : target.value === 'selected' ? props.sessions.filter(item => props.selected.length ? props.selected.includes(item.session_id) : props.selectedDevices.some(device => device.device_uuid === item.device_uuid)) : props.active ? [props.active] : [])
const filteredButtons = computed(() => (group.value?.buttons || [])
  .filter(button => button.enabled && `${button.name} ${button.text}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))
  .sort((left, right) => left.order - right.order))
const consoleText = (key: string, fallback: string) => t(`console.${key}`, fallback)
async function load() {
  config.value = validateConsoleButtonBar(await apiRequest<unknown>('/api/terminal/quick-buttons'))
  if (!group.value) groupId.value = config.value.groups[0]?.id || ''
  if (window.netconsoleDesktop?.listExternalTools) {
    externalTools.value = (await listExternalTools()).tools
  }
}
onMounted(() => { void load().catch(error => ElMessage.error(String(error))) })
onBeforeUnmount(() => {
  disposed = true
  pendingJobs.clear()
  if (poll) clearInterval(poll)
  if (scriptRunning.value) void stopScript()
})
function newButton() {
  group.value?.buttons.push({ id: crypto.randomUUID(), name: '新按钮', action: 'SEND_STRING', text: 'display version\\r', launch_with_session_context: false, color: '#409eff', tooltip: '', disable_tooltip: false, order: group.value.buttons.length, enabled: true })
}
function duplicate(button: Button) { group.value?.buttons.push({ ...button, id: crypto.randomUUID(), name: `${button.name} 副本`, order: group.value.buttons.length }) }
function reorder(index: number, delta: number) {
  const items = group.value?.buttons
  if (!items || index + delta < 0 || index + delta >= items.length) return
  const [item] = items.splice(index, 1); items.splice(index + delta, 0, item!)
  items.forEach((button, order) => { button.order = order })
}
async function save() { try { const valid = validateConsoleButtonBar(config.value); config.value = validateConsoleButtonBar(await apiRequest<unknown>('/api/terminal/quick-buttons', { method: 'PUT', body: JSON.stringify(valid) })); ElMessage.success('按钮配置已保存') } catch (error) { ElMessage.error(String(error)) } }
async function reset() { try { await ElMessageBox.confirm('恢复所有默认按钮组？', '恢复默认'); config.value = validateConsoleButtonBar(await apiRequest<unknown>('/api/terminal/quick-buttons/reset', { method: 'POST' })) } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(String(error)) } }
async function importConfig(event: Event) {
  const input = event.target as HTMLInputElement
  try {
    const file = input.files?.[0]; if (!file) return
    if (file.size > 1024 * 1024) throw new Error('按钮配置超过 1 MiB')
    const imported = validateConsoleButtonBar(JSON.parse(await file.text()))
    config.value = validateConsoleButtonBar(await apiRequest<unknown>('/api/terminal/quick-buttons', { method: 'PUT', body: JSON.stringify(imported) }))
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
function activateButton(button: Button) {
  if (button.action === 'MENU_FUNCTION') {
    if ((MENU_FUNCTIONS as readonly string[]).includes(button.text)) emit('menuAction', button.text as typeof MENU_FUNCTIONS[number])
    return
  }
  if (button.action === 'LAUNCH_APPLICATION') {
    void launchApplication(button)
    return
  }
  if (button.action === 'RUN_SCRIPT') {
    void runScript(button.text)
    return
  }
  requestSend(button)
}
async function launchApplication(button: Button) {
  try {
    if (!window.netconsoleDesktop?.launchExternalTool) throw new Error('启动外部应用需要 Electron')
    if (button.launch_with_session_context && !props.active) throw new Error('请先打开一个终端会话')
    const toolId = button.text
    const tool = externalTools.value.find(item => item.id === toolId)
    if (!tool) throw new Error('映射按钮引用的 External Tool 不存在')
    const context = button.launch_with_session_context ? {
      host: props.active?.address || '',
      address: props.active?.address || '',
      backup_host: props.active?.backup_address || '',
      backup_address: props.active?.backup_address || '',
      port: props.active?.port || 0,
      username: props.active?.username || '',
      password: '',
    } : undefined
    let password = ''
    if (context && consoleToolNeedsPassword(tool.arguments)) {
      const { value } = await ElMessageBox.prompt('密码仅用于本次外部程序启动，不会保存或写入日志。', '输入外部终端密码', {
        inputType: 'password',
        confirmButtonText: '启动',
        cancelButtonText: '取消',
      })
      password = value
    }
    const result = await launchExternalTool(toolId, 'normal', context ? { ...context, password } : undefined)
    if (!result.success) throw new Error(result.error || '外部应用启动失败')
    ElMessage.success('外部应用已启动')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error instanceof Error ? error.message : String(error))
  }
}
function appendScriptOutput(value: string) {
  const current = scriptOutput.value.join('')
  const available = Math.max(0, 256 * 1024 - current.length)
  if (available) scriptOutput.value.push(value.slice(0, available))
}
async function waitForScriptDelay(milliseconds: number, deadline: number): Promise<void> {
  const end = Math.min(Date.now() + milliseconds, deadline)
  while (!stopScriptRequested && Date.now() < end) {
    await new Promise(resolve => setTimeout(resolve, Math.min(100, end - Date.now())))
  }
  if (Date.now() >= deadline && !stopScriptRequested) throw new Error('脚本运行超过 15 分钟')
}
async function runScript(source: string) {
  if (scriptRunning.value) return
  let script
  try {
    script = parseConsoleRunScriptJson(source)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
    return
  }
  const session = props.active
  if (!session || !['RUNNING', 'CONNECTED'].includes(session.state)) {
    ElMessage.error('请先打开并连接目标终端')
    return
  }
  try {
    await ElMessageBox.confirm(`脚本将向 ${session.device_name} 发送 ${script.steps.filter(step => step.type === 'SEND_STRING').length} 个命令，确认继续？`, '运行 Console 脚本', { type: 'warning' })
  } catch {
    return
  }

  scriptDialog.value = true
  scriptRunning.value = true
  scriptStatus.value = '运行中'
  scriptOutput.value = []
  stopScriptRequested = false
  activeScriptJobId = ''
  const deadline = Date.now() + 900_000
  try {
    for (const [index, step] of script.steps.entries()) {
      if (stopScriptRequested) break
      if (Date.now() >= deadline) throw new Error('脚本运行超过 15 分钟')
      if (step.type === 'WAIT') {
        scriptStatus.value = `等待 ${step.milliseconds} ms（${index + 1}/${script.steps.length}）`
        await waitForScriptDelay(step.milliseconds, deadline)
        continue
      }

      scriptStatus.value = `发送步骤 ${index + 1}/${script.steps.length}`
      const job = await apiRequest<Job>('/api/terminal/batch-sends', {
        method: 'POST',
        body: JSON.stringify({ session_ids: [session.session_id], text: step.text, mode: 'escaped', interval_ms: 0, execution_mode: 'sequential', max_concurrency: 1, device_timeout: 15, total_timeout: 600, max_retries: 0, fail_policy: 'stop', scope: 'current' }),
      })
      activeScriptJobId = job.id
      let current = job
      while (current.rows.some(row => ['WAITING', 'RUNNING'].includes(row.state))) {
        if (stopScriptRequested) {
          await apiRequest(`/api/terminal/batch-sends/${job.id}/cancel`, { method: 'POST' }).catch(() => undefined)
          break
        }
        if (Date.now() >= deadline) {
          await apiRequest(`/api/terminal/batch-sends/${job.id}/cancel`, { method: 'POST' }).catch(() => undefined)
          throw new Error('脚本运行超过 15 分钟')
        }
        await new Promise(resolve => setTimeout(resolve, 200))
        current = await apiRequest<Job>(`/api/terminal/batch-sends/${job.id}`)
      }
      const row = current.rows[0]
      if (row?.output) appendScriptOutput(row.output)
      if (row?.state !== 'SENT' && !stopScriptRequested) throw new Error(row?.error || `脚本步骤 ${index + 1} 未能确认写入`)
      activeScriptJobId = ''
    }
    scriptStatus.value = stopScriptRequested ? '已停止' : '完成'
  } catch (error) {
    scriptStatus.value = '失败'
    appendScriptOutput(`\n${error instanceof Error ? error.message : String(error)}`)
  } finally {
    scriptRunning.value = false
    activeScriptJobId = ''
  }
}
async function stopScript() {
  if (!scriptRunning.value) return
  stopScriptRequested = true
  scriptStatus.value = '正在停止'
  if (activeScriptJobId) {
    await apiRequest(`/api/terminal/batch-sends/${activeScriptJobId}/cancel`, { method: 'POST' }).catch(() => undefined)
  }
}
async function importScript(event: Event) {
  const input = event.target as HTMLInputElement
  try {
    const file = input.files?.[0]
    if (!file || !selectedScriptButton.value) return
    if (file.size > 65_536) throw new Error('脚本不能超过 64 KiB')
    const source = await file.text()
    parseConsoleRunScriptJson(source)
    selectedScriptButton.value.text = source
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    input.value = ''
    selectedScriptButton.value = null
  }
}
async function cancelBatch() {
  const id = latestBatch.value?.id
  if (!id || !batchActive.value) return
  try {
    const updated = await apiRequest<Job>(`/api/terminal/batch-sends/${id}/cancel`, { method: 'POST' })
    if (latestBatch.value?.id === id) latestBatch.value = updated
  } catch (error) { ElMessage.error(String(error)) }
}
async function toggleBatchPause() {
  const job = latestBatch.value
  if (!job || !batchActive.value && !batchPaused.value) return
  const action = batchPaused.value ? 'resume' : 'pause'
  try {
    latestBatch.value = await apiRequest<Job>(`/api/terminal/batch-sends/${job.id}/${action}`, { method: 'POST' })
  } catch (error) { ElMessage.error(String(error)) }
}
async function exportBatch(format: 'csv' | 'txt') {
  const id = latestBatch.value?.id
  if (!id) return
  try {
    await downloadBackendResource({ apiPath: `/api/terminal/batch-sends/${id}/export?format=${format}`, suggestedName: `console-batch-${id}.${format}` })
  } catch (error) { ElMessage.error(String(error)) }
}
async function retryRow(row: Job['rows'][number]) {
  const id = latestBatch.value?.id
  if (!id || row.state !== 'FAILED' || !row.session_id) return
  try {
    const retry = await apiRequest<Job>(`/api/terminal/batch-sends/${id}/retry/${encodeURIComponent(row.session_id)}`, { method: 'POST' })
    latestBatch.value = retry
    if (!reportCompletion(retry)) {
      pendingJobs.set(retry.id, 0)
      if (!poll) poll = setInterval(() => void refreshJobs(), 300)
    }
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
    if (button) parseSendString(button.text)
    const submitted = await apiRequest<Job>('/api/terminal/batch-sends', { method: 'POST', body: JSON.stringify({ session_ids: ids, text: text.value, mode: mode.value, interval_ms: interval.value, execution_mode: executionMode.value, max_concurrency: maxConcurrency.value, device_timeout: deviceTimeout.value, total_timeout: totalTimeout.value, max_retries: maxRetries.value, fail_policy: failPolicy.value, scope: ['new', 'window'].includes(target.value) ? 'new' : target.value, ...(button ? { group_id: groupId.value, button_id: button.id } : {}) }) })
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
    <div class="quick-buttons">
      <button type="button" @click="managing = true">管理按钮</button>
      <button type="button" :aria-expanded="buttonBarExpanded" @click="buttonBarExpanded = !buttonBarExpanded">{{ buttonBarExpanded ? '收起按钮栏' : '显示按钮栏' }}</button>
    </div>
    <div v-if="buttonBarExpanded" class="mapped-button-bar" aria-label="映射按钮栏">
      <select v-model="groupId" aria-label="按钮栏分组">
        <option v-for="item in config.groups" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
      <button
        v-for="button in filteredButtons"
        :key="button.id"
        type="button"
        :disabled="busy || !active || active.state !== 'RUNNING' && active.state !== 'CONNECTED'"
        :style="{ borderColor: button.color, color: button.color }"
        :title="button.disable_tooltip ? undefined : button.tooltip"
        @click="activateButton(button)"
      >{{ button.name }}</button>
    </div>
    <div v-show="batchExpanded" class="batch-panel">
      <div v-show="batchExpanded" class="command-input"><select v-model="target" aria-label="发送目标"><option value="current">当前会话</option><option value="selected">选中会话</option><option value="all">所有已连接会话</option><option value="new">新建终端标签</option><option value="window">独立终端窗口</option></select><textarea v-model="text" rows="2" aria-label="批量命令" placeholder="输入或粘贴命令" @keydown.enter.exact.prevent="requestSend()" /><select v-model="mode" aria-label="发送模式"><option value="block">整段发送</option><option value="lines">逐行 + CR</option></select><select v-if="mode === 'lines'" v-model="interval"><option :value="0">立即</option><option :value="200">200ms</option><option :value="500">500ms</option><option :value="1000">1000ms</option></select><el-button type="primary" :loading="busy" @click="requestSend()">预览发送</el-button></div>
      <div class="batch-options"><label>执行<select v-model="executionMode" aria-label="批量执行方式"><option value="concurrent">并发</option><option value="sequential">顺序</option></select></label><label>最大并发<input v-model.number="maxConcurrency" aria-label="最大并发数" type="number" min="1" max="16" :disabled="executionMode === 'sequential'"></label><label>单设备超时<input v-model.number="deviceTimeout" aria-label="单设备超时" type="number" min="1" max="300">秒</label><label>总超时<input v-model.number="totalTimeout" aria-label="批量总超时" type="number" min="1" max="3600">秒</label><label>失败重试<input v-model.number="maxRetries" aria-label="失败重试次数" type="number" min="0" max="3"></label><label>失败后<select v-model="failPolicy" aria-label="失败后的处理"><option value="continue">继续</option><option value="stop">停止后续</option></select></label></div>
    </div>
    <el-dialog v-model="preview" title="发送预览" width="min(700px,90vw)"><p>{{ target }} · {{ target === 'new' && selectedDevices.length ? selectedDevices.length : chosen.length }} 个目标</p><div>{{ target === 'new' && selectedDevices.length ? selectedDevices.map(item => item.name).join('、') : chosen.map(item => item.session_name || item.device_name).join('、') }}</div><pre>{{ pendingButton?.text || text }}</pre><template #footer><el-button @click="preview = false">取消</el-button><el-button type="primary" :loading="busy" @click="send">确认发送</el-button></template></el-dialog>
    <el-dialog v-model="scriptDialog" title="Console 脚本运行" width="min(760px,92vw)" :close-on-click-modal="!scriptRunning">
      <p>{{ scriptStatus }}</p>
      <pre class="script-output">{{ scriptOutput.join('') || '等待脚本输出' }}</pre>
      <template #footer><el-button :disabled="scriptRunning" @click="scriptDialog = false">关闭</el-button><el-button v-if="scriptRunning" type="danger" @click="stopScript">停止脚本</el-button></template>
    </el-dialog>
    <section v-if="batchExpanded && latestBatch" class="dispatch-results" aria-label="批量写入状态">
      <div class="batch-actions"><button type="button" :disabled="!batchActive && !batchPaused" @click="toggleBatchPause">{{ batchPaused ? '恢复' : '暂停' }}</button><button type="button" :disabled="!batchActive && !batchPaused" @click="cancelBatch">取消剩余发送</button><button type="button" @click="exportBatch('csv')">导出 CSV</button><button type="button" @click="exportBatch('txt')">导出 TXT</button></div>
      <ul>
        <li v-for="row in latestBatch.rows" :key="row.session_id">
          <details><summary>{{ row.name || row.session_id }} · {{ row.address }} · {{ consoleBatchStatusLabel(row.state) }} · {{ row.duration_ms ?? '—' }} ms</summary><p>{{ row.command }}</p><pre>{{ row.output || row.error || '等待设备回显' }}</pre><button v-if="row.state === 'FAILED' && !row.sent_segments" type="button" @click="retryRow(row)">重试该设备</button></details>
        </li>
      </ul>
    </section>
    <el-dialog v-model="managing" title="快捷按钮管理" width="min(1100px,96vw)">
      <div class="manage-toolbar">
        <input v-model="query" aria-label="搜索快捷命令" placeholder="搜索快捷命令" />
        <el-button @click="batchExpanded = !batchExpanded; managing = false">{{ batchExpanded ? '收起批量命令' : '批量命令' }}</el-button>
      </div>
      <div class="quick-buttons">
        <button v-for="button in filteredButtons" :key="button.id" type="button" :disabled="busy" :style="{ borderColor: button.color, color: button.color }" :title="button.disable_tooltip ? undefined : button.tooltip" @click="activateButton(button)">{{ button.name }}</button>
      </div>
      <div class="manage-toolbar">
        <select v-model="groupId"><option v-for="item in config.groups" :key="item.id" :value="item.id">{{ item.name }}</option></select>
        <el-button @click="newGroup">新增组</el-button>
        <el-input v-if="group" v-model="group.name" aria-label="分组名称" style="width:160px" />
        <el-button @click="newButton">{{ consoleText('button.add', '新增按钮') }}</el-button>
        <el-button @click="importInput?.click()">{{ consoleText('button.import', '导入配置') }}</el-button>
        <input ref="importInput" hidden type="file" accept=".json" @change="importConfig" />
        <el-button @click="exportConfig">{{ consoleText('button.export', '导出配置') }}</el-button>
        <el-button @click="reset">{{ consoleText('button.reset', '恢复默认') }}</el-button>
      </div>
      <div class="button-editor" v-for="(button,index) in group?.buttons" :key="button.id">
        <input v-model="button.name" aria-label="按钮名称" />
        <select v-model="button.action">
          <option value="SEND_STRING">{{ consoleText('button.send_string', '发送字符串') }}</option>
          <option value="MENU_FUNCTION">{{ consoleText('button.menu_function', '菜单功能') }}</option>
          <option value="LAUNCH_APPLICATION">{{ consoleText('button.launch_application', '启动外部程序') }}</option>
          <option value="RUN_SCRIPT">{{ consoleText('button.run_script', '运行脚本') }}</option>
        </select>
        <textarea v-if="button.action === 'SEND_STRING'" v-model="button.text" aria-label="发送字符串" rows="2" title="示例 display\sclock\r\p250display\sversion\r。支持 \r 回车、\n 换行、\s 空格、\t 制表、\e ESC、\b 退格、\\ 反斜杠。单独 \p 暂停 1 秒。" />
        <select v-else-if="button.action === 'MENU_FUNCTION'" v-model="button.text" aria-label="菜单功能">
          <option v-for="id in MENU_FUNCTIONS" :key="id" :value="id">{{ consoleText(`button.${id.replaceAll('-', '_')}`, ({ find: '查找', 'select-all': '全选', 'clear-scrollback': '清除回滚缓冲区', 'clear-screen': '清屏', 'clear-all': '清屏并清除回滚缓冲区' } as Record<string, string>)[id]!) }}</option>
        </select>
        <select v-else-if="button.action === 'LAUNCH_APPLICATION'" v-model="button.text" aria-label="外部应用"><option v-for="tool in externalTools" :key="tool.id" :value="tool.id">{{ tool.name }}</option></select>
        <label v-if="button.action === 'LAUNCH_APPLICATION'"><input v-model="button.launch_with_session_context" type="checkbox" />传递当前会话参数</label>
        <div v-if="button.action === 'RUN_SCRIPT'" class="script-editor"><textarea v-model="button.text" aria-label="脚本 JSON" rows="2" /><button type="button" @click="selectedScriptButton = button; scriptInput?.click()">选择脚本 JSON</button></div>
        <input v-model="button.color" type="color" aria-label="按钮颜色" />
        <input v-model="button.tooltip" :placeholder="consoleText('button.tooltip', '提示文本')" aria-label="提示文本" />
        <label><input v-model="button.disable_tooltip" type="checkbox" />{{ consoleText('button.no_tooltip', '不提示') }}</label>
        <label><input v-model="button.enabled" type="checkbox" />{{ consoleText('button.enabled', '启用') }}</label>
        <button @click="duplicate(button)">复制</button>
        <button @click="reorder(index,-1)" aria-label="上移">↑</button>
        <button @click="reorder(index,1)" aria-label="下移">↓</button>
        <button @click="group?.buttons.splice(index,1)">{{ consoleText('button.delete', '删除') }}</button>
      </div>
      <input ref="scriptInput" hidden type="file" accept=".json,application/json" @change="importScript" />
      <template #footer><el-button @click="managing = false">关闭</el-button><el-button type="primary" @click="save">保存配置</el-button></template>
    </el-dialog>
  </section>
</template>
<style scoped>
.command-bar { border-top: 1px solid var(--nc-border); background: var(--nc-bg-code-header); color: var(--nc-text-primary); padding: 5px 8px; }
.quick-buttons,.command-input,.manage-toolbar { display:flex;align-items:center;gap:6px; }
.quick-buttons { overflow-x:auto;white-space:nowrap;margin-bottom:5px; }
.mapped-button-bar { display:flex;align-items:center;gap:6px;overflow-x:auto;white-space:nowrap;margin-bottom:5px; }
.mapped-button-bar button { flex:0 0 auto;border:1px solid var(--nc-border);border-radius:4px;padding:3px 9px;background:var(--nc-bg-panel);cursor:pointer; }
.mapped-button-bar button:disabled { opacity:.5;cursor:not-allowed; }
.quick-buttons button { border:1px solid var(--nc-border);border-radius:4px;padding:3px 9px;background:var(--nc-bg-panel);cursor:pointer; }
.command-input textarea { flex:1;min-width:120px;resize:vertical;max-height:130px; }
textarea,select,input { background:var(--nc-bg-panel);color:var(--nc-text-primary);border:1px solid var(--nc-border);border-radius:4px;padding:4px; }
.button-editor { display:flex;align-items:center;gap:5px;min-width:950px;padding:8px 0; }
.button-editor textarea { flex:1; }.button-editor input:not([type]) { width:110px; }
pre { white-space:pre-wrap;max-height:50vh;overflow:auto; }
.dispatch-results { max-height: 9rem; overflow: auto; }
.dispatch-results li { display: flex; flex-wrap: wrap; gap: 8px; }
.batch-panel { display:grid;gap:6px; }
.batch-options,.batch-actions { display:flex;align-items:center;flex-wrap:wrap;gap:8px; }
.batch-options label { display:flex;align-items:center;gap:4px; }
.batch-options input { width:72px; }
.dispatch-results details { width:100%; }
.dispatch-results pre { max-height:180px;overflow:auto;white-space:pre-wrap; }
.script-editor { display:flex;align-items:center;gap:6px;flex:1; }
.script-editor textarea { flex:1;min-width:160px; }
.script-output { max-height:55vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere; }
</style>
