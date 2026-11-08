<script setup lang="ts">
import { t } from '../../i18n/runtime'
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { getGroundHeartbeat, listGroundTimeline } from '../../api/groundUnattended'
import type { GroundHeartbeatPage, GroundTimelineEvent } from '../../types/groundUnattended'
import { useGroundContext } from './useGroundUnattended'
const { CopyDocument, Refresh, groundRunModeLabel, groundStatusLabel, activeTab, status, profile, health, syslogTransport, syslogTransportLoading, loadSyslogTransport, saveProfile, refreshSyslogAddresses, copyReturnTarget, bytes, statusType } = useGroundContext()
const { pageVisible, pageActivated, quickContextRevision } = useGroundContext()
const mounted = ref(false)
const active = computed(() => mounted.value && pageVisible.value && pageActivated.value && activeTab.value === 'overview')
const heartbeat = ref<GroundHeartbeatPage | null>(null)
const recentExceptions = ref<GroundTimelineEvent[]>([])
const loadError = ref('')
const runId = computed(() => status.value?.active_run_id || status.value?.latest_run_id || '')
const trainOnline = computed(() => (heartbeat.value?.train_counts.BOTH_ONLINE || 0) + (heartbeat.value?.train_counts.SINGLE_ONLINE || 0))
const trainPartial = computed(() => (heartbeat.value?.train_counts.CT_ONLY || 0) + (heartbeat.value?.train_counts.CW_ONLY || 0))
const trainOffline = computed(() => (heartbeat.value?.train_counts.TRAIN_OFFLINE || 0) + (heartbeat.value?.train_counts.SINGLE_OFFLINE || 0))
let generation = 0
let controller: AbortController | null = null
let timer: ReturnType<typeof setInterval> | undefined
async function loadV2(): Promise<void> {
  if (!active.value || controller) return
  const current = generation
  const request = new AbortController()
  controller = request
  try {
    const [snapshot, events] = await Promise.all([
      getGroundHeartbeat(runId.value, { signal: request.signal }),
      listGroundTimeline('', '', runId.value, { signal: request.signal }, 1, 50),
    ])
    if (current !== generation || !active.value) return
    heartbeat.value = snapshot
    recentExceptions.value = events.items.filter((row) => ['warning', 'error', 'critical'].includes(row.severity.toLowerCase()) || /offline|failed|degraded/i.test(row.event_type)).slice(0, 8)
    loadError.value = ''
  } catch (error) {
    if (current === generation && !request.signal.aborted) loadError.value = error instanceof Error ? error.message : t('ground.v2.overview_load_failed', '概览心跳数据读取失败')
  } finally { if (current === generation) controller = null }
}
function stopPolling(): void {
  generation += 1; controller?.abort(); controller = null
  if (timer) clearInterval(timer)
  timer = undefined
}
watch([active, runId, quickContextRevision], () => {
  stopPolling(); heartbeat.value = null; recentExceptions.value = []; loadError.value = ''
  if (active.value) { void loadV2(); timer = setInterval(() => { void loadV2() }, 5000) }
})
onMounted(() => { mounted.value = true })
onBeforeUnmount(stopPolling)
</script>

<template>
<section class="ground-subpage">
        <el-alert v-if="loadError" :title="loadError" :description="t('ground.v2.overview_stale', '最后快照可能已过期；服务读取失败不代表 MR 离线。')" type="error" :closable="false" />
        <section class="overview-band">
          <h2>{{ t('ground.v2.all_mr', '全量 MR 心跳') }}</h2>
          <p class="muted">{{ heartbeat?.run_id || t('ground.v2.dynamic_65', '暂无运行') }} {{ t('ground.v2.offline_rule_short', '· MR 全部 IP 持续失败 10 秒才确认离线；整车离线需双端同时不可达满 2 分钟。') }}</p>
          <div class="metric-grid" data-testid="v2-heartbeat-metrics">
            <article><span>{{ t('ground.v2.online_offline_mr', '在线 / 离线 MR') }}</span><strong>{{ heartbeat?.mr_counts.ONLINE ?? '—' }} / {{ heartbeat?.mr_counts.OFFLINE ?? '—' }}</strong><small>{{ t('ground.v2.recovering', '恢复中') }} {{ heartbeat?.mr_counts.RECOVERING || 0 }} · {{ t('ground.v2.overview_pending', '待确认') }} {{ heartbeat?.mr_counts.OFFLINE_PENDING || 0 }} · {{ t('ground.v2.overview_unknown', '未知') }} {{ heartbeat?.mr_counts.UNKNOWN || 0 }}</small></article>
            <article><span>{{ t('ground.v2.online_partial_offline_train', '在线 / 部分可达 / 离线列车') }}</span><strong>{{ heartbeat ? trainOnline : '—' }} / {{ heartbeat ? trainPartial : '—' }} / {{ heartbeat ? trainOffline : '—' }}</strong><small>{{ t('ground.v2.single_train_note', '单端列车单独判断，待确认与未知不计入离线') }}</small></article>
            <article><span>{{ t('ground.v2.fleet_totals', '心跳 MR / 列车总数') }}</span><strong>{{ heartbeat?.mrs.length ?? '—' }} / {{ heartbeat?.trains.length ?? '—' }}</strong><el-button text type="primary" @click="activeTab = 'heartbeat'">{{ t('ground.v2.view_heartbeat', '查看心跳明细') }}</el-button></article>
          </div>
          <div class="transport-heading"><h3>{{ t('ground.v2.recent_errors', '近期异常（最近 50 条事件）') }}</h3><el-button text @click="activeTab = 'timeline'">{{ t('ground.v2.view_timeline', '查看事件时间轴') }}</el-button></div>
          <el-empty v-if="!recentExceptions.length" :description="t('ground.v2.no_recent_errors', '近期事件中暂无异常')" :image-size="45" />
          <div v-for="event in recentExceptions" :key="event.event_id" class="status-line"><el-tag size="small" type="warning">{{ event.ts }}</el-tag><span>{{ event.mr_name || event.train_no }} {{ event.title || event.event_type }}</span><span class="muted">{{ event.message }}</span></div>
        </section>
        <section class="overview-band">
          <div class="status-line">
            <span>{{ t('ground.current_site', '当前局点') }} <b>{{ status?.site_id || '—' }}</b></span>
            <el-tag :type="status ? statusType(status.state) : 'danger'">{{ status ? groundStatusLabel(status.state) : t('ground.v2.overview_state_not_loaded', '状态未加载') }}</el-tag>
            <el-switch v-if="profile" v-model="profile.enabled" :active-text="t('ground.enabled', '启用无人值守')" @change="saveProfile()" />
            <span class="muted">{{ t('ground.pause_note', '暂停调度时 AC 轮询与心跳检测继续') }}</span>
          </div>
          <div class="metric-grid">
            <article><span>{{ t('ground.v2.run_mode', '当前运行模式') }}</span><strong>{{ status ? groundRunModeLabel(status.running_mode) : '—' }}</strong><small>{{ !status ? t('ground.v2.overview_waiting_state', '等待运行状态加载') : status.running_mode === 'LIGHTWEIGHT' ? t('ground.v2.overview_lightweight', '不启动 SSH 深度 MR 采集') : t('ground.v2.overview_standard', '包含深度 MR 采集') }}</small></article>
            <article><span>{{ t('ground.v2.active_run', '当前活动运行') }}</span><strong>{{ status?.active_run_date || t('ground.v2.overview_none', '无') }}</strong><small>{{ status?.active_run_id || t('ground.v2.overview_no_active_run', '当前没有正在执行的运行') }}</small></article>
            <article><span>{{ t('ground.v2.latest_run', '最近历史运行') }}</span><strong>{{ status?.latest_run_date || '—' }}</strong><small>{{ status?.latest_run_state ? groundStatusLabel(status.latest_run_state) : t('ground.v2.overview_no_history', '暂无历史运行') }}</small></article>
            <article><span>{{ t('ground.window', '配置运行时间') }}</span><strong>{{ status?.schedule_start_time }} - {{ status?.schedule_end_time }}</strong></article>
            <article><span>{{ t('ground.next_start', '下一次启动') }}</span><strong>{{ status?.next_start_at || '—' }}</strong></article>
            <article><span>{{ t('ground.next_end', '下一次结束') }}</span><strong>{{ status?.next_end_at || '—' }}</strong></article>
            <article><span>{{ t('ground.ac_updated', 'AC 最近更新') }}</span><strong>{{ status?.ac_last_updated_at || '—' }}</strong></article>
            <article><span>{{ t('ground.mainline_trains', '正线列车') }}</span><strong>{{ status?.mainline_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.mainline_ping_mr', '正线心跳 MR') }}</span><strong>{{ status?.mainline_ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.depot_ping_mr', '车辆段心跳 MR') }}</span><strong>{{ status?.depot_ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.ping_mrs', '心跳总目标') }}</span><strong>{{ status?.ping_target_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.active_deep', '当前深度采集车辆') }}</span><strong>{{ status?.active_deep_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.covered_today', '今日已完成 / 未完成') }}</span><strong>{{ status?.covered_train_count ?? 0 }} / {{ status?.incomplete_train_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.disk_usage', '当前占用 / 磁盘剩余') }}</span><strong>{{ bytes(status?.disk_used_bytes ?? 0) }} / {{ bytes(status?.disk_free_bytes ?? 0) }}</strong><el-tag size="small" :type="statusType(status?.disk_status || '')">{{ groundStatusLabel(status?.disk_status) }}</el-tag></article>
            <article><span>{{ t('ground.latest_archive', '最近归档') }}</span><strong>{{ status?.latest_archive_status ? groundStatusLabel(status.latest_archive_status) : '—' }}</strong><small>{{ status?.latest_archive_message }}</small></article>
            <article><span>{{ t('ground.v2.syslog_active_errors', 'Syslog 活跃 / 配置异常') }}</span><strong>{{ status?.syslog_active_mr_count ?? 0 }} / {{ status?.config_abnormal_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.radio_down_mr', '射频口关闭 MR') }}</span><strong>{{ status?.radio_down_mr_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.radio_interruptions_today', '今日射频短暂中断') }}</span><strong>{{ status?.radio_bounce_today_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.snmp_controls_today', '今日 SNMP 射频控制') }}</span><strong>{{ status?.snmp_radio_control_today_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.snmp_unrecovered', 'SNMP 控制后未恢复') }}</span><strong>{{ status?.snmp_unrecovered_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.radio_flapping_mr', '射频频繁切换 MR') }}</span><strong>{{ status?.radio_flapping_mr_count ?? 0 }}</strong></article>
            <article><span>{{ t('ground.v2.last_snmp_radio', '最近 SNMP 射频操作') }}</span><strong>{{ status?.last_snmp_radio_control_at || '—' }}</strong></article>
            <article><span>{{ t('ground.v2.udp_queue_drops', 'UDP 队列 / 丢弃') }}</span><strong>{{ health?.udp_queue_length ?? 0 }} / {{ health?.udp_dropped_count ?? 0 }}</strong><small>{{ health?.udp_listen_address || t('ground.v2.overview_not_listening', '未监听') }}</small></article>
          </div>
          <section class="syslog-transport-band" v-loading="syslogTransportLoading">
            <div class="transport-heading">
              <div>
                <h2>{{ t('ground.v2.syslog_transport', 'UDP Syslog 与 MR 日志回传') }}</h2>
                <p>{{ t('ground.v2.transport_note', 'MR 目标地址与 NetConsole 本机监听是两条独立配置。') }}</p>
              </div>
              <div class="row-actions">
                <el-button :icon="Refresh" @click="refreshSyslogAddresses">{{ t('ground.v2.refresh_addresses', '刷新地址') }}</el-button>
                <el-button @click="loadSyslogTransport(false)">{{ t('ground.v2.check_port', '检查端口') }}</el-button>
                <el-button @click="activeTab = 'settings'">{{ t('ground.v2.go_settings', '前往设置') }}</el-button>
                <el-button :icon="CopyDocument" :disabled="!syslogTransport?.configured_return_ip" @click="copyReturnTarget">{{ t('ground.v2.copy_return_target', '复制回传目标') }}</el-button>
              </div>
            </div>
            <el-alert
              v-if="syslogTransport && ['NOT_LOCAL', 'INVALID', 'EMPTY'].includes(syslogTransport.return_address_status)"
              :title="syslogTransport.return_address_status === 'NOT_LOCAL' ? t('ground.v2.overview_return_not_local', 'MR 日志回传地址 {address} 当前不属于本机').replace('{address}', `${syslogTransport.configured_return_ip}:${syslogTransport.configured_return_port}`) : groundStatusLabel(syslogTransport.return_address_status)"
              :description="syslogTransport.return_address_status === 'NOT_LOCAL' ? t('ground.v2.overview_return_config_help', '不会自动采用推荐地址；请前往设置选择本机地址，或明确确认外部/NAT 地址。') : t('ground.v2.overview_configure_help', '请前往设置完成有效配置。')"
              type="error"
              :closable="false"
              show-icon
            />
            <el-alert
              v-else-if="syslogTransport?.return_address_status === 'EXTERNAL_CONFIRMED'"
              :title="t('ground.v2.external_confirmed', '当前使用已确认的外部/NAT 日志回传地址')"
              :description="t('ground.v2.external_note', '启动允许继续，但本机监听端口状态不代表外部映射可达。')"
              type="warning"
              :closable="false"
              show-icon
            />
            <div class="transport-grid">
              <article>
                <span>{{ t('ground.v2.return_address', 'MR 日志回传地址') }}</span>
                <strong>{{ syslogTransport?.configured_return_ip ? `${syslogTransport.configured_return_ip}:${syslogTransport.configured_return_port}` : t('ground.v2.overview_not_configured', '尚未配置') }}</strong>
                <el-tag size="small" :type="statusType(syslogTransport?.return_address_status || '')">{{ groundStatusLabel(syslogTransport?.return_address_status) }}</el-tag>
              </article>
              <article>
                <span>{{ t('ground.v2.recommended_address', '系统推荐地址') }}</span>
                <strong>{{ syslogTransport?.recommended_local_ip || t('ground.v2.overview_no_recommendation', '无可靠推荐') }}</strong>
                <small>{{ syslogTransport?.recommended_adapter_name || t('ground.v2.overview_no_adapter', '未匹配网卡') }} · {{ t('ground.v2.overview_display_only', '仅展示，不自动覆盖') }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.listener_address', '本机监听地址') }}</span>
                <strong>{{ syslogTransport ? `${syslogTransport.listen_host}:${syslogTransport.listen_port}` : '—' }}</strong>
                <small>{{ syslogTransport?.listen_host === '0.0.0.0' ? t('ground.v2.overview_all_adapters', '监听全部本机网卡') : syslogTransport?.actual_listen_address || t('ground.v2.overview_selected_adapter', '指定网卡地址') }}</small>
              </article>
              <article>
                <span>UDP Receiver</span>
                <strong>{{ groundStatusLabel(syslogTransport?.receiver_state) }}</strong>
                <small>{{ syslogTransport?.actual_listen_address || t('ground.v2.overview_currently_not_listening', '当前未监听') }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.listener_port', '本机监听端口') }}</span>
                <strong>{{ groundStatusLabel(syslogTransport?.port_state) }}</strong>
                <small>{{ syslogTransport?.port_message || t('ground.v2.overview_not_checked', '尚未检测') }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.destination_listen_ports', 'MR 目标端口 / 本地端口') }}</span>
                <strong>{{ syslogTransport ? `${syslogTransport.configured_return_port} / ${syslogTransport.listen_port}` : '—' }}</strong>
                <small>{{ syslogTransport?.target_port_message || t('ground.v2.overview_not_checked', '尚未检测') }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.last_received_count', '最近接收 / 已接收') }}</span>
                <strong>{{ syslogTransport?.last_received_at || t('ground.v2.overview_no_records', '尚无记录') }}</strong>
                <small>{{ syslogTransport?.received_count ?? 0 }} {{ t('ground.v2.overview_records', '条') }} · {{ t('ground.v2.overview_active_mrs', '活跃 MR') }} {{ syslogTransport?.active_mr_count ?? 0 }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.identity_quality', '身份质量') }}</span>
                <strong>{{ syslogTransport?.unidentified_count ?? 0 }} / {{ syslogTransport?.identity_conflict_count ?? 0 }}</strong>
                <small>{{ t('ground.v2.identity_unknown_conflict', '未识别来源 / 身份冲突') }}</small>
              </article>
              <article>
                <span>{{ t('ground.v2.udp_queue_drops', 'UDP 队列 / 丢弃') }}</span>
                <strong>{{ syslogTransport?.queue_length ?? 0 }} / {{ syslogTransport?.queue_capacity ?? 0 }}</strong>
                <small>{{ t('ground.v2.dropped', '已丢弃') }} {{ syslogTransport?.dropped_count ?? 0 }} {{ t('ground.v2.overview_records', '条') }}</small>
              </article>
            </div>
          </section>
        </section>

</section>
</template>

<style scoped src="./groundUnattended.css"></style>
