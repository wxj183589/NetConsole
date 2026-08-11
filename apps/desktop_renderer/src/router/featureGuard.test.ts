// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import { getRendererFeatureStates } from '../api/features'
import { resetRendererFeaturesForTest, setRendererFeaturesForTest } from '../features'
import { enforceRouteFeature } from './featureGuard'

vi.mock('../api/features', () => ({ getRendererFeatureStates: vi.fn() }))


describe('Desktop Renderer route Feature Gate', () => {
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

  it('rejects an internal route omitted from the packaged feature snapshot', async () => {
    vi.mocked(getRendererFeatureStates).mockResolvedValueOnce([
      { feature_id: 'module.system_settings', visible: true, enabled: true },
    ])

    expect(await enforceRouteFeature({
      meta: { featureId: 'internal.feature_switch' },
    } as Pick<RouteLocationNormalized, 'meta'>)).toEqual({ name: 'dashboard' })
  })

  it('allows an internal route explicitly returned by the source development backend', async () => {
    vi.mocked(getRendererFeatureStates).mockResolvedValueOnce([
      { feature_id: 'internal.feature_switch', visible: true, enabled: true },
    ])

    expect(await enforceRouteFeature({
      meta: { featureId: 'internal.feature_switch' },
    } as Pick<RouteLocationNormalized, 'meta'>)).toBe(true)
  })

  it('rejects the tool collection in browser mode before evaluating its feature', async () => {
    Reflect.deleteProperty(window, 'netconsoleDesktop')
    expect(await enforceRouteFeature({
      meta: { featureId: 'module.tools', desktopOnly: true },
    } as Pick<RouteLocationNormalized, 'meta'>)).toEqual({ name: 'dashboard' })
  })
})
