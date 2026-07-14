import { describe, expect, it } from 'vitest'

import source from './index.ts?raw'

describe('Web route Feature Gate', () => {
  it('attaches page feature ids and redirects hidden pages', () => {
    for (const featureId of [
      'web.device_management',
      'web.config_collection',
      'web.file_management',
      'web.network_tools',
    ]) {
      expect(source).toContain(`featureId: '${featureId}'`)
    }
    expect(source).toContain("return isFeatureEnabled(featureId) ? true : { name: 'dashboard' }")
  })
})
