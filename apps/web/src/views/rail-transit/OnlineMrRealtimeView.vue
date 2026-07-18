<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Refresh } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import OnlineMrAgentControlPanel from '../../components/OnlineMrAgentControlPanel.vue'
import OnlineMrLocalControl from '../../components/OnlineMrLocalControl.vue'
import { addOnlineMrNote, listOnlineMrNotes } from '../../api/onlineMr'
import { getRailTransitTask, parseOnlineMrSession, recoverRailTransitTasks } from '../../api/railTransitWeb'
import { getTrainCommunicationSummary, listTrainCommunications } from '../../api/trainCommunication'
import { isFeatureEnabled } from '../../features'
import { useOnlineMrStore } from '../../stores/onlineMr'
import type { OnlineMrManualNote } from '../../types/onlineMr'
import type { RailTransitTask } from '../../types/railTransitWeb'
import type { MrCommunicationStatus } from '../../types/trainCommunication'

const store = useOnlineMrStore()
const route = useRoute()
const router = useRouter()
const expanded = ref('')
const rawTab = ref('mesh_link')
const fpingSource = ref('fping_summary')
const controlMrs = ref<MrCommunicationStatus[]>([])
const controlMrId = ref('')
const controlError = ref('')
const controlSiteId = ref('')
const executorTab = ref('local')
const noteText = ref('')
const notes = ref<OnlineMrManualNote[]>([])
const noteLoading = ref(false)
const parseTask = ref<RailTransitTask | null>(null)
const parseLoading = ref(false)
let parseTimer: number | null = null
const terminalTaskStates = new Set(['COMPLETED', 'FAILED', 'CANCELLED'])
const parseTaskStorageKey = 'netconsole.online-mr.parse-task'
const controlMr = computed(() => controlMrs.value.find((item) => item.mr_id === controlMrId.value) || null)
const selectedId = computed({
  get: () => store.selected?.session_id || '',
  set: (value: string) => value && void store.selectSession(value),
})
const fpingSummary = computed(() => {
  const summary = store.preview?.fping?.summary
  if (!summary || typeof summary !== 'object') return {}
  const result = summary as Record<string, unknown>
  const targets = result.targets
  if (!targets || typeof targets !== 'object') return result
  const first = Object.values(targets as Record<string, unknown>).find((item) => item && typeof item === 'object')
  return first ? { ...result, ...first as Record<string, unknown> } : result
})
const fpingTarget = computed(() => {
  const targets = store.preview?.fping?.summary && typeof store.preview.fping.summary === 'object'
    ? (store.preview.fping.summary as Record<string, unknown>).targets
    : null
  return targets && typeof targets === 'object' ? Object.keys(targets as Record<string, unknown>)[0] || '--' : '--'
})
const link = computed(() => store.preview?.link || {})
const displayContext = computed(() => store.preview?.display_context || {})
const acceptanceCommand = computed(() => {
  if (!store.selected) return ''
  return `python -m scripts.maintenance.check_online_mr_session_state --site "${store.selected.site_id}" --session-id "${store.selected.session_id}"`
})
const parseActive = computed(() => Boolean(parseTask.value && !terminalTaskStates.has(parseTask.value.status)))

watch(() => store.rawFiles, (files) => {
  if (!files.length) return
  const selected = files.find((item) => item.name === fpingSource.value)
  if (selected?.size_bytes) return
  fpingSource.value = ['fping_summary', 'fping_samples', 'fping_raw'].find((name) => files.some((item) => item.name === name && item.size_bytes > 0)) || 'fping_raw'
}, { immediate: true })

watch([expanded, rawTab, fpingSource], ([section, tab, selectedFping]) => {
  if (section === 'raw') {
    store.setRawSource(tab === 'fping' ? selectedFping : tab)
  } else if (section === 'logs') {
    store.setRawSource('collector_output')
  }
  store.setRawExpanded(Boolean(section))
})

watch(() => store.selected?.session_id, () => { void loadNotes() })

function field(value: Record<string, unknown>, ...names: string[]): string {
  for (const name of names) {
    const candidate = value[name]
    if (candidate !== undefined && candidate !== null && candidate !== '') return String(candidate)
  }
  return '--'
}

function formatBytes(value: number): string {
  if (!value) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function collectorType(status: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const value = status.toLowerCase()
  if (['running', 'completed', 'stopped'].includes(value)) return 'success'
  if (['failed', 'error', 'missing'].includes(value)) return 'danger'
  if (['starting', 'stopping', 'warning'].includes(value)) return 'warning'
  return 'info'
}

async function copyAcceptanceCommand(): Promise<void> {
  if (!acceptanceCommand.value) return
  await navigator.clipboard.writeText(acceptanceCommand.value)
  ElMessage.success('验收命令已复制')
}

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
}

function noteAuditSource(note: OnlineMrManualNote): string {
  const audit = note.payload.audit
  return audit && typeof audit === 'object'
    ? String((audit as Record<string, unknown>).source || 'legacy_qt')
    : 'legacy_qt'
}

async function loadNotes(): Promise<void> {
  if (!store.selected) {
    notes.value = []
    return
  }
  const sessionId = store.selected.session_id
  noteLoading.value = true
  try {
    const loaded = await listOnlineMrNotes(sessionId)
    if (store.selected?.session_id === sessionId) notes.value = loaded
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '备注加载失败')
  } finally {
    noteLoading.value = false
  }
}

async function addNote(): Promise<void> {
  if (!store.selected || !noteText.value.trim()) return
  const sessionId = store.selected.session_id
  noteLoading.value = true
  try {
    await ElMessageBox.confirm(
      `确认把备注写入会话 ${sessionId}？`,
      '记录采集备注',
      { confirmButtonText: '确认记录', cancelButtonText: '取消', type: 'warning' },
    )
    const saved = await addOnlineMrNote(sessionId, noteText.value.trim())
    if (store.selected?.session_id !== sessionId) return
    notes.value.push(saved)
    noteText.value = ''
    await store.refreshOverview()
    ElMessage.success('备注已写入会话并保留审计来源')
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') {
      ElMessage.error(cause instanceof Error ? cause.message : '备注保存失败')
    }
  } finally {
    noteLoading.value = false
  }
}

function stopParsePolling(): void {
  if (parseTimer !== null) window.clearTimeout(parseTimer)
  parseTimer = null
}

function rememberParseTask(value: RailTransitTask | null): void {
  parseTask.value = value
  if (value) localStorage.setItem(parseTaskStorageKey, value.task_id)
  else localStorage.removeItem(parseTaskStorageKey)
}

function pollParseTask(): void {
  stopParsePolling()
  if (!parseTask.value || terminalTaskStates.has(parseTask.value.status)) {
    if (parseTask.value?.status === 'COMPLETED') void store.refreshOverview()
    return
  }
  parseTimer = window.setTimeout(async () => {
    try {
      rememberParseTask(await getRailTransitTask(parseTask.value!.task_id))
      pollParseTask()
    } catch (cause) {
      ElMessage.error(cause instanceof Error ? cause.message : '解析任务状态读取失败')
    }
  }, 1000)
}

async function startParse(forceReparse: boolean): Promise<void> {
  if (!store.selected || parseActive.value || !isFeatureEnabled('web.online_mr_parse')) return
  const sessionId = store.selected.session_id
  parseLoading.value = true
  try {
    if (forceReparse) {
      await ElMessageBox.confirm(
        '强制解析会重建当前会话 parsed 结果；原始日志不会删除。确认继续？',
        '强制重新解析',
        { confirmButtonText: '重新解析', cancelButtonText: '取消', type: 'warning' },
      )
    }
    rememberParseTask(await parseOnlineMrSession(sessionId, forceReparse))
    pollParseTask()
    openTaskWindow()
  } catch (cause) {
    if (cause !== 'cancel' && cause !== 'close') {
      ElMessage.error(cause instanceof Error ? cause.message : '解析任务启动失败')
    }
  } finally {
    parseLoading.value = false
  }
}

async function recoverParse(): Promise<void> {
  try {
    const saved = localStorage.getItem(parseTaskStorageKey) || ''
    const rows = await recoverRailTransitTasks()
    rememberParseTask(
      rows.find((item) => item.task_id === saved && item.action === 'online_mr_parse')
      || rows.find((item) => item.action === 'online_mr_parse' && !terminalTaskStates.has(item.status))
      || null,
    )
    pollParseTask()
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '解析任务恢复失败')
  }
}

function openTaskWindow(): void {
  const taskId = parseTask.value?.task_id || ''
  if (window.netconsoleDesktop) {
    void window.netconsoleDesktop.openTaskWindow({ module: 'rail', ...(taskId ? { taskId } : {}) })
    return
  }
  void router.push({ name: 'tasks', query: { module: 'rail', ...(taskId ? { task_id: taskId } : {}) } })
}

async function loadControlMrs(): Promise<void> {
  try {
    const [summary, page] = await Promise.all([
      getTrainCommunicationSummary(),
      listTrainCommunications({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' }),
    ])
    controlSiteId.value = summary.site_id
    controlMrs.value = page.items.flatMap((train) => train.mrs)
    const requestedMr = typeof route.query.mr_id === 'string' ? route.query.mr_id : ''
    const requestedDevice = typeof route.query.device_id === 'string' ? route.query.device_id : ''
    controlMrId.value = controlMrs.value.find((item) => item.mr_id === requestedMr)?.mr_id
      || controlMrs.value.find((item) => String(item.device_id) === requestedDevice)?.mr_id
      || controlMrId.value
      || controlMrs.value[0]?.mr_id
      || ''
    controlError.value = ''
  } catch (cause) {
    controlError.value = cause instanceof Error ? cause.message : '正式 MR 列表加载失败'
  }
}

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibility)
  await loadControlMrs()
  const requestedSession = typeof route.query.session_id === 'string' ? route.query.session_id : ''
  if (requestedSession) await store.selectSession(requestedSession)
  await Promise.all([loadNotes(), recoverParse()])
  store.startPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
  stopParsePolling()
})
</script>

<template>
  <div class="online-mr-web" v-loading="store.loading">
    <div class="mr-toolbar">
      <div>
        <p class="eyebrow">RAIL TRANSIT · ONLINE MR COLLECTION</p>
        <h2>车载 MR 实时收集</h2>
        <p>配置、启动、SSH 采集、fping/iPerf、正常停止、强停、恢复与会话交付。</p>
      </div>
      <div class="mr-toolbar-actions">
        <el-select v-model="selectedId" filterable placeholder="选择最近会话" style="width: 310px">
          <el-option
            v-for="item in store.recent"
            :key="item.session_id"
            :label="`${item.device_name || item.mr_name} · ${item.status} · ${item.started_at || item.session_id}`"
            :value="item.session_id"
          />
        </el-select>
        <el-button :icon="Refresh" @click="store.refreshOverview">刷新</el-button>
      </div>
    </div>

    <section class="content-card collection-control">
      <div class="control-selector">
        <div><h3>采集控制</h3><p>从基础资料选择正式 MR；连接凭据由后端设备库受控读取。</p></div>
        <div class="mr-toolbar-actions"><el-select v-model="controlMrId" filterable placeholder="选择列车 MR" style="width: 330px"><el-option v-for="mr in controlMrs" :key="mr.mr_id" :label="`${mr.train_name} · ${mr.mr_role} · ${mr.mr_name}`" :value="mr.mr_id" /></el-select><el-button :icon="Refresh" @click="loadControlMrs">刷新 MR</el-button></div>
      </div>
      <el-alert v-if="controlError" :title="controlError" type="error" :closable="false" show-icon />
      <el-tabs v-if="controlMr && controlSiteId" v-model="executorTab" type="border-card"><el-tab-pane label="LOCAL 本地执行" name="local"><OnlineMrLocalControl :site-id="controlSiteId" :mr="controlMr" /></el-tab-pane><el-tab-pane label="AGENT 远程执行" name="agent"><OnlineMrAgentControlPanel :site-id="controlSiteId" :mr="controlMr" /></el-tab-pane></el-tabs>
      <el-empty v-else description="当前局点没有已登记且绑定设备的 MR" />
    </section>

    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="mr-error" />
    <el-empty v-if="!store.selected && !store.loading" description="当前局点暂无 Online MR 会话" />

    <template v-if="store.selected">
      <section class="mr-status-grid">
        <article class="mr-status-card primary">
          <span>会话状态</span>
          <NcStatusTag :status="store.selected.status" />
          <small>{{ store.selected.phase || '无阶段信息' }}</small>
        </article>
        <article class="mr-status-card">
          <span>车辆 / MR</span>
          <strong>{{ store.selected.device_name || store.selected.mr_name }}</strong>
          <small>{{ store.selected.mr_name }} · {{ store.selected.executor_kind || '--' }}</small>
        </article>
        <article class="mr-status-card">
          <span>运行时长</span>
          <strong>{{ (store.selected.duration_minutes || 0).toFixed(1) }} min</strong>
          <small>{{ store.selected.started_at || '--' }}</small>
        </article>
        <article class="mr-status-card">
          <span>Task / Mapping</span>
          <strong>{{ store.selected.task_status || '--' }}</strong>
          <small>{{ store.selected.mapping_state || '无映射' }}</small>
        </article>
        <article class="mr-status-card">
          <span>数据完整性</span>
          <strong>{{ store.selected.data_integrity }}</strong>
          <small>{{ store.selected.stop_reason || '运行中或未记录停止原因' }}</small>
        </article>
      </section>
      <el-alert v-if="store.selected.error_message" :title="store.selected.error_message" type="error" :closable="false" show-icon class="mr-error" />

      <section class="mr-two-column">
        <div class="content-card mr-panel">
          <div class="mr-panel-title">
            <div><h3>采集器状态</h3><p>终态会话会校正过期的 running 视图状态</p></div>
            <span>{{ store.collectors.filter((item) => item.enabled).length }} 项启用</span>
          </div>
          <el-table :data="store.collectors" size="small" max-height="360">
            <el-table-column prop="label" label="采集项" min-width="138" />
            <el-table-column label="状态" width="104">
              <template #default="scope">
                <el-tag :type="collectorType(scope.row.status)" effect="light">{{ scope.row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Raw" min-width="190">
              <template #default="scope"><code>{{ scope.row.raw_file }}</code></template>
            </el-table-column>
            <el-table-column label="大小" width="96">
              <template #default="scope">{{ formatBytes(scope.row.size_bytes) }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="更新时间" min-width="156" />
          </el-table>
        </div>

        <div class="content-card mr-panel">
          <div class="mr-panel-title">
            <div><h3>轻量实时预览</h3><p>{{ store.preview?.updated_at || '尚未更新时间' }}</p></div>
            <el-tag :type="store.preview?.available ? 'success' : 'info'">{{ store.preview?.available ? '可用' : '暂无数据' }}</el-tag>
          </div>
          <div class="mr-preview-grid">
            <div><span>站点</span><strong>{{ field(displayContext, 'station', 'site') }}</strong></div>
            <div><span>区间</span><strong>{{ field(displayContext, 'section') }}</strong></div>
            <div><span>主链路</span><strong>{{ field(link, 'peer_name', 'resolved_peer_name', 'main_link') }}</strong></div>
            <div><span>Peer MAC</span><strong>{{ field(link, 'peer_mac', 'peer_mac_normalized', 'bssid') }}</strong></div>
            <div><span>RSSI</span><strong>{{ field(link, 'rssi', 'mr_rssi', 'local_rssi_db') }}</strong></div>
            <div><span>链路状态</span><strong>{{ field(link, 'link_state', 'status') }}</strong></div>
            <div><span>Ping 目标</span><strong>{{ fpingTarget }}</strong></div>
            <div><span>Ping 已发</span><strong>{{ field(fpingSummary, 'sent') }}</strong></div>
            <div><span>最新延迟</span><strong>{{ field(fpingSummary, 'latest_latency_ms') }} ms</strong></div>
            <div><span>Ping 丢包</span><strong>{{ field(fpingSummary, 'loss_percent') }}%</strong></div>
            <div><span>平均延迟</span><strong>{{ field(fpingSummary, 'avg_latency_ms') }} ms</strong></div>
            <div><span>最大延迟</span><strong>{{ field(fpingSummary, 'max_latency_ms') }} ms</strong></div>
            <div><span>iPerf</span><strong>{{ field(store.preview?.iperf || {}, 'bitrate_mbps', 'status') }}</strong></div>
          </div>
          <el-alert :title="store.preview?.message || '暂无实时预览数据'" type="info" :closable="false" class="mr-preview-message" />
        </div>
      </section>

      <el-collapse v-model="expanded" accordion class="mr-collapse">
        <el-collapse-item name="raw" title="原始日志动态查看（展开后每秒刷新）">
          <div class="mr-raw-toolbar">
            <el-tabs v-model="rawTab" class="mr-raw-tabs">
              <el-tab-pane label="主链路 mesh-link" name="mesh_link" />
              <el-tab-pane label="信道繁忙度" name="channel_busy" />
              <el-tab-pane label="高频 Ping" name="fping" />
              <el-tab-pane label="主链路切换" name="switch_history" />
            </el-tabs>
            <el-select v-if="rawTab === 'fping'" v-model="fpingSource" size="small" style="width: 170px">
              <el-option label="最终摘要" value="fping_summary" />
              <el-option label="最近样本" value="fping_samples" />
              <el-option label="原始输出" value="fping_raw" />
            </el-select>
            <el-button size="small" :icon="Refresh" @click="store.refreshRawTail">刷新</el-button>
            <span>{{ store.rawTail?.message || store.rawTail?.modified_at || '选择日志来源' }}</span>
          </div>
          <pre class="mr-raw-log">{{ store.rawTail?.lines.join('\n') || (store.rawSource === 'switch_history' ? '暂无主链路切换日志' : '文件不存在、尚未生成或暂无内容。') }}</pre>
        </el-collapse-item>
        <el-collapse-item name="logs" title="采集输出日志 tail（展开后每秒刷新）">
          <div class="mr-raw-toolbar">
            <span>raw/collector_output_raw.log · 最后 200 行</span>
            <el-button size="small" :icon="Refresh" @click="store.refreshRawTail">刷新</el-button>
          </div>
          <pre class="mr-raw-log">{{ store.rawTail?.lines.join('\n') || '采集输出日志不存在或尚未生成。' }}</pre>
        </el-collapse-item>
      </el-collapse>

      <section class="content-card mr-session-actions">
        <div class="session-action-heading">
          <div>
            <h3>采集备注与会话解析</h3>
            <p>备注持久化到会话；解析使用现有 Job Center，停止、日志和结果统一在任务窗口处理。</p>
          </div>
          <el-tag v-if="parseTask">{{ parseTask.status }}</el-tag>
        </div>
        <div class="note-actions">
          <el-input
            v-model="noteText"
            maxlength="500"
            show-word-limit
            clearable
            placeholder="输入现场备注、站点或异常说明"
            @keyup.enter="addNote"
          />
          <el-button
            :loading="noteLoading"
            :disabled="!noteText.trim() || !isFeatureEnabled('online_mr.collection_notes')"
            @click="addNote"
          >记录备注</el-button>
          <el-button @click="noteText = ''">清空输入</el-button>
        </div>
        <el-table v-loading="noteLoading" :data="notes" max-height="230" empty-text="当前会话暂无备注">
          <el-table-column prop="local_time" label="时间" width="185" />
          <el-table-column prop="title" label="备注" min-width="280" />
          <el-table-column label="审计来源" width="190">
            <template #default="{ row }">{{ noteAuditSource(row) }}</template>
          </el-table-column>
        </el-table>
        <div class="parse-actions">
          <el-button
            type="primary"
            :loading="parseLoading"
            :disabled="parseActive || !isFeatureEnabled('web.online_mr_parse')"
            @click="startParse(false)"
          >解析当前会话</el-button>
          <el-button
            type="warning"
            plain
            :disabled="parseActive || !isFeatureEnabled('web.online_mr_parse')"
            @click="startParse(true)"
          >强制重新解析</el-button>
          <el-button @click="recoverParse">恢复任务状态</el-button>
          <el-button @click="openTaskWindow">打开任务窗口</el-button>
          <span v-if="parseTask">{{ parseTask.error_message || parseTask.message || parseTask.task_id }}</span>
        </div>
      </section>

      <section class="content-card mr-delivery">
        <div>
          <h3>会话交付</h3>
          <p><b>Session ID：</b><code>{{ store.selected.session_id }}</code></p>
          <p><b>Task ID：</b><code>{{ store.selected.controller_task_id || '无 Controller Task' }}</code></p>
          <p><b>Session：</b><code>{{ store.selected.session_path_reference }}</code></p>
          <p><b>Package：</b><code>{{ store.selected.package_reference || '尚未生成' }}</code></p>
        </div>
        <div class="mr-command">
          <code>{{ acceptanceCommand }}</code>
          <el-button :icon="CopyDocument" @click="copyAcceptanceCommand">复制验收命令</el-button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.online-mr-web { max-width: 1680px; margin: 0 auto; }.eyebrow { margin: 0 0 4px !important; color: var(--el-color-primary) !important; font-size: 12px !important; font-weight: 700; letter-spacing: .08em; }
.mr-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 18px 0; }
.mr-toolbar h2, .mr-panel-title h3, .mr-delivery h3 { margin: 0; }
.mr-toolbar p, .mr-panel-title p { margin: 5px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.mr-toolbar-actions { display: flex; gap: 10px; }
.collection-control { margin-bottom: 16px; padding: 16px; }.control-selector { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }.control-selector h3 { margin: 0 0 5px; }.control-selector p { margin: 0; color: var(--el-text-color-secondary); }.collection-control .el-alert { margin-bottom: 12px; }
.mr-error { margin-bottom: 16px; }
.mr-status-grid { display: grid; grid-template-columns: repeat(5, minmax(160px, 1fr)); gap: 14px; margin-bottom: 16px; }
.mr-status-card { min-height: 116px; padding: 17px 18px; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-top: 3px solid var(--nc-border-strong); border-radius: 10px; }
.mr-status-card.primary { border-top-color: var(--nc-primary); }
.mr-status-card > span { display: block; margin-bottom: 12px; color: var(--nc-text-secondary); font-size: 12px; }
.mr-status-card strong { display: block; overflow: hidden; color: var(--nc-text-primary); font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }
.mr-status-card small { display: block; margin-top: 10px; overflow: hidden; color: var(--nc-text-tertiary); text-overflow: ellipsis; white-space: nowrap; }
.mr-two-column { display: grid; grid-template-columns: minmax(560px, 1.15fr) minmax(440px, .85fr); gap: 16px; }
.mr-panel { min-width: 0; }
.mr-panel-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 17px 19px; border-bottom: 1px solid var(--nc-divider); }
.mr-panel-title > span { color: var(--nc-text-secondary); font-size: 12px; }
.mr-preview-grid { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 1px; background: var(--nc-divider); }
.mr-preview-grid div { min-height: 84px; padding: 16px; background: var(--nc-bg-panel); }
.mr-preview-grid span { display: block; color: var(--nc-text-secondary); font-size: 12px; }
.mr-preview-grid strong { display: block; margin-top: 8px; overflow: hidden; font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }
.mr-preview-message { margin: 14px; width: auto; }
.mr-collapse { margin-top: 16px; padding: 0 18px; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 10px; }
.mr-session-actions { margin-top: 16px; padding: 18px 20px; }
.session-action-heading, .note-actions, .parse-actions { display: flex; align-items: center; gap: 12px; }
.session-action-heading { justify-content: space-between; }
.session-action-heading h3 { margin: 0; }
.session-action-heading p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; }
.note-actions, .parse-actions { margin-top: 14px; }
.note-actions .el-input { max-width: 900px; }
.parse-actions { flex-wrap: wrap; }
.parse-actions span { color: var(--el-text-color-secondary); font-size: 12px; }
.mr-raw-toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; color: var(--nc-text-secondary); font-size: 12px; }
.mr-raw-toolbar > span { margin-left: auto; }
.mr-raw-tabs { min-width: 560px; }
.mr-raw-log { min-height: 240px; max-height: 420px; margin: 0 0 18px; padding: 15px; overflow: auto; color: var(--nc-text-code); background: var(--nc-bg-code); border-radius: 8px; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-all; }
.mr-delivery { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-top: 16px; padding: 18px 20px; }
.mr-delivery p { margin: 8px 0 0; color: var(--nc-text-secondary); font-size: 12px; }
.mr-delivery code { overflow-wrap: anywhere; }
.mr-command { display: flex; align-items: center; justify-content: flex-end; gap: 12px; max-width: 58%; }
.mr-command code { padding: 9px 11px; color: var(--nc-text-code); background: var(--nc-bg-code); border-radius: 6px; font-size: 11px; }
@media (max-width: 1380px) {
  .mr-status-grid { grid-template-columns: repeat(3, 1fr); }
  .mr-two-column { grid-template-columns: 1fr; }
}
@media (max-width: 900px) { .mr-toolbar,.control-selector { align-items: flex-start; flex-direction: column; }.mr-toolbar-actions { flex-wrap: wrap; } }
</style>
