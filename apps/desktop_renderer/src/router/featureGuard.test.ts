// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import { getRendererFeatureStates } from '../api/features'
import { resetRendererFeaturesForTest, setRendererFeaturesForTest } from '../features'
import { enforceRouteFeature } from './featureGuard'

vi.mock('../api/features', () => ({ getRendererFeatureStates: vi.fn() }))


describe('Web route Feature Gate', () => {
  beforeEach(() => resetRendererFeaturesForTest())

  it('redirects a disabled direct route to Dashboard', async () => {
    setRendererFeaturesForTest({ 'module.fit_ap': { visible: false, enabled: false } })
    const result = await enforceRouteFeature({ meta: { featureId: 'module.fit_ap' } } as Pick<RouteLocationNormalized, 'meta'>)
    expect(result).toEqual({ name: 'dashboard' })
  })

  it('allows routes with enabled or no feature', async () => {
    setRendererFeaturesForTest({ 'module.task_center': { visible: true, enabled: true } })
    expect(await enforceRouteFeature({ meta: { featureId: 'module.task_center' } } as Pick<RouteLocationNormalized, 'meta'>)).toBe(true)
    expect(await enforceRouteFeature({ meta: {} } as Pick<RouteLocationNormalized, 'meta'>)).toBe(true)
  })

  it('fails closed when feature states cannot be loaded', async () => {
    vi.mocked(getRendererFeatureStates).mockRejectedValueOnce(new Error('unavailable'))
    const result = await enforceRouteFeature({ meta: { featureId: 'module.task_center' } } as Pick<RouteLocationNormalized, 'meta'>)
    expect(result).toEqual({ name: 'dashboard' })
  })

  it('rejects the tool collection in browser mode before evaluating its feature', async () => {
    Reflect.deleteProperty(window, 'netconsoleDesktop')
    expect(await enforceRouteFeature({
      meta: { featureId: 'module.tools', desktopOnly: true },
    } as Pick<RouteLocationNormalized, 'meta'>)).toEqual({ name: 'dashboard' })
  })
})
