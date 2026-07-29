import { normalizedOpticalStatus, opticalStatusPresentation } from '../../utils/opticalPresentation'

export type TracksideOpticalTagType = 'success' | 'warning' | 'danger' | 'info'

export interface TracksideOpticalPresentation {
  label: string
  tagType: TracksideOpticalTagType
  className: string
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
  unknown: 'optical-unknown',
  offline: 'optical-offline',
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

export function displayTracksideValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
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

export function displayLldpStatus(value: unknown): string {
  const status = String(value || '').trim().toUpperCase()
  return {
    MATCHED: '已匹配',
    AMBIGUOUS: '候选不唯一',
    UNRESOLVED: '未匹配',
    NO_NEIGHBOR: '无邻居',
    SAMPLE_REQUIRED: '待真实样本验证',
  }[status] || status || '—'
}

export function displayBidirectionalLoss(
  statusValue: unknown,
  forward: unknown,
  reverse: unknown,
): string {
  const status = String(statusValue || '').trim().toUpperCase()
  if (status === 'CALCULATED') {
    return `正向 ${displayTracksideValue(forward)} dB / 反向 ${displayTracksideValue(reverse)} dB`
  }
  return {
    SINGLE_ENDED_ONLY: '无法计算（仅有单端光功率）',
    REMOTE_DOM_UNAVAILABLE: '无法计算（对端 DOM 不可用）',
    STALE_SAMPLE: '无法计算（两端样本不同步）',
    NEIGHBOR_UNCERTAIN: '无法计算（对端关系不可靠）',
    MODULE_OFFLINE: '无法计算（模块离线或无 DOM）',
    NOT_VERIFIED: '当前数据不足，无法计算双向光衰',
  }[status] || '—'
}
