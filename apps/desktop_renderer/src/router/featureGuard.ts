import type { RouteLocationNormalized } from 'vue-router'

import { isFeatureEnabled, loadRendererFeatures } from '../features'


export async function enforceRouteFeature(to: Pick<RouteLocationNormalized, 'meta'>) {
  if (to.meta.desktopOnly === true && !(typeof window !== 'undefined' && window.netconsoleDesktop)) return { name: 'dashboard' }
  const featureId = typeof to.meta.featureId === 'string' ? to.meta.featureId : ''
  if (!featureId) return true
  try {
    await loadRendererFeatures()
  } catch {
    return { name: 'dashboard' }
  }
  return isFeatureEnabled(featureId) ? true : { name: 'dashboard' }
}
