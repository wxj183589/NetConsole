import { apiRequest } from './client'

export interface RendererFeatureState {
  feature_id: string
  visible: boolean
  enabled: boolean
}

export interface RendererFeatureRequestOptions {
  fresh?: boolean
}

export async function getRendererFeatureStates(
  options: RendererFeatureRequestOptions = {},
): Promise<RendererFeatureState[]> {
  const response = await apiRequest<{ items: RendererFeatureState[] }>('/api/features', {
    coalesce: options.fresh !== true,
  })
  return response.items
}
