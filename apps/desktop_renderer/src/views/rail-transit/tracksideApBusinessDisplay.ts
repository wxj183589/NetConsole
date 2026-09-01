import {
  dualOpticalStatusPresentation,
  isApOpticalApplicable,
  normalizedOpticalStatus,
  opticalRxStatusPresentation,
  opticalStatusPresentation,
} from '../../utils/opticalPresentation'
import { t } from '../../i18n/runtime'

export type TracksideOpticalTagType = 'success' | 'warning' | 'danger' | 'info'

export interface TracksideOpticalPresentation {
  label: string
  tagType: TracksideOpticalTagType
  className: string
}

export type TracksideApRecognitionTagType = 'success' | 'warning' | 'info'

export interface TracksideApRecognitionPresentation {
  label: string
  tagType: TracksideApRecognitionTagType
  className: string
}

const tracksideApReasonLabels: Record<string, string> = {
  EMPTY_CONFIGURED_PORT: '空闲/未接 AP',
  AP_OFFLINE_NO_IDENTITY: 'AP 离线，Identity 不足',
  FIT_AP_NOT_MATCHED: '未匹配 FIT-AP',
  LLDP_MISSING: '缺少 LLDP',
  LLDP_STALE: 'LLDP 数据过旧',
  PLANNING_NOT_MATCHED: '未匹配 AP 规划',
  IDENTITY_INSUFFICIENT: 'Identity 证据不足',
  OTHER: '其他',
}

export function displayTracksideApRecognitionStatus(value: unknown): string {
  return String(value || '').trim().toLowerCase() === 'identified' ? '已识别' : '未识别'
}

export function displayTracksideApReason(value: unknown): string {
  const code = String(value || '').trim()
  return tracksideApReasonLabels[code] || code || '—'
}

export function tracksideApRecognitionPresentation(value: unknown): TracksideApRecognitionPresentation {
  const identified = String(value || '').trim().toLowerCase() === 'identified'
  return {
    label: identified ? '已识别' : '未识别',
    tagType: identified ? 'success' : 'info',
    className: identified ? 'recognition-identified' : 'recognition-unidentified',
  }
}

const classByStatus: Record<string, string> = {
  normal: 'optical-normal',
  notice: 'optical-notice',
  warning: 'optical-warning',
  alarm: 'optical-alarm',
  critical: 'optical-alarm',
  link_abnormal: 'optical-link-abnormal',
  link_down: 'optical-link-down',
  no_light: 'optical-no-light',
  no_module: 'optical-no-module',
  abnormal: 'optical-alarm',
  unverified: 'optical-warning',
  dom_unavailable: 'optical-not-collected',
  skipped: 'optical-skipped',
  not_collected: 'optical-not-collected',
  not_applicable: 'optical-not-collected',
  unknown: 'optical-unknown',
  offline: 'optical-offline',
  collection_failed: 'optical-warning',
}

const missingPresentation: TracksideOpticalPresentation = {
  label: '—',
  tagType: 'info',
  className: 'optical-missing',
}

export function tracksideOpticalPresentation(value: unknown): TracksideOpticalPresentation {
  const status = normalizedOpticalStatus(value)
  if (!status) return missingPresentation
  const presentation = opticalStatusPresentation(value)
  return {
    label: presentation.label,
    tagType: presentation.tagType,
    className: classByStatus[status] || 'optical-unknown',
  }
}

export function tracksideRxPresentation(
  rxPower: unknown,
  backendStatus: unknown,
  freshness: unknown = 'fresh',
  model?: unknown,
  opticalApplicable?: boolean,
): TracksideOpticalPresentation {
  if (!isApOpticalApplicable(model, opticalApplicable)) {
    return tracksideOpticalPresentation('not_applicable')
  }
  return toTracksidePresentation(opticalRxStatusPresentation({
    rxPower,
    backendStatus,
    freshness,
  }))
}

export function tracksideDeviceOpticalPresentation(
  backendStatus: unknown,
  model?: unknown,
  opticalApplicable?: boolean,
): TracksideOpticalPresentation {
  if (!isApOpticalApplicable(model, opticalApplicable)) {
    return tracksideOpticalPresentation('not_applicable')
  }
  return tracksideOpticalPresentation(backendStatus)
}

export function tracksideBusinessOpticalPresentation(row: {
  ap_rx_power?: unknown
  switch_rx_power?: unknown
  ap_device_optical_status?: unknown
  ap_optical_status?: unknown
  switch_device_optical_status?: unknown
  switch_optical_status?: unknown
  optical_severity?: unknown
  model?: unknown
  ap_optical_applicable?: boolean
  ap_optical_data_freshness?: unknown
  switch_optical_data_status?: unknown
}): TracksideOpticalPresentation {
  const freshness = normalizedOpticalStatus(row.ap_optical_data_freshness) === 'stale'
    || normalizedOpticalStatus(row.switch_optical_data_status) === 'stale'
    ? 'stale'
    : 'fresh'
  const presentation = dualOpticalStatusPresentation({
    apBackendStatus: row.ap_device_optical_status || row.ap_optical_status,
    apRxPower: row.ap_rx_power,
    switchBackendStatus: row.switch_device_optical_status || row.switch_optical_status,
    switchRxPower: row.switch_rx_power,
    model: row.model,
    opticalApplicable: row.ap_optical_applicable,
    freshness,
  }).overall
  return toTracksidePresentation(presentation)
}

function toTracksidePresentation(
  presentation: ReturnType<typeof opticalStatusPresentation>,
): TracksideOpticalPresentation {
  return {
    label: presentation.label,
    tagType: presentation.tagType,
    className: classByStatus[presentation.status] || 'optical-unknown',
  }
}

export function displayTracksideValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

const opticalEventStatusLabels: Record<string, string> = {
  OPEN: '未恢复',
  RESOLVED: '已恢复',
}

export function formatOpticalEventStatus(status: unknown): string {
  const normalized = String(status || '').trim().toUpperCase()
  return opticalEventStatusLabels[normalized] || '未知'
}

export function displaySwitchVendor(value: unknown): string {
  const vendor = String(value || '').trim().toUpperCase()
  if (vendor === 'ZTE') return '中兴 ZTE'
  if (vendor === 'H3C') return '新华三 H3C'
  return vendor || '—'
}

export function displayPowerThreshold(low: unknown, high: unknown): string {
  const lowText = displayTracksideValue(low)
  const highText = displayTracksideValue(high)
  if (lowText === '—' && highText === '—') return '—'
  return `${lowText} ~ ${highText} dBm`
}

export function displayTracksideSnapshotTime(value: unknown, status: unknown): string {
  const timestamp = displayTracksideValue(value)
  if (timestamp === '—') return timestamp
  if (String(status || '').trim().toLowerCase() === 'stale') {
    return `${t('trackside.snapshot.stale', '历史数据')} · ${timestamp}`
  }
  return timestamp
}

export function displayLldpStatus(value: unknown): string {
  const status = String(value || '').trim().toUpperCase()
  return {
    MATCHED: '已匹配',
    AMBIGUOUS: '候选不唯一',
    UNRESOLVED: '未匹配',
    NO_NEIGHBOR: '无邻居',
    SAMPLE_REQUIRED: '待真实样本验证',
    CURRENT_CONSISTENT: '正常',
    CURRENT_CONFLICT: '当前冲突',
    HISTORICAL_CONFLICT: '历史冲突',
    PORT_MIGRATED: '接口已迁移',
    STALE_SNAPSHOT: '快照过期',
    NO_CURRENT_EVIDENCE: '无当前记录',
    LLDP_SNAPSHOT_STALE: '等待同步',
    LLDP_EXACT_MATCH_PENDING: '等待同步',
    LLDP_CONFLICT_CURRENT: '当前冲突',
  }[status] || status || '—'
}
