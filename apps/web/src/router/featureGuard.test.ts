import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import { getWebFeatureStates } from '../api/features'
import { resetWebFeaturesForTest, setWebFeaturesForTest } from '../features'
import { enforceRouteFeature } from './featureGuard'

vi.mock('../api/features', () => ({ getWebFeatureStates: vi.fn() }))


describe('Web route Feature Gate', () => {
  beforeEach(() => resetWebFeaturesForTest())

  it('redirects a disabled direct route to Dashboard', async () => {
    setWebFeaturesForTest({ 'web.ac_fit_ap_resources': { visible: false, enabled: false } })
    const result = await enforceRouteFeature({ meta: { featureId: 'web.ac_fit_ap_resources' } } as Pick<RouteLocationNormalized, 'meta'>)
    expect(result).toEqual({ name: 'dashboard' })
  })

  it('allows routes with enabled or no feature', async () => {
    setWebFeaturesForTest({ 'web.job_center': { visible: true, enabled: true } })
    expect(await enforceRouteFeature({ meta: { featureId: 'web.job_center' } } as Pick<RouteLocationNormalized, 'meta'>)).toBe(true)
    expect(await enforceRouteFeature({ meta: {} } as Pick<RouteLocationNormalized, 'meta'>)).toBe(true)
  })

  it('fails closed when feature states cannot be loaded', async () => {
    vi.mocked(getWebFeatureStates).mockRejectedValueOnce(new Error('unavailable'))
    const result = await enforceRouteFeature({ meta: { featureId: 'web.job_center' } } as Pick<RouteLocationNormalized, 'meta'>)
    expect(result).toEqual({ name: 'dashboard' })
  })
})
