<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { t } from '../../i18n/runtime'
import { isFeatureEnabled, isFeatureVisible } from '../../features'
import { getGroundHeartbeat } from '../../api/groundUnattended'
import { useExternalTerminalLauncher } from '../../composables/useExternalTerminalLauncher'
import type { NcTableColumn } from '../../components/table'
import type { GroundEndpoint, GroundPingTarget, GroundTrain, GroundHeartbeatPage, GroundHeartbeatMr } from '../../types/groundUnattended'
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
const { activeTab, pageVisible, pageActivated, selectedRunId, quickContextRevision } = useGroundContext()
const heartbeat = ref<GroundHeartbeatPage | null>(null), heartbeatError = ref(''), loading = ref(false)
const search = ref(props.trainFilter), status = ref(''), station = ref(''), abnormalOnly = ref(false), page = ref(1), pageSize = ref(50)
const selectedMr = ref<GroundHeartbeatMr | null>(null), selectedSection = ref('all')
const menu = ref<{ mr: GroundHeartbeatMr; x: number; y: number } | null>(null)
const mounted = ref(false), active = computed(() => mounted.value && pageVisible.value && pageActivated.value && activeTab.value === 'heartbeat')
const heartbeatMrs = computed(() => heartbeat.value?.mrs || [])
const quickPingVisible = computed(() => isFeatureVisible('ground_unattended.quick_ping') && isFeatureVisible('capability.ground_unattended.quick_ping'))
const quickPingEnabled = computed(() => isFeatureEnabled('ground_unattended.quick_ping') && isFeatureEnabled('capability.ground_unattended.quick_ping'))
const terminalEnabled = computed(() => isFeatureEnabled('capability.desktop_native_integration'))
const terminal = useExternalTerminalLauncher()
let generation = 0, controller: AbortController | null = null, timer: ReturnType<typeof setInterval> | undefined, debounce: ReturnType<typeof setTimeout> | undefined
const labels: Record<string, string> = { ONLINE: '在线', OFFLINE: '离线', OFFLINE_PENDING: '待确认', RECOVERING: '恢复中', UNKNOWN: '未知', BOTH_ONLINE: '双端在线', CT_ONLY: '仅 CT 可达', CW_ONLY: '仅 CW 可达', BOTH_UNREACHABLE_PENDING: '双端待确认', TRAIN_OFFLINE: '整车离线', SINGLE_ONLINE: '单端在线', SINGLE_OFFLINE: '单端离线', SINGLE_UNREACHABLE_PENDING: '单端待确认', SINGLE_RECOVERING: '单端恢复中' }
function stateLabel(value: string): string { return t(`ground.monitor.state_${value}`, labels[value] || value) }
function stateType(value: string): 'success' | 'danger' | 'warning' | 'info' { return ['ONLINE', 'BOTH_ONLINE', 'SINGLE_ONLINE'].includes(value) ? 'success' : ['OFFLINE', 'TRAIN_OFFLINE', 'SINGLE_OFFLINE'].includes(value) ? 'danger' : value === 'UNKNOWN' ? 'info' : 'warning' }
function mrFor(trainId: string, role: string): GroundHeartbeatMr | undefined { return heartbeatMrs.value.find((mr) => mr.train_id === trainId && mr.role === role) }
async function loadHeartbeat(): Promise<void> {
  if (!active.value || controller) return
  const current = generation, request = new AbortController(); controller = request; loading.value = true
  try {
    const data = await getGroundHeartbeat(selectedRunId.value, { signal: request.signal }, { query: search.value.trim(), status: status.value, station: station.value, abnormal_only: abnormalOnly.value, page: page.value, page_size: pageSize.value })
    if (current !== generation || !active.value) return
    heartbeat.value = data; heartbeatError.value = ''
  } catch (error) { if (current === generation && !request.signal.aborted) heartbeatError.value = error instanceof Error ? error.message : t('ground.v2.dynamic_66', '心跳状态读取失败') }
  finally { if (current === generation) { controller = null; loading.value = false } }
}
function stopPolling(): void { generation++; controller?.abort(); controller = null; if (timer) clearInterval(timer); timer = undefined; if (debounce) clearTimeout(debounce); loading.value = false }
function restart(clear = false): void { stopPolling(); if (clear) { heartbeat.value = null; heartbeatError.value = ''; selectedMr.value = null; menu.value = null }; if (active.value) { void loadHeartbeat(); timer = setInterval(() => { void loadHeartbeat() }, 3000) } }
watch([active, selectedRunId, quickContextRevision], () => restart(true))
watch(search, () => { if (debounce) clearTimeout(debounce); debounce = setTimeout(() => { page.value = 1; restart() }, 250) })
watch([status, station, abnormalOnly, pageSize], () => { if (page.value !== 1) page.value = 1; else restart() })
watch(page, () => restart())
onMounted(() => { mounted.value = true; document.addEventListener('click', closeMenu); document.addEventListener('keydown', onKey) })
onBeforeUnmount(() => { stopPolling(); document.removeEventListener('click', closeMenu); document.removeEventListener('keydown', onKey) })
function refresh(): void { restart(); emit('refresh') }
function closeMenu(): void { menu.value = null }
function onKey(event: KeyboardEvent): void { if (event.key === 'Escape') closeMenu() }
function openMenu(event: MouseEvent, mr: GroundHeartbeatMr): void { event.preventDefault(); event.stopPropagation(); menu.value = { mr, x: Math.max(0, Math.min(event.clientX, window.innerWidth - 205)), y: Math.max(0, Math.min(event.clientY, window.innerHeight - 270)) } }
function openMonitor(mr: GroundHeartbeatMr, section = 'all'): void { selectedMr.value = mr; selectedSection.value = section; closeMenu() }
async function openTerminal(mr: GroundHeartbeatMr): Promise<void> {
  closeMenu(); if (!terminalEnabled.value) return
  try {
    const preflight = await terminal.preflightDeviceTerminalTargets([mr.mr_uuid])
    if (!preflight) return
    terminal.showPreflightSkipped(preflight.skippedDevices)
    if (preflight.launchableDevices.length) { const result = await terminal.launchDeviceTerminalTargets(preflight.launchableDevices, preflight.terminalType); if (result) terminal.showLaunchResult(result) }
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : String(error)) }
}
const metrics = computed(() => {
  const counts = heartbeat.value?.train_counts || {}
  return [
    { label: t('ground.monitor.trains', '列车总数'), value: Object.values(counts).reduce((sum, value) => sum + value, 0) },
    { label: t('ground.monitor.both_online', '双端在线'), value: counts.BOTH_ONLINE || 0 },
    { label: t('ground.monitor.one_online', '单端可达'), value: (counts.CT_ONLY || 0) + (counts.CW_ONLY || 0) + (counts.SINGLE_ONLINE || 0) },
    { label: t('ground.monitor.train_offline', '整车离线'), value: (counts.TRAIN_OFFLINE || 0) + (counts.SINGLE_OFFLINE || 0) },
    { label: t('ground.monitor.mr_total', 'MR / AP 总数'), value: heartbeat.value?.total_mrs ?? heartbeat.value?.mrs.length ?? 0 },
  ]
})
</script>
<template>
  <section class="heartbeat-page">
    <header class="heading"><div><h2>{{ t('ground.v2.train_heartbeat', '车辆与双端心跳') }}</h2><span class="muted">{{ heartbeat?.run_id || selectedRunId || '—' }} · {{ heartbeat?.run_state || '—' }}</span></div><el-button :loading="loading" @click="refresh">{{ t('common.refresh', '刷新') }}</el-button></header>
    <el-alert v-if="heartbeatError" :title="heartbeatError" type="error" :closable="false" />
    <div class="metrics"><div v-for="item in metrics" :key="item.label"><span>{{ item.label }}</span><b>{{ item.value }}</b></div></div>
    <div class="filters"><el-input v-model="search" clearable :placeholder="t('ground.monitor.search', '列车、AP 名称、UUID 或管理 IP')" /><el-select v-model="status" clearable :placeholder="t('ground.monitor.train_state', '列车状态')"><el-option v-for="value in ['BOTH_ONLINE','CT_ONLY','CW_ONLY','TRAIN_OFFLINE','BOTH_UNREACHABLE_PENDING','SINGLE_ONLINE','SINGLE_OFFLINE','UNKNOWN']" :key="value" :value="value" :label="stateLabel(value)" /></el-select><el-select v-model="station" clearable :placeholder="t('ground.station', '站点')"><el-option v-for="item in heartbeat?.stations || []" :key="item" :value="item" :label="item" /></el-select><el-checkbox v-model="abnormalOnly">{{ t('ground.monitor.abnormal', '仅异常') }}</el-checkbox></div>
    <div v-if="!heartbeat?.trains.length" class="empty">{{ t('ground.monitor.no_trains', '当前没有符合条件的心跳快照') }}</div>
    <div v-else class="train-list"><article v-for="train in heartbeat.trains" :key="train.train_id" class="train-row">
      <div class="train-ident"><strong>{{ train.train_no || train.train_id }}</strong><el-tag size="small" :type="stateType(train.status)">{{ stateLabel(train.status) }}</el-tag></div>
      <template v-for="role in ['CT', 'CW']" :key="role"><div v-if="mrFor(train.train_id, role)" class="mr-card" tabindex="0" role="button" :aria-label="`${role} ${t('ground.monitor.open', '打开综合监测')}`" @click="openMonitor(mrFor(train.train_id, role)!)" @keydown.enter="openMonitor(mrFor(train.train_id, role)!)" @contextmenu="openMenu($event, mrFor(train.train_id, role)!)">
        <div class="mr-card-heading"><strong>{{ role }}</strong><el-tag size="small" :type="stateType(mrFor(train.train_id, role)!.status)">{{ stateLabel(mrFor(train.train_id, role)!.status) }}</el-tag><span class="rtt">{{ mrFor(train.train_id, role)!.current_rtt_ms == null ? 'RTT —' : `RTT ${mrFor(train.train_id, role)!.current_rtt_ms} ms` }}</span><button class="more" :aria-label="t('ground.monitor.actions', '操作菜单')" @click.stop="openMenu($event, mrFor(train.train_id, role)!)">⋮</button></div>
        <div class="mr-name">{{ mrFor(train.train_id, role)!.resolved_ap_name || t('ground.monitor.unresolved', 'AP 身份未解析') }} <span>{{ mrFor(train.train_id, role)!.station || mrFor(train.train_id, role)!.section || '""' }}</span></div>
        <div class="addresses"><span v-for="(ip, index) in mrFor(train.train_id, role)!.ip_states" :key="ip.ip">{{ index === 0 ? t('ground.monitor.primary', '主') : t('ground.monitor.backup', '备') }} {{ ip.ip }}</span></div>
      </div><div v-else class="mr-card absent"><strong>{{ role }}</strong><span>{{ t('ground.monitor.no_endpoint', '无端点快照') }}</span></div></template>
    </article></div>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[25, 50, 100, 200]" :total="heartbeat?.total ?? heartbeat?.trains.length ?? 0" layout="total, sizes, prev, pager, next" />
    <teleport to="body"><div v-if="menu" class="mr-context-menu" :style="{ left: `${menu.x}px`, top: `${menu.y}px` }" role="menu" @click.stop><button role="menuitem" :disabled="!terminalEnabled" @click="openTerminal(menu.mr)">{{ t('ground.monitor.terminal', '外部终端（主 IP）') }}</button><button role="menuitem" @click="openMonitor(menu.mr)">{{ t('ground.monitor.all', '综合监测') }}</button><button role="menuitem" @click="openMonitor(menu.mr, 'ping')">Ping</button><button role="menuitem" @click="openMonitor(menu.mr, 'loss')">{{ t('ground.monitor.loss', '丢包') }}</button><button role="menuitem" @click="openMonitor(menu.mr, 'peer')">Peer AP</button><button role="menuitem" @click="openMonitor(menu.mr, 'mesh')">Mesh</button><button v-if="quickPingVisible" role="menuitem" :disabled="!quickPingEnabled" @click="emit('quick-ping', menu.mr.mr_uuid); closeMenu()">{{ t('ground.quick_ping', '快速 Ping') }}</button></div></teleport>
    <MrMonitoringDrawer v-if="selectedMr" :mr="selectedMr" :run-id="heartbeat?.run_id || selectedRunId" :active="active" :section="selectedSection" :terminal-enabled="terminalEnabled" :quick-enabled="quickPingVisible && quickPingEnabled" @close="selectedMr = null" @terminal="openTerminal(selectedMr!)" @quick-ping="emit('quick-ping', selectedMr!.mr_uuid)" />
  </section>
</template>
<style scoped>
.heartbeat-page{display:flex;flex-direction:column;gap:14px;min-width:0}.heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.heading h2{font-size:20px;margin:0 0 4px}.muted{color:var(--el-text-color-secondary);font-size:12px}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.metrics>div{display:flex;flex-direction:column;gap:7px;padding:10px 12px;border:1px solid var(--el-border-color-lighter);background:var(--el-fill-color-light)}.metrics span{font-size:12px;color:var(--el-text-color-secondary)}.metrics b{font-size:20px}.filters{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.filters .el-input{width:260px}.filters .el-select{width:150px}.train-list{display:flex;flex-direction:column;gap:6px}.train-row{display:grid;grid-template-columns:minmax(130px,0.6fr) repeat(2,minmax(0,1fr));gap:8px;align-items:stretch;border-bottom:1px solid var(--el-border-color-lighter);padding:4px 0 10px}.train-ident{display:flex;align-items:flex-start;justify-content:center;flex-direction:column;gap:7px;padding:6px}.train-ident strong{font-size:16px;overflow-wrap:anywhere}.mr-card{min-width:0;padding:8px 10px;border:1px solid var(--el-border-color-light);border-radius:4px;cursor:pointer;background:var(--el-bg-color)}.mr-card:hover,.mr-card:focus-visible{border-color:var(--el-color-primary)}.mr-card-heading{display:flex;align-items:center;gap:8px}.mr-card-heading strong{font-size:14px}.rtt{margin-left:auto;color:var(--el-text-color-secondary);font-size:12px}.more{border:0;background:transparent;color:var(--el-text-color-secondary);font-size:20px;cursor:pointer;padding:0 4px}.mr-name{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;overflow-wrap:anywhere}.mr-name span,.addresses,.absent span{color:var(--el-text-color-secondary);font-size:12px}.addresses{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px}.absent{display:flex;align-items:center;gap:10px;cursor:default;background:var(--el-fill-color-light)}.empty{padding:32px;text-align:center;color:var(--el-text-color-secondary)}@media(max-width:800px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.train-row{grid-template-columns:1fr 1fr}.train-ident{grid-column:1/-1;flex-direction:row;justify-content:flex-start}.filters .el-input{width:100%}}@media(max-width:480px){.train-row{grid-template-columns:1fr}.train-ident{grid-column:auto}}
</style>
<style>.mr-context-menu{position:fixed;z-index:4000;display:flex;flex-direction:column;min-width:190px;padding:4px;background:var(--el-bg-color-overlay);border:1px solid var(--el-border-color-light);box-shadow:var(--el-box-shadow-light)}.mr-context-menu button{border:0;background:transparent;color:var(--el-text-color-primary);text-align:left;padding:8px 12px;cursor:pointer}.mr-context-menu button:hover{background:var(--el-fill-color-light)}.mr-context-menu button:disabled{color:var(--el-disabled-text-color);cursor:not-allowed}</style>
