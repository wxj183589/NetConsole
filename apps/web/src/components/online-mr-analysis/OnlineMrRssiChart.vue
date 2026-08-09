<script setup lang="ts">
import { computed, ref } from 'vue'

import MeshRssiChart from '../mesh-analysis/MeshRssiChart.vue'
import MeshTracksideSignalChart from '../mesh-analysis/MeshTracksideSignalChart.vue'
import RailRssiComparison from '../rail-timeline/RailRssiComparison.vue'
import type {
  MeshChartEvent,
  MeshChartPoint,
  MeshLocationSegment,
  MeshTracksideSignalSeriesData,
} from '../../types/meshAnalysis'
import type {
  OnlineMrMainLinkRow,
  OnlineMrMetricSeries,
  OnlineMrSwitchRssiWindow,
} from '../../types/onlineMr'
import type {
  MeshChartHandle,
  MeshChartViewport,
  MeshRssiChartSource,
  MeshSharedPointerChange,
} from '../mesh-analysis/meshChartViewport'
import type { MeshRssiLayoutMode } from '../mesh-analysis/meshRssiLayout'

const props = withDefaults(defineProps<{
  rows?: OnlineMrMainLinkRow[]
  mainSeries?: OnlineMrMetricSeries[]
  tracksideSeries?: OnlineMrMetricSeries[]
  historyEvents?: OnlineMrSwitchRssiWindow[]
  realtimeEvents?: OnlineMrSwitchRssiWindow[]
  active?: boolean
  viewport?: MeshChartViewport | null
  cursorTime?: string | null
  cursorSource?: MeshRssiChartSource | null
  selectedTime?: string | null
  layoutMode?: MeshRssiLayoutMode
  splitRatio?: number
  workspaceHeight?: number
  radio?: number | null
  showPeer?: boolean
  showSwitchLines?: boolean
  showSwitchPoints?: boolean
  showLocationBand?: boolean
}>(), {
  rows: () => [],
  mainSeries: () => [],
  tracksideSeries: () => [],
  historyEvents: () => [],
  realtimeEvents: () => [],
  active: true,
  viewport: null,
  cursorTime: null,
  cursorSource: null,
  selectedTime: null,
  layoutMode: 'compare',
  splitRatio: 0.5,
  workspaceHeight: 760,
  radio: null,
  showPeer: false,
  showSwitchLines: true,
  showSwitchPoints: true,
  showLocationBand: true,
})
const emit = defineEmits<{
  'update:viewport': [viewport: MeshChartViewport]
  'update:splitRatio': [ratio: number]
  'pointer-change': [pointer: MeshSharedPointerChange]
  'select-time': [time: string]
  'select-switch': [event: MeshChartEvent]
}>()

const mainChart = ref<MeshChartHandle | null>(null)
const tracksideChart = ref<MeshChartHandle | null>(null)

function text(value: unknown): string | null {
  const normalized = String(value ?? '').trim()
  return normalized || null
}

function number(value: unknown): number | null {
  const parsed = Number(value)
  return value === null || value === undefined || value === '' || !Number.isFinite(parsed) ? null : parsed
}

function identityStatus(value: unknown): MeshChartPoint['identity_status'] {
  const normalized = text(value)
  return normalized === 'matched' || normalized === 'unresolved' || normalized === 'ambiguous'
    ? normalized
    : undefined
}

function pointFromMetric(series: OnlineMrMetricSeries, point: OnlineMrMetricSeries['points'][number]): MeshChartPoint | null {
  if (!point.timestamp) return null
  const dimensions = point.dimensions || {}
  const radio = number(dimensions.radio)
  if (props.radio != null && radio != null && radio !== props.radio) return null
  return {
    link_id: null,
    timestamp: point.timestamp,
    timestamp_tag: null,
    source_file_id: null,
    local_radio: radio,
    link_state: text(dimensions.link_state) || 'ACTIVE',
    peer_mac: text(dimensions.peer_mac),
    peer_ap_name: text(dimensions.peer_name) || text(series.series_key),
    peer_ap_mac: text(dimensions.ap_mac),
    peer_radio: null,
    peer_radio_mac: text(dimensions.peer_radio_mac),
    station: text(dimensions.station),
    section: text(dimensions.section),
    establish_time: null,
    segment_start: null,
    segment_end: null,
    segment_duration_seconds: null,
    local_rssi: number(point.value),
    peer_rssi: null,
    local_signal: null,
    peer_signal: null,
    local_tx_busy: null,
    peer_tx_busy: null,
    local_rx_busy: null,
    peer_rx_busy: null,
    is_switch: false,
    is_anomaly: false,
    gap_before: false,
    backups: [],
    identity_status: identityStatus(dimensions.identity_status),
    identity_source: text(dimensions.identity_source),
  }
}

const rowPoints = computed<MeshChartPoint[]>(() => props.rows
  .filter((row) => Boolean(row.device_time) && (props.radio == null || row.radio == null || row.radio === props.radio))
  .map((row) => ({
    link_id: null,
    timestamp: row.device_time || '',
    timestamp_tag: null,
    source_file_id: null,
    local_radio: number(row.radio),
    link_state: text(row.link_state) || 'ACTIVE',
    peer_mac: text(row.peer_mac),
    peer_ap_name: text(row.peer_name),
    peer_ap_mac: text(row.canonical_ap_mac),
    peer_radio: null,
    peer_radio_mac: text(row.bssid),
    station: text(row.belong_station),
    section: text(row.belong_section),
    local_rssi: number(row.mr_rssi),
    peer_rssi: null,
    local_signal: null,
    peer_signal: null,
    local_tx_busy: null,
    peer_tx_busy: null,
    local_rx_busy: null,
    peer_rx_busy: null,
    is_switch: false,
    is_anomaly: false,
    gap_before: false,
    backups: [],
    identity_status: identityStatus(row.identity_status),
    identity_source: text(row.identity_source),
  })))

const points = computed<MeshChartPoint[]>(() => {
  const metricPoints = props.mainSeries.flatMap((series) => series.points.flatMap((point) => {
    const value = pointFromMetric(series, point)
    return value ? [value] : []
  }))
  return (metricPoints.length ? metricPoints : rowPoints.value)
    .sort((left, right) => left.timestamp.localeCompare(right.timestamp))
})

const trackside = computed<MeshTracksideSignalSeriesData[]>(() => props.tracksideSeries.flatMap((series, seriesIndex) => {
  const pointsForSeries = series.points.flatMap((point, pointIndex) => {
    if (!point.timestamp) return []
    const dimensions = point.dimensions || {}
    const radio = number(dimensions.radio)
    if (props.radio != null && radio != null && radio !== props.radio) return []
    const role = text(dimensions.link_state)?.toUpperCase().startsWith('STANDBY') ? 'STANDBY' as const : 'ACTIVE' as const
    return [{
      timestamp: point.timestamp,
      timestamp_tag: '',
      source_file_id: null,
      link_id: null,
      sample_id: seriesIndex * 100_000 + pointIndex,
      local_radio: radio,
      role,
      peer_mac: text(dimensions.peer_mac),
      peer_ap_name: text(dimensions.peer_name) || text(series.series_key),
      peer_ap_mac: text(dimensions.ap_mac),
      peer_radio: null,
      peer_radio_mac: text(dimensions.peer_radio_mac),
      station: text(dimensions.station),
      section: text(dimensions.section),
      peer_rssi: number(point.value),
      local_rssi: null,
      peer_signal: null,
      local_signal: null,
      segment_duration_seconds: null,
      break_before: false,
      data_source: 'online-mr',
      identity_status: identityStatus(dimensions.identity_status),
      identity_source: text(dimensions.identity_source),
    }]
  })
  if (!pointsForSeries.length) return []
  const first = pointsForSeries[0]
  return [{
    series_id: `online-${seriesIndex}-${series.series_key}`,
    peer_name: first.peer_ap_name,
    peer_mac: first.peer_mac,
    ap_mac: first.peer_ap_mac,
    radio: first.local_radio,
    peer_radio_mac: first.peer_radio_mac,
    station: first.station,
    section: first.section,
    roles_present: [...new Set(pointsForSeries.map((point) => point.role))],
    data_source: 'online-mr',
    total_points: pointsForSeries.length,
    returned_points: pointsForSeries.length,
    points: pointsForSeries,
  }]
}))

function nearestPoint(event: OnlineMrSwitchRssiWindow): MeshChartPoint | undefined {
  const target = event.event_time ? Date.parse(event.event_time.replace(' ', 'T')) : Number.NaN
  if (!Number.isFinite(target)) return undefined
  let nearest: MeshChartPoint | undefined
  let distance = Number.POSITIVE_INFINITY
  for (const point of points.value) {
    if (event.radio != null && point.local_radio != null && event.radio !== point.local_radio) continue
    const candidate = Date.parse(point.timestamp.replace(' ', 'T'))
    const delta = Math.abs(candidate - target)
    if (Number.isFinite(delta) && delta < distance) {
      nearest = point
      distance = delta
    }
  }
  return distance <= 10_000 ? nearest : undefined
}

const events = computed<MeshChartEvent[]>(() => {
  const source = props.realtimeEvents.length ? props.realtimeEvents : props.historyEvents
  return source.flatMap((event) => {
    if (!event.event_time) return []
    const point = nearestPoint(event)
    return [{
      event_id: null,
      timestamp: event.event_time,
      event_type: 'ACTIVE_SWITCH',
      local_radio: event.radio,
      from_peer_mac: event.old_peer_mac || null,
      to_peer_mac: event.new_peer_mac || null,
      from_ap_name: event.old_peer_name || null,
      to_ap_name: event.new_peer_name || null,
      before_rssi: event.old_rssi_dbm,
      after_rssi: event.new_rssi_dbm,
      duration_ms: null,
      reason: event.reason || null,
      from_station: event.old_station || null,
      from_section: event.old_section || null,
      to_station: event.new_station || null,
      to_section: event.new_section || null,
      station: event.new_station || event.old_station || null,
      section: event.new_section || event.old_section || null,
      point_timestamp: point?.timestamp || null,
      point_rssi: point?.local_rssi ?? null,
      point_context: point || null,
      render_point_timestamp: point?.timestamp || event.event_time,
      render_point_rssi: point?.local_rssi ?? null,
      render_aligned: Boolean(point),
    }]
  })
})

const locationSegments = computed<MeshLocationSegment[]>(() => {
  const segments: MeshLocationSegment[] = []
  for (const point of points.value) {
    if (!point.station && !point.section) continue
    const previous = segments.at(-1)
    if (previous && previous.station === point.station && previous.section === point.section) {
      previous.end_time = point.timestamp
    } else {
      segments.push({
        start_time: point.timestamp,
        end_time: point.timestamp,
        station: point.station,
        section: point.section || null,
        label: [point.station, point.section].filter(Boolean).join(' / ') || null,
      })
    }
  }
  return segments
})

const sharedTimeDomain = computed(() => {
  const timestamps = [
    ...points.value.map((point) => point.timestamp),
    ...trackside.value.flatMap((series) => series.points.map((point) => point.timestamp)),
  ].sort()
  return timestamps.length > 1
    ? { full_start_time: timestamps[0], full_end_time: timestamps.at(-1)! }
    : null
})

function resize(): void {
  mainChart.value?.resize?.()
  tracksideChart.value?.resize?.()
}
</script>

<template>
  <RailRssiComparison
    :mode="layoutMode"
    :split-ratio="splitRatio"
    :workspace-height="workspaceHeight"
    :minimum-pane-height="210"
    @update:split-ratio="emit('update:splitRatio', $event)"
    @resize="resize"
  >
    <template #active>
      <div class="online-rssi-pane">
        <header><h3>主用链路信号</h3><span>ACTIVE {{ points.length }} 点</span></header>
        <div class="online-rssi-chart-host">
          <MeshRssiChart
            ref="mainChart"
            :points="points"
            :events="events"
            :location-segments="locationSegments"
            :show-peer="showPeer"
            :show-switch-lines="showSwitchLines"
            :show-switch-points="showSwitchPoints"
            :show-location-band="showLocationBand"
            :active="active && layoutMode !== 'trackside-focus'"
            :initial-viewport="viewport"
            :sync-viewport="viewport"
            :shared-time-domain="sharedTimeDomain"
            :sync-pointer-time="cursorTime || selectedTime"
            :sync-pointer-source="cursorTime ? cursorSource : 'programmatic'"
            :selected-time="selectedTime"
            quick-tooltip
            preserve-viewport
            @viewport-change="emit('update:viewport', $event)"
            @pointer-change="emit('pointer-change', $event)"
            @select-time="emit('select-time', $event)"
            @select-switch="emit('select-switch', $event)"
          />
        </div>
      </div>
    </template>
    <template #trackside>
      <div class="online-rssi-pane">
        <header><h3>轨旁 AP 信号图</h3><span>{{ trackside.length }} 条 AP/Radio 序列</span></header>
        <div class="online-rssi-chart-host">
          <MeshTracksideSignalChart
            ref="tracksideChart"
            :series="trackside"
            :events="events"
            :location-segments="locationSegments"
            :show-switch-lines="showSwitchLines"
            :show-switch-points="showSwitchPoints"
            :show-location-band="showLocationBand"
            :active="active && layoutMode !== 'active-focus'"
            :workspace-visible="active"
            :initial-viewport="viewport"
            :sync-viewport="viewport"
            :shared-time-domain="sharedTimeDomain"
            :sync-pointer-time="cursorTime || selectedTime"
            :sync-pointer-source="cursorTime ? cursorSource : 'programmatic'"
            :selected-time="selectedTime"
            quick-tooltip
            preserve-viewport
            @viewport-change="emit('update:viewport', $event)"
            @pointer-change="emit('pointer-change', $event)"
            @select-time="emit('select-time', $event)"
            @select-switch="emit('select-switch', $event)"
          />
        </div>
      </div>
    </template>
  </RailRssiComparison>
</template>

<style scoped>
.online-rssi-pane{display:flex;min-width:0;min-height:0;height:100%;flex-direction:column}
.online-rssi-pane header{display:flex;align-items:center;justify-content:space-between;min-height:34px;padding:0 8px;border-bottom:1px solid var(--el-border-color-lighter)}
.online-rssi-pane h3{margin:0;font-size:14px;line-height:1.2}
.online-rssi-pane header span{color:var(--el-text-color-secondary);font-size:12px}
.online-rssi-chart-host{min-width:0;min-height:0;flex:1}
</style>
