import { apiRequest } from './client'
import type {
  FeatureConfigurationTarget,
  FeatureSetting,
  FeatureSettingsSnapshot,
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
export const getFeatureSettings = (target: FeatureConfigurationTarget = 'runtime') => apiRequest<FeatureSettingsSnapshot>(`/api/settings/features?target=${encodeURIComponent(target)}`)
export const saveFeatureSettings = (items: FeatureSetting[], target: FeatureConfigurationTarget = 'runtime') => featureRequest('/api/settings/features', items, target, 'PUT')
export const previewFeatureSettings = (items: FeatureSetting[], target: FeatureConfigurationTarget = 'runtime') => featureRequest('/api/settings/features/preview', items, target, 'POST')
export const exitFeatureSettingsPreview = (target: FeatureConfigurationTarget = 'runtime') => apiRequest<FeatureSettingsSnapshot>(`/api/settings/features/preview/exit?target=${encodeURIComponent(target)}`, { method: 'POST' })
export const restoreFeatureSettings = (target: FeatureConfigurationTarget = 'runtime') => apiRequest<FeatureSettingsSnapshot>('/api/settings/features/restore', { method: 'POST', body: JSON.stringify({ target, confirmed: true }) })

function featureRequest(
  path: string,
  items: FeatureSetting[],
  target: FeatureConfigurationTarget,
  method: 'PUT' | 'POST',
) {
  const updates = items.map(({ feature_id, visible, enabled, package_included }) => ({
    feature_id,
    visible,
    enabled,
    package_included,
  }))
  return apiRequest<FeatureSettingsSnapshot>(path, {
    method,
    body: JSON.stringify({ target, items: updates, confirmed: true }),
  })
}
