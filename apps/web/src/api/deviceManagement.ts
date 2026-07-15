import { apiRequest } from './client'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionTest,
  DeviceDeleteToken,
  DeviceDetailResponse,
  DeviceExportRequest,
  DeviceExternalTerminalAction,
  DeviceGroup,
  DeviceImportPreview,
  DeviceEditPreview,
  DeviceEditPreviewRequest,
  DeviceListQuery,
  DevicePage,
  DeviceTaskBatch,
  DeviceTaskReference,
  DeviceWriteResponse,
} from '../types/deviceManagement'

function queryString(values: DeviceListQuery): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function listDevices(query: DeviceListQuery = {}): Promise<DevicePage> {
  return apiRequest<DevicePage>(`/api/device-management/devices${queryString(query)}`)
}

export function getDevice(deviceUuid: string): Promise<DeviceDetailResponse> {
  return apiRequest<DeviceDetailResponse>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}`)
}

export function previewDeviceEdit(deviceUuid: string, payload: DeviceEditPreviewRequest): Promise<DeviceEditPreview> {
  return apiRequest<DeviceEditPreview>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/edit-preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function startDeviceConnectionTest(deviceUuid: string, protocol: DeviceConnectionProtocol): Promise<DeviceConnectionTest> {
  return apiRequest<DeviceConnectionTest>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/connection-tests`, {
    method: 'POST',
    body: JSON.stringify({ protocol }),
  })
}

export function getDeviceConnectionTest(taskId: string): Promise<DeviceConnectionTest> {
  return apiRequest<DeviceConnectionTest>(`/api/device-management/connection-tests/${encodeURIComponent(taskId)}`)
}

export function listDeviceGroups(): Promise<DeviceGroup[]> {
  return apiRequest<DeviceGroup[]>('/api/device-management/groups')
}

export function createDevice(payload: DeviceEditPreviewRequest): Promise<DeviceWriteResponse> {
  return apiRequest<DeviceWriteResponse>('/api/device-management/devices', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateDevice(deviceUuid: string, payload: DeviceEditPreviewRequest): Promise<DeviceWriteResponse> {
  return apiRequest<DeviceWriteResponse>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function duplicateDevice(deviceUuid: string): Promise<DeviceWriteResponse> {
  return apiRequest<DeviceWriteResponse>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/duplicate`, { method: 'POST' })
}

export function createDeviceGroup(name: string): Promise<DeviceGroup> {
  return apiRequest<DeviceGroup>('/api/device-management/groups', { method: 'POST', body: JSON.stringify({ name }) })
}

export function renameDeviceGroup(groupId: number, name: string): Promise<DeviceGroup> {
  return apiRequest<DeviceGroup>(`/api/device-management/groups/${groupId}`, { method: 'PATCH', body: JSON.stringify({ name }) })
}

export function deleteDeviceGroup(groupId: number): Promise<void> {
  return apiRequest<void>(`/api/device-management/groups/${groupId}`, { method: 'DELETE' })
}

export function assignDeviceGroup(deviceUuids: string[], groupId: number | null): Promise<{ success: number; failed: number; group_id: number | null }> {
  return apiRequest<{ success: number; failed: number; group_id: number | null }>('/api/device-management/groups/assign', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids, group_id: groupId }) })
}

export function issueDeviceDeleteToken(deviceUuids: string[]): Promise<DeviceDeleteToken> {
  return apiRequest<DeviceDeleteToken>('/api/device-management/devices/delete-confirmation', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids }) })
}

export function deleteDevices(deviceUuids: string[], confirmationToken: string): Promise<{ deleted: number; device_uuids: string[] }> {
  return apiRequest<{ deleted: number; device_uuids: string[] }>('/api/device-management/devices/batch-delete', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids, confirmation_token: confirmationToken }) })
}

export function startBatchRefreshDetails(deviceUuids: string[]): Promise<DeviceTaskBatch> {
  return apiRequest<DeviceTaskBatch>('/api/device-management/devices/batch-refresh-details', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids }) })
}

export function previewDeviceImport(file: File): Promise<DeviceImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<DeviceImportPreview>('/api/device-management/imports/preview', { method: 'POST', body: form })
}

export function confirmDeviceImport(previewToken: string): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/imports/confirm', { method: 'POST', body: JSON.stringify({ preview_token: previewToken }) })
}

export function startDeviceCsvExport(payload: DeviceExportRequest): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/csv', { method: 'POST', body: JSON.stringify(payload) })
}

export function startDeviceTemplateExport(): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/template', { method: 'POST', body: JSON.stringify({}) })
}

export function startSecureCrtExport(payload: DeviceExportRequest): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/securecrt', { method: 'POST', body: JSON.stringify(payload) })
}

export function startOmniPeekExport(payload: DeviceExportRequest & { line_name: string; include_device_mr?: boolean }): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/omnipeek', { method: 'POST', body: JSON.stringify(payload) })
}

export function downloadDeviceExport(taskId: string, artifactId: string): string {
  const params = new URLSearchParams({ artifact_id: artifactId })
  return `/api/device-management/exports/${encodeURIComponent(taskId)}/download?${params.toString()}`
}

export function getDeviceExportTask(taskId: string): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>(`/api/device-management/exports/${encodeURIComponent(taskId)}`)
}

export function getDeviceTask(taskId: string): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>(`/api/device-management/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelDeviceTask(taskId: string): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>(`/api/device-management/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function startDeviceDiagnosticDownload(deviceUuids: string[]): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/diagnostic-download', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids }) })
}

export function requestExternalTerminal(deviceUuid: string, terminalType: 'securecrt' | 'putty' | 'xshell'): Promise<DeviceExternalTerminalAction> {
  return apiRequest<DeviceExternalTerminalAction>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/external-terminal`, { method: 'POST', body: JSON.stringify({ terminal_type: terminalType }) })
}
