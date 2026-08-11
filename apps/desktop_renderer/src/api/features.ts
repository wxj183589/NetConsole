import { apiRequest } from './client'

export interface RendererFeatureState {
  feature_id: string
  visible: boolean
  enabled: boolean
}

export async function getRendererFeatureStates(): Promise<RendererFeatureState[]> {
  const response = await apiRequest<{ items: RendererFeatureState[] }>('/api/features')
  return response.items
}
