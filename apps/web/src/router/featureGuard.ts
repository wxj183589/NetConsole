import type { RouteLocationNormalized } from 'vue-router'

import { isFeatureEnabled, loadWebFeatures } from '../features'


export async function enforceRouteFeature(to: Pick<RouteLocationNormalized, 'meta'>) {
  const featureId = typeof to.meta.featureId === 'string' ? to.meta.featureId : ''
  if (!featureId) return true
  try {
    await loadWebFeatures()
  } catch {
    return { name: 'dashboard' }
  }
  return isFeatureEnabled(featureId) ? true : { name: 'dashboard' }
}
