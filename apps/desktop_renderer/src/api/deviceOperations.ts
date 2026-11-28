import { apiRequest } from './client'

export const deviceMaintenanceTask = 'device_maintenance_collection'
const root = '/api/device-operations'

export const deviceTaskLabels = {
  configuration: '配置收集', backup: '配置备份', diagnostic: '诊断收集',
  optical: '光衰收集', lldp: 'LLDP 收集', version: '版本检查', custom: '自定义命令采集',
  wireless: '无线信息收集', mesh: 'MESH 收集',
} as const

export type DeviceTaskKind = keyof typeof deviceTaskLabels
export type TargetGroup = number | 'all' | 'ungrouped'

export interface CommandTemplate {
  source: string
  schema_fields: Record<string, { type: string; required?: boolean; default?: unknown }>
  values: Record<string, unknown>
}

export interface CommandPreview {
  commands: string[]
  risk: 'read_only' | 'configuration_change'
}

export interface SavedTemplateDefinition extends Omit<CommandTemplate, 'values'> {
  name: string
  category: string
  vendor: 'h3c'
  platform: 'comware'
  device_roles: string[]
  command_type: CommandPreview['risk']
  enabled: boolean
}

export interface SavedTemplate extends SavedTemplateDefinition {
  template_id: string
  version: number
  updated_at: string
}

export interface SavedTemplateParameters {
  template_id: string
  version: number
  values: Record<string, unknown>
}

export interface SavedTemplatePreview extends CommandPreview {
  template_id: string
  version: number
  preview_digest: string
}

export interface DeviceTaskReference {
  scheduled_at?: string | null
  task_id: string
  run_id: string
  target_count: number
}

export interface DeviceExecution {
  device_uuid: string
  device_name?: string
  status: 'success' | 'failed' | 'partial' | 'skipped'
  started_at: string
  finished_at: string
  elapsed_ms?: number
  message?: string
  warning_message?: string
  collect_run_uuid?: string
  software_version?: string
  device_model?: string
  snapshot_ids?: number[]
  snapshot_types?: string[]
  record_count?: number
  records_truncated?: boolean
  wireless_summary?: Record<string, unknown>
  ac_time?: string
  records?: Record<string, unknown>[]
  command_results?: { command: string; status: string; output: string }[]
}

export interface DeviceTaskResult {
  task_id?: string
  run_id?: string
  template?: { template_id?: string }
  items?: DeviceExecution[]
}

function post<T>(path: string, body?: object): Promise<T> {
  return apiRequest<T>(root + path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
}

export function previewCommandTemplate(template: CommandTemplate): Promise<CommandPreview> {
  return post('/templates/preview', template)
}

export function listCommandTemplates(): Promise<SavedTemplate[]> {
  return apiRequest(root + '/templates')
}

export function getCommandTemplateVersions(templateId: string): Promise<SavedTemplate[]> {
  return apiRequest(`${root}/templates/${encodeURIComponent(templateId)}/versions`)
}

export function saveCommandTemplate(definition: SavedTemplateDefinition, current?: SavedTemplate): Promise<SavedTemplate> {
  if (!current) return post('/templates', definition)
  return apiRequest(`${root}/templates/${encodeURIComponent(current.template_id)}?expected_version=${current.version}`, {
    method: 'PUT', body: JSON.stringify(definition),
  })
}

export function previewSavedTemplate(parameters: SavedTemplateParameters): Promise<SavedTemplatePreview> {
  return post('/templates/saved-preview', parameters)
}

export function startDeviceTask(payload: {
  kind: DeviceTaskKind
  device_uuids: string[]
  group_id: TargetGroup | null
  organization_uid?: string | null
  concurrency?: number
  command_timeout?: number
  scheduled_at?: string
  template?: CommandTemplate
  saved_template?: SavedTemplateParameters & { preview_digest: string }
}): Promise<DeviceTaskReference> {
  return post('/tasks', payload)
}

export interface DeviceTaskSchedule {
  task_id: string
  scheduled_at: string
  request: { kind: DeviceTaskKind; device_uuids: string[] }
  status: 'WAITING' | 'SUBMITTED' | 'FAILED' | 'CANCELLED'
  error: string
}

export function listDeviceTaskSchedules(): Promise<DeviceTaskSchedule[]> {
  return apiRequest(root + '/schedules')
}

export function cancelDeviceTaskSchedule(id: string): Promise<void> {
  return apiRequest(`${root}/schedules/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function getDeviceTaskResult(id: string): Promise<DeviceTaskResult> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(id)}/result`)
}

export function retryDeviceTask(id: string): Promise<DeviceTaskReference> {
  return post(`/tasks/${encodeURIComponent(id)}/retry`)
}

export function listTaskOrganizations(): Promise<{ uid: string; name: string; parent_uid: string }[]> {
  return apiRequest(root + '/organizations')
}

export function startDeviceTaskResultExport(id: string): Promise<{ task_id: string }> {
  return post(`/tasks/${encodeURIComponent(id)}/exports`)
}
