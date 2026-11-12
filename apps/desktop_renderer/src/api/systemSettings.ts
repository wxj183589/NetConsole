import { apiRequest } from './client'
import type {
  NetworkComponentMode,
  NetworkComponentName,
  NetworkComponentsSnapshot,
  RuntimeSelfCheckSnapshot,
  SystemSettingsSnapshot,
  SystemSettingsValues,
} from '../types/systemSettings'

export const getSystemSettings = () => apiRequest<SystemSettingsSnapshot>('/api/settings')
export const reloadSystemSettings = () => apiRequest<SystemSettingsSnapshot>('/api/settings/reload', { method: 'POST' })
export const getRuntimeSelfCheck = () => apiRequest<RuntimeSelfCheckSnapshot>('/api/settings/self-check')
export const saveSystemSettings = (values: SystemSettingsValues, expectedVersion: string) => apiRequest<SystemSettingsSnapshot>('/api/settings', { method: 'PUT', body: JSON.stringify({ ...values, expected_version: expectedVersion }) })
export const getNetworkComponents = () => apiRequest<NetworkComponentsSnapshot>('/api/settings/network-components')
export const saveNetworkComponent = (
  componentName: NetworkComponentName,
  mode: NetworkComponentMode,
  customPath: string,
  expectedVersion: string,
) => apiRequest<NetworkComponentsSnapshot>(`/api/settings/network-components/${componentName}`, {
  method: 'PUT',
  body: JSON.stringify({ mode, custom_path: customPath, expected_version: expectedVersion }),
})
