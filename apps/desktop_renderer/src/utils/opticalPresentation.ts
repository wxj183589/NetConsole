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

export interface OpticalRxPresentationInput {
  backendStatus?: unknown
  rxPower?: unknown
  freshness?: unknown
}

export interface ApOpticalPresentationInput extends OpticalRxPresentationInput {
  model?: unknown
  opticalApplicable?: boolean
}

export interface DualOpticalPresentationInput {
  apBackendStatus?: unknown
  apRxPower?: unknown
  switchBackendStatus?: unknown
  switchRxPower?: unknown
  model?: unknown
  opticalApplicable?: boolean
  freshness?: unknown
}

export interface DualOpticalStatusPresentation {
  ap: OpticalStatusPresentation
  switch: OpticalStatusPresentation
  overall: OpticalStatusPresentation
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
  collection_failed: { label: '采集失败/设备不可达', tagType: 'warning', tone: 'warning' },
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

export function opticalRxStatusPresentation(input: OpticalRxPresentationInput): OpticalStatusPresentation {
  const backendStatus = normalizedOpticalStatus(input.backendStatus)
  if (backendStatus === 'not_applicable') return opticalStatusPresentation(backendStatus)

  const rxPower = parseOpticalPower(input.rxPower)
  let presentation: OpticalStatusPresentation
  if (isExplicitOpticalFault(backendStatus)) {
    presentation = opticalStatusPresentation(backendStatus)
  } else if (['no_module', 'unverified', 'dom_unavailable', 'skipped', 'offline', 'collection_failed'].includes(backendStatus)) {
    presentation = opticalStatusPresentation(backendStatus)
  } else if (rxPower !== null && rxPower < AP_BUSINESS_RX_MIN_DBM) {
    presentation = opticalStatusPresentation('abnormal')
  } else if (isExplicitOpticalAbnormal(backendStatus)) {
    presentation = opticalStatusPresentation(backendStatus)
  } else if (rxPower !== null) {
    presentation = opticalStatusPresentation('normal')
  } else {
    presentation = opticalStatusPresentation('not_collected')
  }

  return withOpticalFreshness(presentation, input.freshness)
}

export function opticalRxValuePresentation(input: OpticalRxPresentationInput): OpticalValuePresentation {
  const presentation = opticalRxStatusPresentation(input)
  const className = {
    normal: 'optical-value-normal',
    warning: 'optical-value-warning',
    danger: 'optical-value-danger',
    muted: 'optical-value-muted',
  }[presentation.tone]
  return { ...presentation, className }
}

export function apOpticalStatusPresentation(input: ApOpticalPresentationInput): OpticalStatusPresentation {
  if (!isApOpticalApplicable(input.model, input.opticalApplicable)) {
    return opticalStatusPresentation('not_applicable')
  }
  return opticalRxStatusPresentation(input)
}

export function dualOpticalStatusPresentation(input: DualOpticalPresentationInput): DualOpticalStatusPresentation {
  if (!isApOpticalApplicable(input.model, input.opticalApplicable)) {
    const notApplicable = opticalStatusPresentation('not_applicable')
    return { ap: notApplicable, switch: notApplicable, overall: notApplicable }
  }

  const ap = opticalRxStatusPresentation({
    backendStatus: input.apBackendStatus,
    rxPower: input.apRxPower,
    freshness: input.freshness,
  })
  const switchSide = opticalRxStatusPresentation({
    backendStatus: input.switchBackendStatus,
    rxPower: input.switchRxPower,
    freshness: input.freshness,
  })
  const abnormal = [ap, switchSide].filter((item) => isExplicitOpticalAbnormal(item.status))
  let overall: OpticalStatusPresentation
  if (abnormal.length) {
    overall = opticalStatusPresentation(
      abnormal.sort((left, right) => opticalStatusRank(right.status) - opticalStatusRank(left.status))[0].status,
    )
  } else if (ap.status === 'normal' && switchSide.status === 'normal') {
    overall = opticalStatusPresentation('normal')
  } else if (ap.status === 'collection_failed' || switchSide.status === 'collection_failed') {
    overall = opticalStatusPresentation('collection_failed')
  } else {
    overall = opticalStatusPresentation('not_collected')
  }
  return {
    ap,
    switch: switchSide,
    overall: withOpticalFreshness(overall, input.freshness),
  }
}

export function dualOpticalReason(input: DualOpticalPresentationInput): string {
  const presentation = dualOpticalStatusPresentation(input)
  if (presentation.overall.status === 'not_applicable') {
    return '该型号使用网口接入，不适用 AP 光模块光衰检测。'
  }
  const sides = [
    opticalSideReason('AP 侧收光', presentation.ap, input.apRxPower),
    opticalSideReason('交换机侧收光', presentation.switch, input.switchRxPower),
  ]
  sides.sort((left, right) => Number(right.abnormal) - Number(left.abnormal))
  const conclusion = presentation.overall.status === 'not_collected'
    ? '综合判定：数据不完整。'
    : `综合判定：${presentation.overall.label.replace('（数据已过期）', '')}。`
  return `${sides.map((item) => item.text).join('；')}。${conclusion}`
}

function withOpticalFreshness(
  presentation: OpticalStatusPresentation,
  freshness: unknown,
): OpticalStatusPresentation {
  if (normalizedOpticalStatus(freshness) === 'stale' && presentation.tone !== 'muted') {
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

function isExplicitOpticalFault(status: string): boolean {
  return new Set(['critical', 'link_abnormal', 'link_down', 'no_light']).has(status)
}

function opticalStatusRank(status: string): number {
  return {
    critical: 100,
    no_light: 95,
    link_down: 90,
    link_abnormal: 90,
    abnormal: 80,
    alarm: 70,
    warning: 60,
    notice: 50,
  }[status] || 0
}

function opticalSideReason(
  label: string,
  presentation: OpticalStatusPresentation,
  value: unknown,
): { text: string; abnormal: boolean } {
  const power = parseOpticalPower(value)
  if (presentation.status === 'abnormal' && power !== null) {
    return {
      text: `${label}异常：${power.toFixed(2)} dBm，低于 ${AP_BUSINESS_RX_MIN_DBM.toFixed(2)} dBm`,
      abnormal: true,
    }
  }
  if (presentation.status === 'normal' && power !== null) {
    return { text: `${label}正常：${power.toFixed(2)} dBm`, abnormal: false }
  }
  return {
    text: `${label}${presentation.label}`,
    abnormal: isExplicitOpticalAbnormal(presentation.status),
  }
}

export function formatOpticalPower(value: unknown): string {
  if (value === null || value === undefined) return '--'
  const text = String(value).trim()
  if (!text || ['-', '--', '—'].includes(text)) return '--'
  if (text.toLowerCase().includes('dbm')) return text
  return /[-+]?\d+(?:\.\d+)?/.test(text) ? `${text} dBm` : text
}
