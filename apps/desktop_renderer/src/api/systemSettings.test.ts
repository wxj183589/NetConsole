import { afterEach, describe, expect, it, vi } from 'vitest'

import type { FeatureSetting } from '../types/systemSettings'
import { getNetworkComponents, saveFeatureSettings, saveNetworkComponent } from './systemSettings'

const feature: FeatureSetting = {
  feature_id: 'module.agent',
  title: 'Agent 管理',
  group_id: 'tasks',
  group_title: '任务与 Agent',
  parent_id: null,
  item_type: 'page',
  configuration_layer: 'business',
  scope: 'global',
  visible: false,
  enabled: true,
  inherited_visible: true,
  inherited_enabled: true,
  client_package: true,
  internal_only: false,
  package_range: 'customer_internal',
  status: 'ENABLED',
  dependencies: ['internal.task_center'],
  delivery_dependencies: ['internal.task_center'],
  locked: false,
  lock_reason: '',
  overridden: true,
}

describe('system settings feature API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('submits template state and customer delivery fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [feature],
        preview_active: false,
        configuration_name: '当前实例运行配置',
        scope_label: '全局',
        inherited_profile: 'full',
        dependency_issues: [],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await saveFeatureSettings([feature], 'customer')

    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toEqual({
      target: 'customer',
      items: [{
        feature_id: 'module.agent',
        visible: false,
        enabled: true,
      }],
      confirmed: true,
    })
  })
})

describe('network component API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads and saves component mode through the dedicated endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ version: 'v2', components: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await getNetworkComponents()
    await saveNetworkComponent('fping', 'builtin', '', 'v1')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings/network-components')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/settings/network-components/fping')
    expect(JSON.parse(String(fetchMock.mock.calls[1][1].body))).toEqual({
      mode: 'builtin', custom_path: '', expected_version: 'v1',
    })
  })
})
