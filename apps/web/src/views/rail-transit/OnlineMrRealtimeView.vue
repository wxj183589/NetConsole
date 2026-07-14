<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CopyDocument, Refresh } from '@element-plus/icons-vue'

import NcStatusTag from '../../components/NcStatusTag.vue'
import { useOnlineMrStore } from '../../stores/onlineMr'

const store = useOnlineMrStore()
const route = useRoute()
const expanded = ref('')
const rawTab = ref('mesh_link')
const fpingSource = ref('fping_summary')
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

onMounted(async () => {
  document.addEventListener('visibilitychange', handleVisibility)
  const requestedSession = typeof route.query.session_id === 'string' ? route.query.session_id : ''
  if (requestedSession) await store.selectSession(requestedSession)
  store.startPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})
</script>

<template>
  <div class="online-mr-web" v-loading="store.loading">
    <el-alert
      title="只读实时展示"
      description="启动、停止、强停和最终化仍由 Qt 页面负责；本页只读取当前局点的会话状态、view 与 raw 事实文件。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="mr-toolbar">
      <div>
        <h2>车载 MR 实时展示</h2>
        <p>当前局点会话 · 2 秒状态轮询 · 原始日志按需刷新</p>
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
.online-mr-web { max-width: 1680px; margin: 0 auto; }
.mr-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 18px 0; }
.mr-toolbar h2, .mr-panel-title h3, .mr-delivery h3 { margin: 0; }
.mr-toolbar p, .mr-panel-title p { margin: 5px 0 0; color: #7b8798; font-size: 12px; }
.mr-toolbar-actions { display: flex; gap: 10px; }
.mr-error { margin-bottom: 16px; }
.mr-status-grid { display: grid; grid-template-columns: repeat(5, minmax(160px, 1fr)); gap: 14px; margin-bottom: 16px; }
.mr-status-card { min-height: 116px; padding: 17px 18px; background: #fff; border: 1px solid #dfe7f1; border-top: 3px solid #7d91ad; border-radius: 10px; }
.mr-status-card.primary { border-top-color: #2398c6; }
.mr-status-card > span { display: block; margin-bottom: 12px; color: #6d7a8e; font-size: 12px; }
.mr-status-card strong { display: block; overflow: hidden; color: #172033; font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }
.mr-status-card small { display: block; margin-top: 10px; overflow: hidden; color: #8a96a7; text-overflow: ellipsis; white-space: nowrap; }
.mr-two-column { display: grid; grid-template-columns: minmax(560px, 1.15fr) minmax(440px, .85fr); gap: 16px; }
.mr-panel { min-width: 0; }
.mr-panel-title { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 17px 19px; border-bottom: 1px solid #e8edf4; }
.mr-panel-title > span { color: #778398; font-size: 12px; }
.mr-preview-grid { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 1px; background: #e8edf4; }
.mr-preview-grid div { min-height: 84px; padding: 16px; background: #fff; }
.mr-preview-grid span { display: block; color: #7b8798; font-size: 12px; }
.mr-preview-grid strong { display: block; margin-top: 8px; overflow: hidden; font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }
.mr-preview-message { margin: 14px; width: auto; }
.mr-collapse { margin-top: 16px; padding: 0 18px; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.mr-raw-toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; color: #7b8798; font-size: 12px; }
.mr-raw-toolbar > span { margin-left: auto; }
.mr-raw-tabs { min-width: 560px; }
.mr-raw-log { min-height: 240px; max-height: 420px; margin: 0 0 18px; padding: 15px; overflow: auto; color: #d6e0ec; background: #101827; border-radius: 8px; font: 12px/1.55 Consolas, "Microsoft YaHei", monospace; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-all; }
.mr-delivery { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-top: 16px; padding: 18px 20px; }
.mr-delivery p { margin: 8px 0 0; color: #657286; font-size: 12px; }
.mr-delivery code { overflow-wrap: anywhere; }
.mr-command { display: flex; align-items: center; justify-content: flex-end; gap: 12px; max-width: 58%; }
.mr-command code { padding: 9px 11px; color: #334155; background: #f2f5f9; border-radius: 6px; font-size: 11px; }
@media (max-width: 1380px) {
  .mr-status-grid { grid-template-columns: repeat(3, 1fr); }
  .mr-two-column { grid-template-columns: 1fr; }
}
</style>
