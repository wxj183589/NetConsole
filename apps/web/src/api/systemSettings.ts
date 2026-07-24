import { apiRequest } from './client'
import type { FeatureSetting, FeatureSettingsSnapshot, RuntimeSelfCheckSnapshot, SystemSettingsSnapshot, SystemSettingsValues } from '../types/systemSettings'

export const getSystemSettings = () => apiRequest<SystemSettingsSnapshot>('/api/settings')
export const reloadSystemSettings = () => apiRequest<SystemSettingsSnapshot>('/api/settings/reload', { method: 'POST' })
export const getRuntimeSelfCheck = () => apiRequest<RuntimeSelfCheckSnapshot>('/api/settings/self-check')
export const saveSystemSettings = (values: SystemSettingsValues, expectedVersion: string) => apiRequest<SystemSettingsSnapshot>('/api/settings', { method: 'PUT', body: JSON.stringify({ ...values, expected_version: expectedVersion }) })
export const getFeatureSettings = () => apiRequest<FeatureSettingsSnapshot>('/api/settings/features')
export const saveFeatureSettings = (items: FeatureSetting[]) => featureRequest('/api/settings/features', items, 'PUT')
export const previewFeatureSettings = (items: FeatureSetting[]) => featureRequest('/api/settings/features/preview', items, 'POST')
export const restoreFeatureSettings = () => apiRequest<FeatureSettingsSnapshot>('/api/settings/features/restore', { method: 'POST', body: JSON.stringify({ confirmed: true }) })

function featureRequest(path: string, items: FeatureSetting[], method: 'PUT' | 'POST') {
  return apiRequest<FeatureSettingsSnapshot>(path, { method, body: JSON.stringify({ items, confirmed: true }) })
}
