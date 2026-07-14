import { describe, expect, it } from 'vitest'

import source from './AppLayout.vue?raw'

describe('App layout Feature Gate navigation', () => {
  it('hides each new Web page navigation entry through the shared feature state', () => {
    for (const featureId of [
      'web.device_management',
      'web.config_collection',
      'web.file_management',
      'web.network_tools',
    ]) {
      expect(source).toContain(`v-if="isFeatureVisible('${featureId}')"`)
      expect(source).toContain(`:disabled="!isFeatureEnabled('${featureId}')"`)
    }
  })

  it('keeps the existing traffic-test entry independent from the new overview switch', () => {
    expect(source).toContain('<el-sub-menu index="/network-tools">')
    expect(source).toContain('<el-menu-item index="/network-tools/traffic">流量测试</el-menu-item>')
  })
})
