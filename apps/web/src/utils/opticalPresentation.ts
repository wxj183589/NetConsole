export type OpticalTagType = 'success' | 'warning' | 'danger' | 'info'
export type OpticalTone = 'normal' | 'warning' | 'danger' | 'muted'

export interface OpticalStatusPresentation {
  status: string
  label: string
  tagType: OpticalTagType
  tone: OpticalTone
}

export interface OpticalValuePresentation extends OpticalStatusPresentation {
  className: string
}

export interface ApOpticalPresentationInput {
  backendStatus?: unknown
  rxPower?: unknown
  model?: unknown
  opticalApplicable?: boolean
  freshness?: unknown
}

export const AP_BUSINESS_RX_MIN_DBM = -13.9

const statusPresentations: Record<string, Omit<OpticalStatusPresentation, 'status'>> = {
  normal: { label: '正常', tagType: 'success', tone: 'normal' },
  notice: { label: '偏低关注', tagType: 'warning', tone: 'warning' },
  warning: { label: '提示告警', tagType: 'warning', tone: 'warning' },
  alarm: { label: '一般告警', tagType: 'danger', tone: 'danger' },
  critical: { label: '严重告警', tagType: 'danger', tone: 'danger' },
  link_abnormal: { label: '链路异常', tagType: 'danger', tone: 'danger' },
  link_down: { label: '链路断开', tagType: 'danger', tone: 'danger' },
  no_light: { label: '无光', tagType: 'danger', tone: 'danger' },
  no_module: { label: '无光模块', tagType: 'info', tone: 'muted' },
  abnormal: { label: '光衰大', tagType: 'danger', tone: 'danger' },
  unverified: { label: '状态未知/第三方模块', tagType: 'warning', tone: 'warning' },
  dom_unavailable: { label: '不支持 DOM', tagType: 'info', tone: 'muted' },
  skipped: { label: '未检查', tagType: 'info', tone: 'muted' },
  not_collected: { label: '光诊断未采集', tagType: 'info', tone: 'muted' },
  no_data: { label: '光诊断未采集', tagType: 'info', tone: 'muted' },
  not_applicable: { label: '不适用', tagType: 'info', tone: 'muted' },
  unknown: { label: '未知', tagType: 'info', tone: 'muted' },
  offline: { label: '离线', tagType: 'danger', tone: 'danger' },
}

export function normalizedOpticalStatus(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : ''
}

export function opticalStatusPresentation(value: unknown): OpticalStatusPresentation {
  const status = normalizedOpticalStatus(value)
  if (!status) return { status, label: '—', tagType: 'info', tone: 'muted' }
  const mapped = statusPresentations[status]
  return mapped ? { status, ...mapped } : { status, label: String(value).trim(), tagType: 'info', tone: 'muted' }
}

export function opticalValuePresentation(status: unknown, freshness = 'fresh'): OpticalValuePresentation {
  const presentation = opticalStatusPresentation(status)
  if (freshness === 'stale' && presentation.tone !== 'muted') {
    return { ...presentation, tagType: 'warning', tone: 'warning', className: 'optical-value-stale' }
  }
  const className = {
    normal: 'optical-value-normal',
    warning: 'optical-value-warning',
    danger: 'optical-value-danger',
    muted: 'optical-value-muted',
  }[presentation.tone]
  return { ...presentation, className }
}

export function parseOpticalPower(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  const text = String(value).trim()
  if (!text || ['-', '--', '—'].includes(text)) return null
  const match = text.match(/[-+]?\d+(?:\.\d+)?/)
  if (!match) return null
  const parsed = Number(match[0])
  return Number.isFinite(parsed) ? parsed : null
}

export function isApOpticalApplicable(model: unknown, opticalApplicable?: boolean): boolean {
  if (opticalApplicable === false) return false
  return String(model ?? '').trim().toLowerCase() !== 'wa6522'
}

export function apOpticalStatusPresentation(input: ApOpticalPresentationInput): OpticalStatusPresentation {
  if (!isApOpticalApplicable(input.model, input.opticalApplicable)) {
    return opticalStatusPresentation('not_applicable')
  }

  const backendStatus = normalizedOpticalStatus(input.backendStatus)
  if (backendStatus === 'not_applicable') return opticalStatusPresentation(backendStatus)

  const rxPower = parseOpticalPower(input.rxPower)
  let presentation: OpticalStatusPresentation
  if (rxPower !== null && rxPower < AP_BUSINESS_RX_MIN_DBM) {
    presentation = opticalStatusPresentation('abnormal')
  } else if (isExplicitOpticalAbnormal(backendStatus)) {
    presentation = opticalStatusPresentation(backendStatus)
  } else if (rxPower !== null) {
    presentation = opticalStatusPresentation('normal')
  } else if (['no_module', 'dom_unavailable', 'skipped', 'offline'].includes(backendStatus)) {
    presentation = opticalStatusPresentation(backendStatus)
  } else {
    presentation = opticalStatusPresentation('not_collected')
  }

  if (normalizedOpticalStatus(input.freshness) === 'stale' && presentation.tone !== 'muted') {
    return {
      ...presentation,
      label: `${presentation.label}（数据已过期）`,
      tagType: 'warning',
      tone: 'warning',
    }
  }
  return presentation
}

export function apOpticalValuePresentation(input: ApOpticalPresentationInput): OpticalValuePresentation {
  const presentation = apOpticalStatusPresentation(input)
  const className = {
    normal: 'optical-value-normal',
    warning: 'optical-value-warning',
    danger: 'optical-value-danger',
    muted: 'optical-value-muted',
  }[presentation.tone]
  return { ...presentation, className }
}

function isExplicitOpticalAbnormal(status: string): boolean {
  return new Set([
    'notice',
    'warning',
    'alarm',
    'abnormal',
    'critical',
    'link_abnormal',
    'link_down',
    'no_light',
  ]).has(status)
}

export function formatOpticalPower(value: unknown): string {
  if (value === null || value === undefined) return '--'
  const text = String(value).trim()
  if (!text || ['-', '--', '—'].includes(text)) return '--'
  if (text.toLowerCase().includes('dbm')) return text
  return /[-+]?\d+(?:\.\d+)?/.test(text) ? `${text} dBm` : text
}
