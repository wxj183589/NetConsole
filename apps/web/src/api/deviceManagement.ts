import { apiRequest } from './client'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionTest,
  DeviceDeleteToken,
  DeviceDetailResponse,
  DeviceExportRequest,
  DeviceExternalTerminalAction,
  DeviceExternalTerminalBatch,
  DeviceExternalTerminalConfirmation,
  DeviceExternalTerminalSettings,
  DeviceFormConnectionTestRequest,
  DeviceGroup,
  DeviceImportPreview,
  DeviceHistoryPage,
  DeviceListQuery,
  DeviceOmniPeekPreview,
  DevicePage,
  DeviceTaskBatch,
  DeviceTaskReference,
  DeviceWriteRequest,
  DeviceWriteResponse,
} from '../types/deviceManagement'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

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

export function createDevice(payload: DeviceWriteRequest): Promise<DeviceWriteResponse> {
  return apiRequest<DeviceWriteResponse>('/api/device-management/devices', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateDevice(deviceUuid: string, payload: DeviceWriteRequest): Promise<DeviceWriteResponse> {
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

export function startBatchConnectionTests(deviceUuids: string[]): Promise<DeviceTaskBatch> {
  return apiRequest<DeviceTaskBatch>('/api/device-management/devices/batch-connection-tests', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids }) })
}

export function startDeviceOpticalRefresh(deviceUuid: string): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/refresh-optical`, { method: 'POST' })
}

export function getDeviceHistory(
  deviceUuid: string,
  kind: 'interface' | 'optical' | 'lldp',
  objectName: string,
  page = 1,
  pageSize = 50,
): Promise<DeviceHistoryPage> {
  const params = new URLSearchParams({
    kind,
    object_name: objectName,
    page: String(page),
    page_size: String(pageSize),
  })
  return apiRequest<DeviceHistoryPage>(`/api/device-management/devices/${encodeURIComponent(deviceUuid)}/history?${params}`)
}

export function previewDeviceImport(file: File): Promise<DeviceImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<DeviceImportPreview>('/api/device-management/imports/preview', { method: 'POST', body: form })
}

export function confirmDeviceImport(previewToken: string, duplicateStrategy: 'reject' | 'skip' | 'create_new'): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/imports/confirm', { method: 'POST', body: JSON.stringify({ preview_token: previewToken, duplicate_strategy: duplicateStrategy }) })
}

export function startDeviceFormConnectionTest(payload: DeviceFormConnectionTestRequest): Promise<DeviceConnectionTest> {
  return apiRequest<DeviceConnectionTest>('/api/device-management/connection-tests/form', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
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

export function startSecureCrtExportWithTemplate(payload: DeviceExportRequest, file: File): Promise<DeviceTaskReference> {
  const form = new FormData()
  form.append('selection', JSON.stringify(payload))
  form.append('file', file)
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/securecrt-with-template', { method: 'POST', body: form })
}

export function startOmniPeekPreview(payload: DeviceExportRequest): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/omnipeek-preview', { method: 'POST', body: JSON.stringify(payload) })
}

export function getOmniPeekPreview(taskId: string): Promise<DeviceOmniPeekPreview> {
  return apiRequest<DeviceOmniPeekPreview>(`/api/device-management/exports/omnipeek-preview/${encodeURIComponent(taskId)}`)
}

export function startOmniPeekExport(payload: DeviceExportRequest & { line_name: string; include_device_mr?: boolean; selected_item_keys?: string[]; excluded_item_keys?: string[]; force_export_keys?: string[] }): Promise<DeviceTaskReference> {
  return apiRequest<DeviceTaskReference>('/api/device-management/exports/omnipeek', { method: 'POST', body: JSON.stringify(payload) })
}

export function deviceExportDownloadRequest(
  taskId: string,
  artifactId: string,
  suggestedName: string,
): BackendDownloadRequest {
  return {
    apiPath: `/api/device-management/exports/${encodeURIComponent(taskId)}/download`,
    query: { artifact_id: artifactId },
    suggestedName,
  }
}

export function deviceDiagnosticDownloadRequest(
  taskId: string,
  artifactId: string,
): BackendDownloadRequest {
  return {
    apiPath: `/api/device-management/diagnostics/${encodeURIComponent(taskId)}/download`,
    query: { artifact_id: artifactId },
    suggestedName: '设备诊断信息.zip',
  }
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

export function issueExternalTerminalConfirmation(deviceUuids: string[], terminalType: 'securecrt' | 'putty' | 'xshell'): Promise<DeviceExternalTerminalConfirmation> {
  return apiRequest<DeviceExternalTerminalConfirmation>('/api/device-management/external-terminal/confirmation', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids, terminal_type: terminalType }) })
}

export function launchExternalTerminals(deviceUuids: string[], terminalType: 'securecrt' | 'putty' | 'xshell', confirmationToken = ''): Promise<DeviceExternalTerminalBatch> {
  return apiRequest<DeviceExternalTerminalBatch>('/api/device-management/external-terminal/launch', { method: 'POST', body: JSON.stringify({ device_uuids: deviceUuids, terminal_type: terminalType, confirmation_token: confirmationToken }) })
}

export function getExternalTerminalSettings(): Promise<DeviceExternalTerminalSettings> {
  return apiRequest<DeviceExternalTerminalSettings>('/api/device-management/external-terminal/settings')
}

export function updateExternalTerminalSettings(payload: DeviceExternalTerminalSettings): Promise<DeviceExternalTerminalSettings> {
  return apiRequest<DeviceExternalTerminalSettings>('/api/device-management/external-terminal/settings', { method: 'PUT', body: JSON.stringify(payload) })
}
