<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { t } from '../../i18n/runtime'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import { applyGroundHeartbeatInventory, getGroundHeartbeat, previewGroundHeartbeatInventory, requestGroundSyslogControl } from '../../api/groundUnattended'
import { useExternalTerminalLauncher } from '../../composables/useExternalTerminalLauncher'
import type { NcTableColumn } from '../../components/table'
import type { GroundEndpoint, GroundPingTarget, GroundTrain, GroundHeartbeatPage, GroundHeartbeatMr, GroundHeartbeatTrain, GroundHeartbeatInventoryAction, GroundHeartbeatInventoryPreview } from '../../types/groundUnattended'
import MrMonitoringDrawer from '../../components/ground-unattended/MrMonitoringDrawer.vue'
import { useGroundContext } from './useGroundUnattended'
const props = defineProps<{
  trains: GroundTrain[]; pingTargets: GroundPingTarget[]; trainColumns: NcTableColumn<GroundTrain>[]; pingColumns: NcTableColumn<GroundPingTarget>[]
  trainTableMaxHeight?: string | number; pingTableMaxHeight?: string | number; trainFilter: string
  pingFilter: { query: string; endpoint: string; station: string; section: string; minLoss: number }
  locationStats: { ap: number; station: number; unmatched: number; excluded: number }
  statusLabel: (value: unknown) => string; statusType: (value: string) => string
  endpoint: (row: GroundTrain, role: 'CT' | 'CW') => GroundEndpoint | undefined
  endpointRadioTooltip: (row: GroundTrain, role: 'CT' | 'CW') => string; controlSourceLabel: (value: unknown) => string
}>()
const emit = defineEmits<{
  (event: 'update:trainFilter', value: string): void; (event: 'update:pingFilter', value: typeof props.pingFilter): void
  (event: 'refresh'): void; (event: 'show-train', row: GroundTrain): void; (event: 'toggle-priority', row: GroundTrain): void
  (event: 'toggle-enabled', row: GroundTrain): void; (event: 'show-ping-series', row: GroundPingTarget): void; (event: 'quick-ping', mrUuid: string): void
}>()
const { activeTab, pageVisible, pageActivated, selectedRunId, quickContextRevision, status: monitorStatus } = useGroundContext()
const heartbeat = ref<GroundHeartbeatPage | null>(null), heartbeatError = ref(''), loading = ref(false)
const search = ref(props.trainFilter), statusFilter = ref(''), station = ref(''), role = ref(''), abnormalOnly = ref(false), page = ref(1), pageSize = ref(50)
const onlineOnly = ref(true), selectedSyslogMrs = ref<string[]>([]), syslogBusy = ref(false)
const paused = ref(false), managementBusy = ref(false), managementPreview = ref<GroundHeartbeatInventoryPreview | null>(null), managementError = ref('')
const managementEnabled = computed(() => isFeatureEnabled('capability.ground_unattended.heartbeat_inventory_manage'))
const selectedMr = ref<GroundHeartbeatMr | null>(null), selectedSection = ref('all')
const menu = ref<{ mr: GroundHeartbeatMr; x: number; y: number } | null>(null)
const viewMode = ref<'vehicles' | 'aps'>('vehicles')
const mounted = ref(false), active = computed(() => mounted.value && pageVisible.value && pageActivated.value && activeTab.value === 'heartbeat')
const monitoringRunning = computed(() => monitorStatus?.value?.state === 'RUNNING')
const heartbeatMrs = computed(() => heartbeat.value?.mrs || [])
const quickPingVisible = computed(() => isFeatureVisible('ground_unattended.quick_ping') && isFeatureVisible('capability.ground_unattended.quick_ping'))
const quickPingEnabled = computed(() => isFeatureEnabled('ground_unattended.quick_ping') && isFeatureEnabled('capability.ground_unattended.quick_ping'))
const terminalEnabled = computed(() => isFeatureEnabled('capability.desktop_native_integration'))
const terminal = useExternalTerminalLauncher()
let generation = 0, controller: AbortController | null = null, timer: ReturnType<typeof setTimeout> | undefined, debounce: ReturnType<typeof setTimeout> | undefined
let pollDelayMs = 3000
const labels: Record<string, string> = { ONLINE: '在线', OFFLINE: '离线', OFFLINE_PENDING: '待确认', RECOVERING: '恢复中', UNKNOWN: '待检测', STALE: '数据过期', PAUSED: '已暂停', STOPPED: '已停止', BOTH_ONLINE: '双端在线', CT_ONLY: '仅 CT 可达', CW_ONLY: '仅 CW 可达', BOTH_UNREACHABLE_PENDING: '双端待确认', TRAIN_OFFLINE: '整车离线', SINGLE_ONLINE: '单端在线', SINGLE_OFFLINE: '单端离线', SINGLE_UNREACHABLE_PENDING: '单端待确认' }
const dataStateLabels: Record<string, string> = { NO_INVENTORY: '暂无监测设备', DISABLED: '心跳监测已停用', STOPPED: '心跳监测已停止', NOT_STARTED: '监测任务未启动', INITIALIZING: '心跳任务初始化中', RUNNING: '正在实时检测', PAUSED: '心跳任务已暂停', STALE: '数据已过期', WAITING_FOR_SAMPLES: '设备已生成，等待首个采样', ERROR: '心跳任务异常' }
function stateLabel(value: string): string { return t(`ground.monitor.state_${value}`, labels[value] || value) }
function stateType(value: string): 'success' | 'danger' | 'warning' | 'info' { return ['ONLINE', 'BOTH_ONLINE', 'SINGLE_ONLINE'].includes(value) ? 'success' : ['OFFLINE', 'TRAIN_OFFLINE', 'SINGLE_OFFLINE'].includes(value) ? 'danger' : ['UNKNOWN', 'STOPPED'].includes(value) ? 'info' : 'warning' }
function mrFor(trainId: string, role: string): GroundHeartbeatMr | undefined { return heartbeatMrs.value.find((mr) => mr.train_id === trainId && mr.role === role) }
function statusText(value: string | undefined): string { return value ? t(`ground.monitor.data_${value}`, dataStateLabels[value] || value) : '加载中' }
function displayMrStatus(mr: GroundHeartbeatMr): string { return dataState.value === 'PAUSED' ? 'PAUSED' : ['DISABLED', 'STOPPED'].includes(dataState.value) ? 'STOPPED' : dataState.value === 'STALE' ? 'STALE' : mr.status }
function displayTrainStatus(train: GroundTrain | GroundHeartbeatTrain): string { return dataState.value === 'PAUSED' ? 'PAUSED' : ['DISABLED', 'STOPPED'].includes(dataState.value) ? 'STOPPED' : dataState.value === 'STALE' ? 'STALE' : ('status' in train ? train.status : 'UNKNOWN') }
function formatRtt(value: number | null | undefined): string { return value == null ? '—' : `${value.toFixed(1)} ms` }
function formatLoss(mr: GroundHeartbeatMr): string {
  const sent = (mr?.ip_states || []).reduce((sum, row) => sum + (row.sent_count || 0), 0)
  const lost = (mr?.ip_states || []).reduce((sum, row) => sum + (row.lost_count || 0), 0)
  return sent ? `${(lost / sent * 100).toFixed(2)}%` : '—'
}
function endpointName(mr: GroundHeartbeatMr): string { return mr.mr_name || mr.mr_uuid }
function associatedAps(mr: GroundHeartbeatMr) { return mr.associated_aps || [] }
function visibleAps(mr: GroundHeartbeatMr) { return associatedAps(mr).slice(0, 3) }
function hiddenApCount(mr: GroundHeartbeatMr) { return Math.max(0, associatedAps(mr).length - visibleAps(mr).length) }
function stationNames(mr: GroundHeartbeatMr): string[] { return Array.from(new Set([...(mr.associated_stations || []), ...(mr.station ? [mr.station] : [])])) }
function apSummary(mr: GroundHeartbeatMr): string { return associatedAps(mr).map((ap) => ap.name || ap.bssid || ap.mac).filter(Boolean).join('、') }
const apRows = computed(() => heartbeatMrs.value.slice().sort((a, b) => `${a.train_no}-${a.role}`.localeCompare(`${b.train_no}-${b.role}`, undefined, { numeric: true })))
const syslogRows = computed(() => apRows.value.filter((mr) => (!onlineOnly.value || mr.status === 'ONLINE') && (!role.value || mr.role === role.value)))
const selectableSyslogRows = computed(() => syslogRows.value.filter((mr) => !!mr.management_ip?.trim()))
const joinAllowed = computed(() => selectedSyslogMrs.value.some((id) => selectableSyslogRows.value.some((mr) => mr.mr_uuid === id && mr.status === 'ONLINE')))
const exitAllowed = computed(() => selectedSyslogMrs.value.some((id) => selectableSyslogRows.value.some((mr) => mr.mr_uuid === id && ['CONFIGURED', 'FAILED', 'UNKNOWN'].includes(mr.syslog_status || ''))))
const dataState = computed(() => heartbeat.value?.data_state || '')
const dataStateMessage = computed(() => heartbeat.value?.data_state_message || '')
const heartbeatStats = computed(() => heartbeat.value?.heartbeat_statistics)
async function loadHeartbeat(): Promise<void> {
  if (!active.value || controller) return
  const current = generation, request = new AbortController(); controller = request; loading.value = true
  try {
    const data = await getGroundHeartbeat(selectedRunId.value, { signal: request.signal }, { query: search.value.trim(), status: statusFilter.value, station: station.value, role: role.value, abnormal_only: abnormalOnly.value, page: page.value, page_size: pageSize.value })
    if (current !== generation || !active.value) return
    heartbeat.value = data; heartbeatError.value = ''; pollDelayMs = 3000
  } catch (error) {
    if (current === generation && !request.signal.aborted) {
      heartbeatError.value = error instanceof Error ? error.message : t('ground.v2.dynamic_66', '心跳状态读取失败')
      pollDelayMs = Math.min(pollDelayMs * 2, 30_000)
    }
  } finally {
    if (current === generation) {
      controller = null; loading.value = false
      scheduleNextPoll()
    }
  }
}
function scheduleNextPoll(): void {
  if (timer) clearTimeout(timer)
  timer = undefined
  if (!active.value || !monitoringRunning.value || paused.value) return
  timer = setTimeout(() => { timer = undefined; void loadHeartbeat() }, pollDelayMs)
}
function stopPolling(): void { generation++; controller?.abort(); controller = null; if (timer) clearTimeout(timer); timer = undefined; if (debounce) clearTimeout(debounce); loading.value = false }
function restart(clear = false): void { stopPolling(); if (clear) { heartbeat.value = null; heartbeatError.value = ''; selectedMr.value = null; menu.value = null }; if (active.value) void loadHeartbeat() }
watch(active, (visible) => {
  if (!visible) { selectedMr.value = null; closeMenu() }
  restart()
})
watch([selectedRunId, quickContextRevision], () => restart(true))
watch(() => monitorStatus?.value?.state, (next, previous) => {
  if (next === previous) return
  stopPolling()
  if (active.value) void loadHeartbeat()
})
watch(search, () => { if (debounce) clearTimeout(debounce); debounce = setTimeout(() => { page.value = 1; restart() }, 250) })
watch([statusFilter, station, role, abnormalOnly, pageSize], () => { if (page.value !== 1) page.value = 1; else restart() })
watch(page, () => restart())
onMounted(() => { mounted.value = true; document.addEventListener('click', closeMenu); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { stopPolling(); document.removeEventListener('click', closeMenu); document.removeEventListener('keydown', onKey) })
function refresh(): void { restart(); emit('refresh') }
function toggleRefresh(): void { paused.value = !paused.value; restart() }
async function previewManagement(action: GroundHeartbeatInventoryAction): Promise<void> {
  managementBusy.value = true; managementError.value = ''; managementPreview.value = null
  try { managementPreview.value = await previewGroundHeartbeatInventory(action) }
  catch (error) { managementError.value = error instanceof Error ? error.message : String(error) }
  finally { managementBusy.value = false }
}
async function applyManagement(): Promise<void> {
  const preview = managementPreview.value
  if (!preview || preview.conflict_count || managementBusy.value) return
  managementBusy.value = true; managementError.value = ''
  try {
    await applyGroundHeartbeatInventory(preview.action, preview.revision)
    managementPreview.value = null; ElMessage.success(t('ground.monitor.management_done', '心跳管理操作已完成')); refresh()
  } catch (error) { managementError.value = error instanceof Error ? error.message : String(error); managementPreview.value = null }
  finally { managementBusy.value = false }
}
function closeMenu(): void { menu.value = null }
function onKey(event: KeyboardEvent): void { if (event.key === 'Escape') closeMenu() }
function openMenu(event: MouseEvent, mr: GroundHeartbeatMr): void { event.preventDefault(); event.stopPropagation(); menu.value = { mr, x: Math.max(0, Math.min(event.clientX, window.innerWidth - 205)), y: Math.max(0, Math.min(event.clientY, window.innerHeight - 270)) } }
function openMonitor(mr: GroundHeartbeatMr, section = 'all'): void { selectedMr.value = mr; selectedSection.value = section; closeMenu() }
function openTrainDetail(train: GroundHeartbeatTrain): void {
  const inventoryTrain = props.trains.find((item) => item.train_id === train.train_id)
  if (inventoryTrain) emit('show-train', inventoryTrain)
  else {
    const mr = mrFor(train.train_id, 'CT') || mrFor(train.train_id, 'CW')
    if (mr) openMonitor(mr)
  }
}
async function openTerminal(mr: GroundHeartbeatMr): Promise<void> {
  closeMenu(); if (!terminalEnabled.value) return
  try {
    const preflight = await terminal.preflightDeviceTerminalTargets([mr.mr_uuid])
    if (!preflight) return
    terminal.showPreflightSkipped(preflight.skippedDevices)
    if (preflight.launchableDevices.length) { const result = await terminal.launchDeviceTerminalTargets(preflight.launchableDevices, preflight.terminalType); if (result) terminal.showLaunchResult(result) }
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : String(error)) }
}
function toggleSyslogMr(id: string, checked: boolean): void {
  selectedSyslogMrs.value = checked ? Array.from(new Set([...selectedSyslogMrs.value, id])) : selectedSyslogMrs.value.filter((item) => item !== id)
}
function toggleFilteredSyslogMrs(checked: boolean): void {
  const visible = selectableSyslogRows.value.map((mr) => mr.mr_uuid)
  selectedSyslogMrs.value = checked
    ? Array.from(new Set([...selectedSyslogMrs.value, ...visible]))
    : selectedSyslogMrs.value.filter((id) => !visible.includes(id))
}
async function controlSyslog(mode: 'JOIN' | 'EXIT'): Promise<void> {
  const eligible = selectableSyslogRows.value.filter((mr) => selectedSyslogMrs.value.includes(mr.mr_uuid) && (mode === 'JOIN' ? mr.status === 'ONLINE' : true))
  if (!eligible.length) return
  syslogBusy.value = true
  try {
    const result = await requestGroundSyslogControl(eligible.map((mr) => mr.mr_uuid), mode)
    ElMessage.success(result.message || (mode === 'JOIN' ? '已提交加入请求' : '已提交退出请求'))
    selectedSyslogMrs.value = []
    restart()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    syslogBusy.value = false
  }
}
const metrics = computed(() => {
  const counts = heartbeat.value?.train_counts || {}
  const hasSamples = (heartbeatStats.value?.sent_count || 0) > 0 || heartbeatMrs.value.some((mr) => mr.ip_states.some((ip) => ip.sent_count > 0))
  return [
    { label: t('ground.monitor.trains', '列车总数'), value: Object.values(counts).reduce((sum, value) => sum + value, 0) },
    { label: t('ground.monitor.both_online', '双端在线'), value: hasSamples ? counts.BOTH_ONLINE || 0 : '—' },
    { label: t('ground.monitor.one_online', '单端可达'), value: hasSamples ? (counts.CT_ONLY || 0) + (counts.CW_ONLY || 0) + (counts.SINGLE_ONLINE || 0) : '—' },
    { label: t('ground.monitor.train_offline', '整车离线'), value: hasSamples ? (counts.TRAIN_OFFLINE || 0) + (counts.SINGLE_OFFLINE || 0) : '—' },
    { label: t('ground.monitor.mr_total', '监测 MR'), value: heartbeat.value?.total_mrs ?? heartbeat.value?.mrs.length ?? 0 },
    { label: t('ground.monitor.mr_online', '在线 MR'), value: hasSamples ? heartbeat.value?.mr_counts?.ONLINE || 0 : '—' },
    { label: t('ground.monitor.mr_pending', '待检测 MR'), value: heartbeat.value?.mr_counts?.UNKNOWN || 0 },
  ]
})
</script>
<template>
  <section class="heartbeat-page">
    <header class="heading"><div><h2>{{ t('ground.monitor.title', '心跳检测') }}</h2><span class="subtitle">{{ t('ground.monitor.subtitle', '车载 AP 心跳监测 · 实时在线状态') }}</span><span class="muted">{{ heartbeat?.run_id || selectedRunId || t('ground.monitor.no_run', '未选择运行') }} · {{ heartbeat?.run_state || t('ground.monitor.not_started', '未启动') }}</span></div><div class="heading-actions"><el-button :loading="managementBusy" :disabled="!managementEnabled" @click="previewManagement('SYNC')">{{ t('ground.monitor.sync_devices', '重新同步设备') }}</el-button><el-button :disabled="!managementEnabled || managementBusy" @click="previewManagement('CLEAR_DATA')">{{ t('ground.monitor.clear_data', '清空心跳数据') }}</el-button><el-button @click="toggleRefresh">{{ paused ? t('ground.monitor.resume_refresh', '恢复刷新') : t('ground.monitor.pause_refresh', '暂停刷新') }}</el-button><el-button :loading="loading" @click="refresh">{{ t('common.refresh', '刷新') }}</el-button></div></header>
    <el-alert v-if="heartbeatError" :title="heartbeatError" type="error" :closable="false" />
    <el-alert v-if="managementError" :title="managementError" type="error" closable @close="managementError = ''" />
    <template v-if="heartbeat">
      <div class="state-banner" :class="`state-${dataState.toLowerCase()}`"><strong>{{ statusText(dataState) }}</strong><span>{{ dataStateMessage }}</span><small v-if="heartbeat.data_state === 'STALE'">{{ heartbeatStats?.latest_sample_at || '—' }}</small></div>
      <div class="metrics"><div v-for="item in metrics" :key="item.label"><span>{{ item.label }}</span><b>{{ item.value }}</b></div></div>
      <div class="heartbeat-stats"><span>{{ t('ground.monitor.ping_total', '累计 Ping') }} <b>{{ heartbeatStats?.sent_count ?? '—' }}</b></span><span>{{ t('ground.monitor.ping_success', '成功次数') }} <b>{{ heartbeatStats?.success_count ?? '—' }}</b></span><span>{{ t('ground.monitor.ping_lost', '丢包次数') }} <b>{{ heartbeatStats?.lost_count ?? '—' }}</b></span><span>{{ t('ground.monitor.average_rtt', '平均 RTT') }} <b>{{ formatRtt(heartbeatStats?.average_rtt_ms) }}</b></span><span>{{ t('ground.monitor.current_loss', '当前丢包率') }} <b>{{ heartbeatStats?.loss_rate_percent == null ? '—' : `${heartbeatStats.loss_rate_percent.toFixed(2)}%` }}</b></span><span>{{ t('ground.monitor.updated_at', '最近更新时间') }} <b>{{ heartbeatStats?.latest_sample_at || '—' }}</b></span></div>
      <div class="view-tabs"><el-button :type="viewMode === 'vehicles' ? 'primary' : 'default'" @click="viewMode = 'vehicles'">{{ t('ground.monitor.vehicle_view', '车辆视图') }}</el-button><el-button :type="viewMode === 'aps' ? 'primary' : 'default'" @click="viewMode = 'aps'">{{ t('ground.monitor.ap_view', 'AP 列表') }}</el-button></div>
      <div class="filters"><el-input v-model="search" clearable :placeholder="t('ground.monitor.search', '搜索列车 / 接入区间 AP / UUID')" /><el-select v-model="role" clearable :placeholder="t('ground.monitor.role', '端别')"><el-option label="CT" value="CT" /><el-option label="CW" value="CW" /></el-select><el-select v-model="statusFilter" clearable :placeholder="t('ground.monitor.train_state', '全部状态')"><el-option v-for="value in ['BOTH_ONLINE','CT_ONLY','CW_ONLY','TRAIN_OFFLINE','BOTH_UNREACHABLE_PENDING','SINGLE_ONLINE','SINGLE_OFFLINE','UNKNOWN']" :key="value" :value="value" :label="stateLabel(value)" /></el-select><el-select v-model="station" clearable :placeholder="t('ground.station', '全部站点')"><el-option v-for="item in heartbeat.stations || []" :key="item" :value="item" :label="item" /></el-select><el-checkbox v-model="abnormalOnly">{{ t('ground.monitor.abnormal', '仅异常') }}</el-checkbox></div>
      <section class="syslog-control" aria-label="Syslog 人工控制">
        <div class="syslog-toolbar"><strong>MR Syslog 控制</strong><el-checkbox v-model="onlineOnly">仅显示在线 MR</el-checkbox><el-checkbox :model-value="selectableSyslogRows.length > 0 && selectableSyslogRows.every((mr) => selectedSyslogMrs.includes(mr.mr_uuid))" @change="toggleFilteredSyslogMrs(Boolean($event))">选择当前筛选 {{ selectableSyslogRows.length }} 台</el-checkbox><span class="muted">已选 {{ selectedSyslogMrs.length }} 台</span><el-button :loading="syslogBusy" :disabled="!joinAllowed || syslogBusy" type="primary" @click="controlSyslog('JOIN')">加入 Syslog 上报</el-button><el-button :loading="syslogBusy" :disabled="!exitAllowed || syslogBusy" @click="controlSyslog('EXIT')">退出 Syslog 上报</el-button></div>
        <div class="syslog-table"><div v-for="mr in syslogRows" :key="mr.mr_uuid" class="syslog-row"><el-checkbox :model-value="selectedSyslogMrs.includes(mr.mr_uuid)" :disabled="!mr.management_ip" :aria-label="`选择 ${endpointName(mr)}`" @change="toggleSyslogMr(mr.mr_uuid, Boolean($event))" /><strong>{{ endpointName(mr) }}</strong><span>{{ mr.train_no || mr.train_id }} · {{ mr.role }}</span><span>管理 {{ mr.management_ip || '无有效地址' }}</span><span>备用 {{ mr.backup_management_ip || '—' }}</span><el-tag size="small" :type="stateType(mr.status)">{{ stateLabel(mr.status) }}</el-tag><el-tag size="small" effect="plain">Syslog {{ mr.syslog_status || 'UNKNOWN' }}</el-tag></div><div v-if="!syslogRows.length" class="syslog-empty">当前筛选没有 MR</div></div>
      </section>
    </template>
    <div v-if="!heartbeat" class="empty" role="status"><span v-if="!heartbeatError">{{ t('common.loading', '加载中') }}</span></div>
    <div v-else-if="!heartbeat.trains.length" class="empty">{{ dataState === 'NO_INVENTORY' ? t('ground.monitor.sync_hint', '当前没有监测设备，请先同步设备') : t('ground.monitor.no_match', '当前筛选条件没有匹配结果') }}</div>
    <div v-else-if="viewMode === 'vehicles'" class="train-list"><article v-for="train in heartbeat.trains" :key="train.train_id" class="train-row" tabindex="0" @click="openMonitor(mrFor(train.train_id, 'CT') || mrFor(train.train_id, 'CW')!)">
      <div class="train-ident"><span class="eyebrow">{{ t('ground.monitor.train', '列车') }}</span><strong>{{ train.train_no || train.train_id }}</strong><small>{{ train.train_id }}</small></div>
      <template v-for="role in ['CT', 'CW']" :key="role"><div v-if="mrFor(train.train_id, role)" class="mr-card" tabindex="0" role="button" :aria-label="`${role} ${t('ground.monitor.open', '打开综合监测')}`" @click.stop="openMonitor(mrFor(train.train_id, role)!)" @keydown.enter.stop="openMonitor(mrFor(train.train_id, role)!)" @contextmenu="openMenu($event, mrFor(train.train_id, role)!)">
        <div class="mr-card-heading"><strong>{{ role }}</strong><el-tag size="small" :type="stateType(displayMrStatus(mrFor(train.train_id, role)!))">{{ stateLabel(displayMrStatus(mrFor(train.train_id, role)!)) }}</el-tag><span class="rtt">{{ mrFor(train.train_id, role)!.current_rtt_ms == null ? 'RTT —' : `RTT ${mrFor(train.train_id, role)!.current_rtt_ms} ms` }}</span><button class="more" :aria-label="t('ground.monitor.actions', '操作菜单')" @click.stop="openMenu($event, mrFor(train.train_id, role)!)">⋮</button></div>
        <div class="mr-name"><strong>{{ endpointName(mrFor(train.train_id, role)!) }}</strong><span>{{ mrFor(train.train_id, role)!.station || mrFor(train.train_id, role)!.section || '—' }}</span></div>
        <div class="connection-context"><div class="context-label">{{ t('ground.monitor.section_ap', '接入区间 AP') }}</div><div v-if="visibleAps(mrFor(train.train_id, role)!).length" class="tag-list"><el-tag v-for="ap in visibleAps(mrFor(train.train_id, role)!)" :key="`${ap.name}-${ap.bssid}-${ap.mac}`" size="small" effect="plain">{{ ap.name || ap.bssid || ap.mac }}</el-tag><el-tag v-if="hiddenApCount(mrFor(train.train_id, role)!)" size="small" effect="plain" class="more-tag">+{{ hiddenApCount(mrFor(train.train_id, role)!) }}</el-tag></div><span v-else class="muted-value">{{ t('ground.monitor.no_ap', '暂无关联 AP') }}</span></div>
        <div class="connection-context"><div class="context-label">{{ t('ground.monitor.access_station', '接入站点') }}</div><div v-if="stationNames(mrFor(train.train_id, role)!).length" class="tag-list"><el-tag v-for="name in stationNames(mrFor(train.train_id, role)!)" :key="name" size="small" effect="plain">{{ name }}</el-tag></div><span v-else class="muted-value">{{ t('ground.monitor.no_station', '未关联站点') }}</span></div>
        <div class="mr-meta"><span>{{ t('ground.monitor.last_success', '最近成功') }} {{ mrFor(train.train_id, role)!.last_success_at || '—' }}</span><span>{{ t('ground.monitor.loss', '丢包率') }} {{ formatLoss(mrFor(train.train_id, role)!) }}</span></div>
      </div><div v-else class="mr-card absent"><strong>{{ role }}</strong><span>{{ t('ground.monitor.no_endpoint', '无端点快照') }}</span></div></template>
      <div class="train-summary"><span class="context-label">{{ t('ground.monitor.vehicle_status', '整车状态') }}</span><el-tag size="small" :type="stateType(displayTrainStatus(train))">{{ stateLabel(displayTrainStatus(train)) }}</el-tag><button @click.stop="openTrainDetail(train)">{{ t('ground.monitor.detail', '整车详情') }}</button></div>
    </article></div>
    <div v-else class="ap-list"><article v-for="mr in apRows" :key="mr.mr_uuid" class="ap-row" tabindex="0" @click="openMonitor(mr)" @contextmenu="openMenu($event, mr)"><div class="ap-main"><strong>{{ endpointName(mr) }}</strong><span>{{ mr.train_no || mr.train_id }} · {{ mr.role }}</span></div><el-tag size="small" :type="stateType(displayMrStatus(mr))">{{ stateLabel(displayMrStatus(mr)) }}</el-tag><span class="ap-cell"><span class="context-label">{{ t('ground.monitor.section_ap', '接入区间 AP') }}</span>{{ apSummary(mr) || t('ground.monitor.no_ap', '暂无关联 AP') }}</span><span class="ap-cell"><span class="context-label">{{ t('ground.monitor.access_station', '接入站点') }}</span>{{ stationNames(mr).join('、') || t('ground.monitor.no_station', '未关联站点') }}</span><span>{{ formatRtt(mr.current_rtt_ms) }}</span><span>{{ formatLoss(mr) }}</span><button @click.stop="openMonitor(mr)">{{ t('ground.monitor.detail', '详情') }}</button></article></div>
    <el-pagination v-if="heartbeat" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[25, 50, 100, 200]" :total="heartbeat.total ?? heartbeat.trains.length" layout="total, sizes, prev, pager, next" />
    <el-dialog :model-value="!!managementPreview" :title="managementPreview?.action === 'SYNC' ? t('ground.monitor.sync_preview', '同步设备预览') : managementPreview?.action === 'CLEAR_DEVICES' ? t('ground.monitor.clear_devices', '清空监测设备') : t('ground.monitor.clear_data', '清空心跳数据')" width="min(600px, 94vw)" @close="managementPreview = null">
      <template v-if="managementPreview"><p>{{ t('ground.monitor.site', '当前 Site') }}: {{ managementPreview.site_id }}</p><p v-if="managementPreview.action === 'SYNC'">{{ t('ground.monitor.preview_counts', '新增 / 更新 / 停用 / 冲突') }}: {{ managementPreview.added_count }} / {{ managementPreview.updated_count }} / {{ managementPreview.disabled_count }} / {{ managementPreview.conflict_count }}</p><p v-else>{{ t('ground.monitor.affected', '涉及车辆 / 监测设备 / 心跳记录') }}: {{ managementPreview.train_count }} / {{ managementPreview.device_count }} / {{ managementPreview.affected_history_count }}</p><p>{{ t('ground.monitor.retained', '保留历史记录') }}: {{ managementPreview.retained_history_count }}</p><p v-if="managementPreview.action === 'CLEAR_DEVICES'">{{ t('ground.monitor.clear_devices_scope', '仅停用心跳监测对象，不删除设备管理资产；可重新同步。') }}</p><p v-if="managementPreview.action === 'CLEAR_DATA'">{{ t('ground.monitor.clear_data_scope', '清理心跳状态和心跳事件，历史采样在心跳视图中按清理时间隔离；共享 Ping 汇总、原始文件及其他业务数据保留。') }}</p><el-alert v-if="managementPreview.conflict_count" type="error" :closable="false" :title="t('ground.monitor.conflicts', '设备身份或端别冲突，请先修复设备资料')" /><ul v-if="managementPreview.conflicts.length"><li v-for="conflict in managementPreview.conflicts" :key="conflict">{{ conflict }}</li></ul></template>
      <template #footer><el-button @click="managementPreview = null">{{ t('common.cancel', '取消') }}</el-button><el-button type="primary" :loading="managementBusy" :disabled="!!managementPreview?.conflict_count" @click="applyManagement">{{ t('common.confirm', '确认') }}</el-button></template>
    </el-dialog>
    <teleport to="body"><div v-if="menu" class="mr-context-menu" :style="{ left: `${menu.x}px`, top: `${menu.y}px` }" role="menu" @click.stop><button role="menuitem" :disabled="!terminalEnabled" @click="openTerminal(menu.mr)">{{ t('ground.monitor.terminal', '外部终端') }}</button><button role="menuitem" @click="openMonitor(menu.mr)">{{ t('ground.monitor.all', '综合监测') }}</button><button role="menuitem" @click="openMonitor(menu.mr, 'ping')">Ping</button><button role="menuitem" @click="openMonitor(menu.mr, 'ap')">{{ t('ground.monitor.ap_history', '连接 AP 历史') }}</button><button role="menuitem" @click="openMonitor(menu.mr, 'mesh')">{{ t('ground.monitor.mesh_syslog', 'Mesh 切换日志') }}</button><button role="menuitem" @click="openMonitor(menu.mr, 'timeline')">{{ t('ground.monitor.timeline', '事件时间轴') }}</button><button v-if="quickPingVisible" role="menuitem" :disabled="!quickPingEnabled" @click="emit('quick-ping', menu.mr.mr_uuid); closeMenu()">{{ t('ground.quick_ping', '快速 Ping') }}</button></div></teleport>
    <MrMonitoringDrawer v-if="selectedMr" :mr="selectedMr" :run-id="heartbeat?.run_id || selectedRunId" :active="active" :section="selectedSection" :monitor-state="dataState" :terminal-enabled="terminalEnabled" :quick-enabled="quickPingVisible && quickPingEnabled" @close="selectedMr = null" @terminal="openTerminal(selectedMr!)" @quick-ping="emit('quick-ping', selectedMr!.mr_uuid)" />
  </section>
</template>
<style scoped>
.heartbeat-page{display:flex;flex-direction:column;gap:12px;min-width:0}.heading{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.heading h2{font-size:22px;margin:0 0 4px}.subtitle{display:block;color:var(--el-text-color-regular);font-size:13px;margin-bottom:4px}.heading-actions{display:flex;justify-content:flex-end;gap:6px;flex-wrap:wrap}.muted{display:block;color:var(--el-text-color-secondary);font-size:12px}.state-banner{display:flex;align-items:center;gap:10px;padding:8px 12px;border-left:3px solid var(--el-color-info);background:var(--el-fill-color-light);font-size:13px}.state-banner span{color:var(--el-text-color-secondary)}.state-banner small{margin-left:auto;color:var(--el-text-color-secondary)}.state-running{border-color:var(--el-color-success)}.state-stale,.state-error{border-color:var(--el-color-warning)}.state-no_inventory,.state-disabled{border-color:var(--el-color-info)}.metrics{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}.metrics>div{display:flex;flex-direction:column;gap:5px;padding:10px 12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-light)}.metrics span,.heartbeat-stats span{font-size:12px;color:var(--el-text-color-secondary)}.metrics b{font-size:22px}.heartbeat-stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.heartbeat-stats span{display:flex;flex-direction:column;gap:4px;padding:7px 10px;background:var(--el-bg-color);border-bottom:1px solid var(--el-border-color-lighter)}.heartbeat-stats b{color:var(--el-text-color-primary);font-size:13px;overflow-wrap:anywhere}.view-tabs{display:flex;gap:6px}.filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:9px;border:1px solid var(--el-border-color-lighter);background:var(--el-bg-color)}.filters .el-input{width:280px}.filters .el-select{width:150px}.train-list,.ap-list{display:flex;flex-direction:column;gap:6px}.train-row{display:grid;grid-template-columns:88px minmax(280px,1fr) minmax(280px,1fr) 150px;gap:8px;align-items:stretch;border-bottom:1px solid var(--el-border-color-lighter);padding:4px 0 10px}.train-row:focus-visible{outline:2px solid var(--el-color-primary);outline-offset:2px}.train-ident{display:flex;align-items:flex-start;justify-content:center;flex-direction:column;gap:4px;padding:6px}.train-ident strong{font-size:16px;overflow-wrap:anywhere}.train-ident small,.eyebrow{font-size:11px;color:var(--el-text-color-secondary)}.mr-card{min-width:0;padding:9px 10px;border:1px solid var(--el-border-color-light);border-radius:4px;cursor:pointer;background:var(--el-bg-color)}.mr-card:hover,.mr-card:focus-visible{border-color:var(--el-color-primary)}.mr-card-heading{display:flex;align-items:center;gap:8px}.mr-card-heading strong{font-size:14px}.rtt{margin-left:auto;color:var(--el-text-color-secondary);font-size:12px}.more{border:0;background:transparent;color:var(--el-text-color-secondary);font-size:18px;cursor:pointer;padding:0 4px}.mr-name{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;overflow-wrap:anywhere}.mr-name span,.mr-meta,.absent span,.muted-value{color:var(--el-text-color-secondary);font-size:12px}.connection-context{margin-top:8px}.context-label{display:block;color:var(--el-text-color-secondary);font-size:11px;margin-bottom:4px}.tag-list{display:flex;gap:5px;flex-wrap:wrap}.more-tag{cursor:pointer}.mr-meta{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px;font-size:11px}.absent{display:flex;align-items:center;gap:10px;cursor:default;background:var(--el-fill-color-light)}.train-summary{display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:7px;font-size:12px;color:var(--el-text-color-secondary);padding:6px}.train-summary button,.train-actions button,.ap-row button{border:0;background:transparent;color:var(--el-color-primary);cursor:pointer;text-align:left;padding:0}.ap-row{display:grid;grid-template-columns:minmax(180px,1.4fr) 90px minmax(180px,1fr) minmax(150px,1fr) 90px 80px 54px;gap:10px;align-items:center;padding:10px 8px;border-bottom:1px solid var(--el-border-color-lighter);font-size:12px}.ap-row:hover,.ap-row:focus-visible{background:var(--el-fill-color-light);outline:none}.ap-main{display:flex;flex-direction:column;gap:4px}.ap-main span,.ap-row>span{color:var(--el-text-color-secondary)}.ap-cell{display:flex;flex-direction:column;gap:3px}.empty{padding:32px;text-align:center;color:var(--el-text-color-secondary)}@media(max-width:1450px){.metrics{grid-template-columns:repeat(4,minmax(0,1fr))}.heartbeat-stats{grid-template-columns:repeat(3,minmax(0,1fr))}.train-row{grid-template-columns:76px minmax(240px,1fr) minmax(240px,1fr) 132px}}@media(max-width:1200px){.metrics{grid-template-columns:repeat(3,minmax(0,1fr))}.train-row{grid-template-columns:72px minmax(210px,1fr) minmax(210px,1fr) 120px}}@media(max-width:800px){.metrics,.heartbeat-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.heading-actions{width:100%;justify-content:flex-start}.train-row{grid-template-columns:1fr 1fr}.train-ident{grid-column:1/-1;flex-direction:row;justify-content:flex-start}.train-summary{grid-column:1/-1;flex-direction:row;align-items:center}.ap-row{grid-template-columns:1fr 1fr}.filters .el-input{width:100%}}@media(max-width:480px){.train-row{grid-template-columns:1fr}.train-ident{grid-column:auto}.train-summary{grid-column:auto;align-items:flex-start}.heartbeat-stats,.metrics{grid-template-columns:1fr}.ap-row{grid-template-columns:1fr}}
</style>
<style scoped>.train-row{grid-template-columns:88px minmax(280px,1fr) minmax(280px,1fr) 124px}.train-summary{align-items:center;text-align:center}.train-summary button{white-space:nowrap}@media(max-width:1450px){.train-row{grid-template-columns:76px minmax(240px,1fr) minmax(240px,1fr) 116px}}@media(max-width:1200px){.train-row{grid-template-columns:72px minmax(210px,1fr) minmax(210px,1fr) 108px}}</style>
<style>.mr-context-menu{position:fixed;z-index:4000;display:flex;flex-direction:column;min-width:190px;padding:4px;background:var(--el-bg-color-overlay);border:1px solid var(--el-border-color-light);box-shadow:var(--el-box-shadow-light)}.mr-context-menu button{border:0;background:transparent;color:var(--el-text-color-primary);text-align:left;padding:8px 12px;cursor:pointer}.mr-context-menu button:hover{background:var(--el-fill-color-light)}.mr-context-menu button:disabled{color:var(--el-disabled-text-color);cursor:not-allowed}</style>
