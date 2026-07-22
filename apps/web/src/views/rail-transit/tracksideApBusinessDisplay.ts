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
