// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DeviceDetailPanel from '../../device-detail/DeviceDetailPanel.vue'
import InfrastructureWorkbench from './InfrastructureWorkbench.vue'
import type { Infrastructure } from '../../../api/railInfrastructure'
import { setRendererFeaturesForTest } from '../../../features'

const api = vi.hoisted(() => ({ getInfrastructure: vi.fn(), getInfrastructureSwitchAps: vi.fn() }))
vi.mock('../../../api/railInfrastructure', () => api)
vi.mock('../../../api/deviceManagement', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../../api/deviceManagement')>(),
  getDeviceOverview: vi.fn(async () => ({ model: '', engineering_context: {} })),
}))

const snapshot: Infrastructure = {
  site_id: 'demo', site_name: '试验局点', line_name: '试验线', schema_available: true, device_count: 2,
  unassociated_device_count: 1, unresolved_binding_count: 1, unassociated_devices: [],
  nodes: [{
    uid: 'station-1', kind: 'station', code: '0101', name: '大道站', source: 'engineering', station: null,
    aliases: [{ name: '旧东站', name_type: 'historical', source: 'fixture', valid_from: null, valid_to: null }],
    projects: [{ project_id: 'p1', name: '初建', stage: '一期' }, { project_id: 'p2', name: '扩建', stage: '二期' }],
    sections: [], ac_service_stations: [],
    devices: [{ device_uuid: 'sw-1', name: '交换机 A', device_type: 'switch', device_role: 'switch', role: '车站交换机', source: 'engineering', section_uid: null }],
  }],
}

describe('Infrastructure workbench', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setRendererFeaturesForTest({ 'module.trackside_ap': {visible:true,enabled:true}, 'module.devices': {visible:true,enabled:true} })
    api.getInfrastructure.mockResolvedValue(snapshot)
    api.getInfrastructureSwitchAps.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 })
  })

  it('searches historical names, shows multiple projects, and uses the bound UUID in device details', async () => {
    const wrapper = mount(InfrastructureWorkbench, {
      props: { siteId: 'demo' },
      global: { stubs: { DeviceDetailPanel: true, RelationshipEditor: true, ElAlert: true, ElButton: true }, directives: { loading: () => {} } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('车辆段与停车场')
    expect(wrapper.text()).toContain('待配置')
    await wrapper.get('input[type=search]').setValue('旧东站')
    await wrapper.get('.organization .tree-node').trigger('click')
    expect(wrapper.text()).toContain('0101 大道站')
    expect(wrapper.text()).toContain('一期 初建、二期 扩建')
    await wrapper.get('.device-link').trigger('click')
    await flushPromises()
    expect(wrapper.getComponent(DeviceDetailPanel).props('deviceUuid')).toBe('sw-1')
    expect(api.getInfrastructureSwitchAps).toHaveBeenCalledWith('demo', 'sw-1', 1, expect.any(AbortSignal))
    expect(wrapper.text()).toContain('暂无经 LLDP 与 AP Identity 确认的接入')
    expect(wrapper.get('.workbench-columns').attributes('data-compact-pane')).toBe('device')
    await wrapper.findAll('.compact-switch button')[0].trigger('click')
    expect(wrapper.get('.workbench-columns').attributes('data-compact-pane')).toBe('node')
    // Narrow-layout switching retains the selected device and its existing panel.
    expect(wrapper.getComponent(DeviceDetailPanel).props('deviceUuid')).toBe('sw-1')
    await wrapper.get('.tree-root').trigger('click')
    expect(wrapper.findComponent(DeviceDetailPanel).exists()).toBe(false)
    expect(wrapper.get('.compact-switch button:last-child').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('keeps incomplete AP queries distinct from zero and displays identity conflicts from the authority', async () => {
    api.getInfrastructureSwitchAps.mockResolvedValue({items:[{row_id:'row',ap_uuid:'ap',ap_name:'AP conflict',interface_name:'GE1',link_status:'unknown',identity_match_status:'conflict',primary_reason_label:'身份冲突'}],total:99,page:1,page_size:50,partial_data:true})
    const wrapper = mount(InfrastructureWorkbench, {props:{siteId:'demo'},global:{stubs:{DeviceDetailPanel:true,RelationshipEditor:true,ElAlert:true,ElButton:true},directives:{loading:()=>{}}}})
    await flushPromises()
    await wrapper.get('.organization .tree-node').trigger('click')
    await flushPromises()
    await wrapper.get('.device-link').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('关联查询不完整，数量未确认')
    expect(wrapper.get('[aria-label="交换机下挂 AP"] h4').text()).not.toContain('99')
    await wrapper.get('.ap-links button').trigger('click')
    expect(wrapper.get('.ap-engineering-detail').text()).toContain('身份冲突')
    expect(wrapper.find('.device-detail-panel').exists()).toBe(false)
    wrapper.unmount()
  })
})
