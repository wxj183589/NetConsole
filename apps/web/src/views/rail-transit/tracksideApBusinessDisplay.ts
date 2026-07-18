export type TracksideOpticalTagType = 'success' | 'warning' | 'danger' | 'info'

export interface TracksideOpticalPresentation {
  label: string
  tagType: TracksideOpticalTagType
  className: string
}

const opticalPresentations: Record<string, TracksideOpticalPresentation> = {
  normal: { label: '正常', tagType: 'success', className: 'optical-normal' },
  notice: { label: '偏低关注', tagType: 'warning', className: 'optical-notice' },
  warning: { label: '提示告警', tagType: 'warning', className: 'optical-warning' },
  alarm: { label: '一般告警', tagType: 'danger', className: 'optical-alarm' },
  link_abnormal: { label: '链路异常', tagType: 'danger', className: 'optical-link-abnormal' },
  link_down: { label: '链路断开', tagType: 'danger', className: 'optical-link-down' },
  no_light: { label: '无光', tagType: 'danger', className: 'optical-no-light' },
  no_module: { label: '无光模块', tagType: 'danger', className: 'optical-no-module' },
  skipped: { label: '未检查', tagType: 'info', className: 'optical-skipped' },
  not_collected: { label: '未采集', tagType: 'info', className: 'optical-not-collected' },
  unknown: { label: '未知', tagType: 'info', className: 'optical-unknown' },
  offline: { label: '离线', tagType: 'danger', className: 'optical-offline' },
}

const missingPresentation: TracksideOpticalPresentation = {
  label: '—',
  tagType: 'info',
  className: 'optical-missing',
}

export function tracksideOpticalPresentation(value: unknown): TracksideOpticalPresentation {
  if (typeof value !== 'string' || value.trim() === '') return missingPresentation
  const status = value.trim().toLowerCase()
  return opticalPresentations[status] ?? {
    label: value.trim(),
    tagType: 'info',
    className: 'optical-unknown',
  }
}

export function displayTracksideValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}
