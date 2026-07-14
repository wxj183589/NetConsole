import { apiRequest } from './client'
import type {
  DeviceConnectionProtocol,
  DeviceConnectionTest,
  DeviceDetailResponse,
  DeviceEditPreview,
  DeviceEditPreviewRequest,
  DeviceListQuery,
  DevicePage,
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
