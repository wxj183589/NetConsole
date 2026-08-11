// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../api/systemSettings'
import type { FeatureSetting, FeatureSettingsSnapshot } from '../../types/systemSettings'
import EditionFeatureProfilesView from './EditionFeatureProfilesView.vue'

vi.mock('../../api/systemSettings')
vi.mock('../../features', () => ({ loadRendererFeatures: vi.fn() }))
vi.mock('../../components/feedback/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true) }),
}))

const baseItem = (overrides: Partial<FeatureSetting>): FeatureSetting => ({
  feature_id: 'module.rail_transit',
  title: '轨道交通',
  group_id: 'rail_general',
  group_title: '轨道交通综合',
  parent_id: null,
  item_type: 'module',
  configuration_layer: 'business',
  scope: 'global',
  visible: true,
  enabled: true,
  inherited_visible: true,
  inherited_enabled: true,
  client_package: true,
  package_included: true,
  package_editable: true,
  internal_only: false,
  package_range: 'customer_internal',
  status: 'ENABLED',
  dependencies: [],
  delivery_dependencies: [],
  locked: false,
  lock_reason: '',
  overridden: false,
  ...overrides,
})

const items = (): FeatureSetting[] => [
  baseItem({}),
  baseItem({
    feature_id: 'module.train_online',
    title: '列车在线情况',
    parent_id: 'module.rail_transit',
    item_type: 'page',
    package_included: false,
    visible: false,
    enabled: false,
  }),
  baseItem({
    feature_id: 'ac.mesh_link.refresh',
    title: '刷新列车 Mesh-Link',
    parent_id: 'module.train_online',
    item_type: 'action',
    configuration_layer: 'operation',
    dependencies: ['internal.train_online_data'],
    delivery_dependencies: ['internal.train_online_data'],
  }),
  baseItem({
    feature_id: 'internal.train_online_data',
    title: '列车在线数据能力',
    group_id: 'foundation',
    group_title: '基础与桌面',
    item_type: 'capability',
    configuration_layer: 'technical',
    package_included: false,
    package_editable: false,
    visible: false,
    enabled: false,
    locked: true,
    lock_reason: '技术能力由业务功能和依赖自动带出',
  }),
]

const snapshot = (dependencyIssues = true): FeatureSettingsSnapshot => ({
  items: items(),
  target: 'customer',
  preview_active: false,
  configuration_name: '客户版交付配置',
  scope_label: '全局',
  inherited_profile: 'registry_defaults',
  applies_immediately: false,
  save_effect: '下次客户版打包时生效。',
  dependency_issues: dependencyIssues ? [{
    feature_id: 'ac.mesh_link.refresh',
    feature_title: '刷新列车 Mesh-Link',
    dependency_id: 'module.train_online',
    dependency_title: '列车在线情况',
    issue_type: 'delivery_parent_missing',
    message: 'ac.mesh_link.refresh 的交付父级 module.train_online 未纳入客户版',
    auto_fix: 'include_dependency_hidden',
  }] : [],
})

async function mounted() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/feature-flags', component: EditionFeatureProfilesView }],
  })
  await router.push('/feature-flags')
  await router.isReady()
  const wrapper = mount(EditionFeatureProfilesView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getFeatureSettings).mockResolvedValue(snapshot())
})

describe('EditionFeatureProfilesView', () => {
  it('uses one customer delivery state and keeps technical capabilities read-only', async () => {
    const wrapper = await mounted()

    expect(wrapper.text()).toContain('版本与功能交付')
    expect(wrapper.text()).toContain('客户版状态')
    expect(wrapper.text()).not.toContain('纳入客户版')
    expect(wrapper.find('[data-testid="customer-state-ac.mesh_link.refresh"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('技术能力')
    expect(wrapper.text()).toContain('只读')
    expect(wrapper.findAll('.feature-groups .el-collapse-item.is-active')).toHaveLength(0)
    wrapper.unmount()
  })

  it('groups dependency issues and auto-fixes only the current draft', async () => {
    const fixed = snapshot(false)
    fixed.items = fixed.items.map((item) => item.feature_id === 'module.train_online'
      ? { ...item, package_included: true, enabled: true, visible: false }
      : item)
    vi.mocked(api.autoFixFeatureSettings).mockResolvedValueOnce(fixed)
    const wrapper = await mounted()

    expect(wrapper.text()).toContain('1 组、1 项依赖问题')
    expect(wrapper.text()).toContain('被以下功能需要')
    await wrapper.find('[data-testid="auto-fix-dependencies"]').trigger('click')
    await flushPromises()

    expect(api.autoFixFeatureSettings).toHaveBeenCalledOnce()
    expect(api.saveFeatureSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('依赖问题，修复后')
    expect(wrapper.text()).toContain('项未保存')
    wrapper.unmount()
  })
})
