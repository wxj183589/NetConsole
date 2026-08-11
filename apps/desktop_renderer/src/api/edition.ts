import { apiRequest } from './client'

export interface EditionRuntimeStatus {
  edition: string
  base_profile: string
  active_profile: string
  full_features_active: boolean
  admin_unlock_available: boolean
  relock_available: boolean
  packaged_runtime: boolean
  profile_source: string
}

export function getEditionRuntimeStatus(): Promise<EditionRuntimeStatus> {
  return apiRequest<EditionRuntimeStatus>('/api/features/edition')
}

export function unlockCustomerEdition(password: string): Promise<EditionRuntimeStatus> {
  return apiRequest<EditionRuntimeStatus>('/api/features/edition/unlock', {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export function lockCustomerEdition(): Promise<EditionRuntimeStatus> {
  return apiRequest<EditionRuntimeStatus>('/api/features/edition/lock', {
    method: 'POST',
    body: JSON.stringify({}),
  })
}
