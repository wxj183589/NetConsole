<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { t } from '../../i18n/runtime'
import { getGroundMrMonitoring, listGroundSyslogRecords } from '../../api/groundUnattended'
import type { GroundHeartbeatMr, GroundMeshMonitorEvent, GroundMrMonitoring } from '../../types/groundUnattended'
import MrMonitoringChart from './MrMonitoringChart.vue'
const props = defineProps<{ mr: GroundHeartbeatMr; runId: string; active: boolean; section: string; terminalEnabled: boolean; quickEnabled: boolean; monitorState?: string }>()
const emit = defineEmits<{ (event: 'close'): void; (event: 'terminal'): void; (event: 'quick-ping'): void }>()
const result = ref<GroundMrMonitoring | null>(null), error = ref(''), loading = ref(false)
const range = ref<number | string>(60), interval = ref(5), paused = ref(false), fullScreen = ref(false)
const customStart = ref(''), customEnd = ref(''), chartStart = ref(''), chartEnd = ref(''), selectedTime = ref('')
const selectedEvent = ref<GroundMeshMonitorEvent | null>(null), rawText = ref(''), rawError = ref(''), rawLoading = ref(false)
let controller: AbortController | null = null, rawController: AbortController | null = null, timer: ReturnType<typeof setInterval> | undefined, generation = 0
const enabled = computed(() => props.active && Boolean(props.mr.mr_uuid))
const size = computed(() => fullScreen.value ? '100%' : '48%')
const mr = computed(() => result.value?.mr || props.mr)
const displayStatusCode = computed(() => props.monitorState === 'PAUSED' ? 'PAUSED' : ['DISABLED', 'STOPPED'].includes(props.monitorState || '') ? 'STOPPED' : mr.value.status)
const displayStatus = computed(() => displayStatusCode.value === 'PAUSED' ? '已暂停' : displayStatusCode.value === 'STOPPED' ? '已停止' : displayStatusCode.value === 'UNKNOWN' ? t('ground.monitor.waiting', '待检测') : mr.value.status)
const tabs = ['all', 'ping', 'ap', 'mesh', 'timeline']
const selectedSection = ref(props.section || 'all')
watch(() => props.section, (value) => { selectedSection.value = value || 'all' })
function stop(): void { generation++; controller?.abort(); controller = null; rawController?.abort(); rawController = null; if (timer) clearInterval(timer); timer = undefined; loading.value = false; rawLoading.value = false }
function bounds(): [string, string] {
  const end = range.value === 'custom' ? new Date(customEnd.value) : new Date()
  const start = range.value === 'custom' ? new Date(customStart.value) : new Date(end.getTime() - Number(range.value) * 60000)
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end || end.getTime() - start.getTime() > 86400000) throw new Error(t('ground.monitor.invalid_range', '请选择有效且不超过 24 小时的时间范围'))
  return [start.toISOString(), end.toISOString()]
}
async function load(): Promise<void> {
  if (!enabled.value || controller) return
  const current = generation, request = new AbortController(); controller = request; loading.value = true
  try {
    const [start, end] = bounds()
    const data = await getGroundMrMonitoring(props.mr.mr_uuid, { run_id: props.runId, start_time: start, end_time: end }, { signal: request.signal })
    if (current !== generation || !enabled.value) return
    result.value = data; chartStart.value = start; chartEnd.value = end; error.value = ''
  } catch (reason) { if (current === generation && !request.signal.aborted) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (current === generation) { controller = null; loading.value = false } }
}
function restart(clear = false): void {
  stop()
  if (clear) { result.value = null; selectedEvent.value = null; rawText.value = ''; error.value = ''; selectedTime.value = '' }
  if (enabled.value) { void load(); if (!paused.value && range.value !== 'custom') timer = setInterval(() => { void load() }, interval.value * 1000) }
}
watch([enabled, () => props.mr.mr_uuid, () => props.runId], () => restart(true), { immediate: true })
watch([range, interval, paused], () => { if (range.value !== 'custom') restart() ; else stop() })
async function selectEvent(event: GroundMeshMonitorEvent): Promise<void> {
  selectedEvent.value = event; selectedTime.value = event.event_time; rawText.value = event.raw_text; rawError.value = ''
  rawController?.abort()
  if (event.raw_text || !event.raw_file_id) return
  const request = new AbortController(), current = generation; rawController = request; rawLoading.value = true
  try {
    const stamp = Date.parse(event.receive_time)
    if (!Number.isFinite(stamp)) throw new Error(t('ground.monitor.raw_no_time', '事件没有可用于查询原始日志的接收时间'))
    const page = await listGroundSyslogRecords({ run_id: props.runId, mr_id: props.mr.mr_uuid, start_time: new Date(stamp - 1).toISOString(), end_time: new Date(stamp + 1).toISOString(), page_size: 100 }, { signal: request.signal })
    if (current !== generation || request.signal.aborted) return
    const exact = page.items.find((row) => row.raw_file_id === event.raw_file_id && row.raw_line_number === event.raw_line_number)
    rawText.value = exact?.raw_text || ''
    if (!exact) rawError.value = t('ground.monitor.raw_missing', '当前有界查询未找到同一文件、同一行的原始日志；保留索引来源，不用相邻日志替代。')
  } catch (reason) { if (current === generation && !request.signal.aborted) rawError.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (current === generation && rawController === request) { rawController = null; rawLoading.value = false } }
}
function rate(sent: number, lost: number): string { return sent ? `${(lost / sent * 100).toFixed(2)}%` : 'UNKNOWN' }
const lastActualPoint = computed(() => result.value?.series.points.filter((row) => !row.warmup_ignored && Date.parse(row.ts) >= Date.parse(chartStart.value) && Date.parse(row.ts) <= Date.parse(chartEnd.value)).slice().sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))[0])
const rtt = computed(() => lastActualPoint.value?.ok && lastActualPoint.value.rtt_ms != null ? `${lastActualPoint.value.rtt_ms.toFixed(2)} ms` : 'UNKNOWN')
onBeforeUnmount(stop)
</script>

<template>
  <el-drawer :model-value="true" :size="size" class="mr-monitor-drawer" append-to-body destroy-on-close @update:model-value="!$event && emit('close')">
    <template #header><div class="drawer-title"><strong>{{ t('ground.monitor.title', 'MR 综合动态监测') }} · {{ mr.train_no }} / {{ mr.role }}</strong><el-button text @click="fullScreen = !fullScreen">{{ fullScreen ? t('ground.monitor.restore', '还原') : t('ground.monitor.fullscreen', '全屏') }}</el-button></div></template>
    <div class="mr-monitor-content">
      <div class="identity"><div class="identity-title"><strong>{{ mr.mr_name || t('ground.monitor.unresolved', 'MR 身份未解析') }}</strong><el-tag size="small" :type="displayStatusCode === 'ONLINE' ? 'success' : displayStatusCode === 'OFFLINE' ? 'danger' : 'warning'">{{ mr.role }} · {{ displayStatus }}</el-tag></div><span>{{ t('ground.monitor.train', '列车') }} {{ mr.train_no || mr.train_id }} · {{ t('ground.monitor.mr_uuid', 'MR UUID') }} {{ mr.mr_uuid }}</span><div class="identity-group"><strong>{{ t('ground.monitor.section_ap', '接入区间 AP') }}</strong><span v-if="mr.associated_aps?.length" class="ap-detail-list"><el-tag v-for="ap in mr.associated_aps" :key="`${ap.name}-${ap.bssid}-${ap.mac}`" size="small" effect="plain">{{ ap.name || ap.bssid || ap.mac }}<template v-if="ap.bssid"> · BSSID {{ ap.bssid }}</template><template v-if="ap.rssi != null"> · RSSI {{ ap.rssi }}</template><template v-if="ap.connection_status"> · {{ ap.connection_status }}</template><template v-if="ap.last_seen_at"> · {{ ap.last_seen_at }}</template><template v-if="ap.station"> · {{ t('ground.monitor.access_station', '接入站点') }} {{ ap.station }}</template></el-tag></span><span v-else class="muted-value">{{ t('ground.monitor.no_ap', '暂无关联 AP') }}</span></div><div class="identity-group"><strong>{{ t('ground.monitor.access_station', '接入站点') }}</strong><span v-if="mr.associated_stations?.length || mr.station" class="ap-detail-list"><el-tag v-for="stationName in Array.from(new Set([...(mr.associated_stations || []), ...(mr.station ? [mr.station] : [])]))" :key="stationName" size="small" effect="plain">{{ stationName }}</el-tag></span><span v-else class="muted-value">{{ t('ground.monitor.no_station', '未关联站点') }}</span></div><span v-if="mr.section">{{ t('ground.monitor.section', '区间') }} {{ mr.section }}</span></div>
      <div class="actions"><el-button :disabled="!terminalEnabled" @click="emit('terminal')">{{ t('ground.monitor.terminal', '外部终端') }}</el-button><el-button :disabled="!quickEnabled" @click="emit('quick-ping')">{{ t('ground.quick_ping', '快速 Ping') }}</el-button><el-button :loading="loading" @click="load">{{ t('common.refresh', '刷新') }}</el-button><el-button @click="emit('close')">{{ t('common.close', '关闭') }}</el-button></div>
      <div class="range-controls"><el-select v-model="range" style="width:150px"><el-option v-for="minutes in [10, 30, 60, 360, 1440]" :key="minutes" :value="minutes" :label="minutes >= 60 ? `${minutes / 60} h` : `${minutes} min`" /><el-option value="custom" :label="t('ground.monitor.custom', '历史自定义')" /></el-select><el-select v-model="interval" style="width:110px"><el-option v-for="seconds in [5, 10, 30, 60]" :key="seconds" :value="seconds" :label="`${seconds} s`" /></el-select><el-checkbox v-model="paused">{{ paused ? t('ground.monitor.resume_refresh', '恢复刷新') : t('ground.monitor.auto_refresh', '实时刷新') }}</el-checkbox></div>
      <div v-if="range === 'custom'" class="range-controls"><input v-model="customStart" type="datetime-local" :aria-label="t('ground.monitor.start', '开始时间')"><input v-model="customEnd" type="datetime-local" :aria-label="t('ground.monitor.end', '结束时间')"><el-button @click="restart(true)">{{ t('ground.monitor.query_history', '查询历史') }}</el-button></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <div class="metrics"><span>{{ t('ground.monitor.average_rtt', '平均 RTT') }} <b>{{ result?.series.average_rtt_ms == null ? rtt : `${result.series.average_rtt_ms.toFixed(2)} ms` }}</b></span><span>{{ t('ground.monitor.recent_probe', '最近有效探测') }} <b>{{ lastActualPoint?.ts || 'UNKNOWN' }}</b></span><span>{{ t('ground.monitor.loss_1m', '丢包率(1m)') }} <b>{{ result?.series.window_statistics?.['1']?.loss_rate_percent == null ? 'UNKNOWN' : `${result.series.window_statistics['1']!.loss_rate_percent!.toFixed(2)}%` }}</b></span><span>{{ t('ground.monitor.loss_10m', '丢包率(10m)') }} <b>{{ result?.series.window_statistics?.['10']?.loss_rate_percent == null ? 'UNKNOWN' : `${result.series.window_statistics['10']!.loss_rate_percent!.toFixed(2)}%` }}</b></span><span>{{ t('ground.monitor.loss_30m', '丢包率(30m)') }} <b>{{ result?.series.window_statistics?.['30']?.loss_rate_percent == null ? 'UNKNOWN' : `${result.series.window_statistics['30']!.loss_rate_percent!.toFixed(2)}%` }}</b></span><span>{{ t('ground.monitor.loss_run', '本次运行丢包') }} <b>{{ result ? rate(result.run_sent_count, result.run_lost_count) : 'UNKNOWN' }}</b></span></div>
      <div class="section-tabs"><el-button v-for="sectionName in tabs" :key="sectionName" :type="selectedSection === sectionName ? 'primary' : 'default'" size="small" @click="selectedSection = sectionName">{{ ({ all: t('ground.monitor.all', '综合监控'), ping: 'Ping 详情', ap: t('ground.monitor.ap_history', '连接 AP 历史'), mesh: t('ground.monitor.mesh_syslog', 'Mesh 切换日志 (Syslog)'), timeline: t('ground.monitor.timeline', '事件时间轴') } as Record<string,string>)[sectionName] }}</el-button></div>
      <template v-if="result">
        <el-alert v-if="result.series.diagnostics.truncated || result.events_truncated" :title="t('ground.monitor.truncated', '查询达到有界预算，当前统计和事件可能不完整，请缩小范围。')" type="warning" :closable="false" />
        <p class="evidence-note">{{ t('ground.monitor.evidence_note', '丢包率只统计实际有效探测，空白不代表丢包。Peer 优先采用相邻一致的 Syslog 切换；AC 仅闭合不超过 30 秒的相同 Peer 实际采样区间。末次证据后与缺失段为 UNKNOWN。') }}</p>
        <section v-if="result.loss_events?.length" class="loss-events"><h4>{{ t('ground.monitor.loss_events', '丢包事件') }}</h4><el-table :data="result.loss_events" size="small" stripe><el-table-column prop="started_at" label="开始" /><el-table-column prop="ended_at" label="恢复" /><el-table-column prop="state" label="状态" /><el-table-column prop="loss_count" label="丢包数" /><el-table-column label="AP / 站点"><template #default="scope">{{ scope.row.ap_name || '—' }} / {{ scope.row.station || '—' }} / {{ scope.row.section || '—' }}</template></el-table-column></el-table></section>
        <MrMonitoringChart v-if="selectedSection !== 'mesh' && selectedSection !== 'timeline'" :data="result" :start="chartStart" :end="chartEnd" :active="active" :selected-time="selectedTime" />
        <p v-if="!result.series.points.length">{{ t('ground.monitor.no_samples', '选定范围没有 Ping 样本') }}</p>
        <section v-if="['all', 'mesh', 'timeline'].includes(selectedSection)" class="mesh-events"><h4>{{ selectedSection === 'timeline' ? t('ground.monitor.timeline', '事件时间轴') : t('ground.monitor.mesh_events', 'Mesh 切换事件与原始日志') }}</h4><p v-if="!result.mesh_events.length">{{ t('ground.monitor.no_mesh', '没有 Mesh 事件证据，连接状态 UNKNOWN') }}</p><button v-for="event in result.mesh_events.slice().reverse()" :key="event.id" class="mesh-event" :class="{ selected: selectedEvent?.id === event.id }" @click="selectEvent(event)"><strong>{{ event.event_type }}</strong><span>{{ event.old_ap_name || event.old_bssid || 'UNKNOWN' }} → {{ event.new_ap_name || event.bssid || 'UNKNOWN' }}</span><span>BSSID {{ event.bssid || 'UNKNOWN' }} · RSSI {{ event.rssi ?? 'UNKNOWN' }}</span><small>{{ t('ground.monitor.device_time', '设备时间') }} {{ event.device_time || 'UNKNOWN' }} · {{ t('ground.monitor.receive_time', '接收时间') }} {{ event.receive_time }} · {{ event.event_time_source }} / {{ event.data_quality }}</small></button></section>
        <section v-if="selectedEvent" class="raw-detail"><p>{{ selectedEvent.raw_file_id }} : {{ selectedEvent.raw_line_number }} · {{ selectedEvent.event_time }}</p><p v-if="rawLoading">{{ t('common.loading', '加载中') }}</p><el-alert v-if="rawError" :title="rawError" type="warning" :closable="false" /><pre>{{ rawText || t('ground.monitor.raw_unavailable', '原始日志尚未加载或不可用') }}</pre></section>
      </template>
    </div>
  </el-drawer>
</template>
<style scoped>
.drawer-title{display:flex;justify-content:space-between;align-items:center;gap:12px;min-width:0}.mr-monitor-content{display:flex;flex-direction:column;gap:14px;min-width:0}.identity{display:flex;flex-direction:column;gap:8px;overflow-wrap:anywhere}.identity-title{display:flex;align-items:center;gap:8px}.identity-title strong{font-size:18px}.identity>span{font-size:12px;color:var(--el-text-color-secondary)}.identity-group{display:flex;flex-direction:column;gap:5px}.identity-group>strong{font-size:12px;color:var(--el-text-color-secondary)}.ap-detail-list{display:flex;gap:6px;flex-wrap:wrap}.muted-value{font-size:12px;color:var(--el-text-color-secondary)}.actions,.range-controls,.section-tabs{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.metrics>span{background:var(--el-fill-color-light);border:1px solid var(--el-border-color-lighter);padding:10px;display:flex;flex-direction:column;gap:6px;min-width:100px}.metrics b{font-size:14px;overflow-wrap:anywhere}.evidence-note{color:var(--el-text-color-secondary);font-size:12px}.mesh-events{max-height:340px;overflow:auto}.mesh-event{display:flex;flex-direction:column;text-align:left;gap:5px;width:100%;padding:9px;margin:4px 0;background:var(--el-fill-color-blank);color:var(--el-text-color-primary);border:1px solid var(--el-border-color-light);cursor:pointer;overflow-wrap:anywhere}.mesh-event.selected{border-color:var(--el-color-primary)}.raw-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;background:var(--el-fill-color-light);padding:12px}.range-controls input{max-width:220px;background:var(--el-fill-color-blank);color:var(--el-text-color-primary);border:1px solid var(--el-border-color);padding:6px}@media(max-width:900px){.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:520px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
<style>@media(max-width:1100px){.mr-monitor-drawer.el-drawer{width:100%!important}}</style>
