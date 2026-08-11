import type { DeviceCompatibilitySummary } from '../types/deviceCompatibility'
import { apiRequest } from './client'

const root = '/api/device-compatibility'

export function getDeviceCompatibilitySummary(): Promise<DeviceCompatibilitySummary> {
  return apiRequest<DeviceCompatibilitySummary>(`${root}/summary`)
}
