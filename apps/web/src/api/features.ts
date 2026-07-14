import { apiRequest } from './client'

export interface WebFeatureState {
  feature_id: string
  visible: boolean
  enabled: boolean
}

export async function getWebFeatureStates(): Promise<WebFeatureState[]> {
  const response = await apiRequest<{ items: WebFeatureState[] }>('/api/features')
  return response.items
}
