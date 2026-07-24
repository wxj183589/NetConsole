import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeatureSetting } from '../types/systemSettings'
import { saveFeatureSettings } from './systemSettings'

const feature: FeatureSetting = {
  feature_id: 'web.agent_management',
  title: 'Agent 管理',
  group_id: 'tasks',
  group_title: '任务与 Agent',
  scope: 'global',
  visible: false,
  enabled: true,
  inherited_visible: true,
  inherited_enabled: true,
  client_package: true,
  internal_only: false,
  package_range: 'customer_internal',
  status: 'ENABLED',
  dependencies: ['web.job_center'],
  locked: false,
  lock_reason: '',
  overridden: true,
}

describe('system settings feature API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('submits only runtime state fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [feature],
        preview_active: false,
        configuration_name: '当前实例运行配置',
        scope_label: '全局',
        inherited_profile: 'full',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await saveFeatureSettings([feature])

    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      items: [{
        feature_id: 'web.agent_management',
        visible: false,
        enabled: true,
      }],
      confirmed: true,
    })
  })
})
