// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import Panel from './EngineeringContextPanel.vue'
import type { DeviceEngineeringContext } from '../../types/deviceManagement'
const mocks = vi.hoisted(() => ({ push: vi.fn(), allowed: true }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('../../features', () => ({ isFeatureEnabled: () => mocks.allowed }))
const context: DeviceEngineeringContext = { available: true, affiliation_status: 'associated', line_name: 'L', node_uid: 'node:stable', node_type: 'station', node_code: '01', node_name: 'Same name', role: 'MR-CT', project_names: [], service_stations: [], source: 'rail_infrastructure_query', device_uuid: 'uuid:stable', station_id: 'station:stable' }
function render(value?: DeviceEngineeringContext, historical = false) {
  return mount(Panel, { props: { context: value, historical }, global: { stubs: { ElTag: { template: '<span><slot /></span>' }, ElTooltip: { template: '<span><slot /></span>' }, ElButton: { template: '<button><slot /></button>' } } } })
}
beforeEach(() => { mocks.push.mockReset(); mocks.allowed = true })
describe('shared engineering context', () => {
  it('navigates with stable IDs and lets the destination validate the object', async () => {
    const wrapper = render(context)
    await wrapper.findAll('button').find(b => b.text() === 'Same name')!.trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'rail-transit-base-data', query: { tab: 'overview', node_uid: 'node:stable' } })
  })
  it('keeps event-time context separate and does not navigate history as current', () => {
    const wrapper = render({ ...context, affiliation_status: 'historical', effective_at: '2026-11-15' }, true)
    expect(wrapper.text()).toContain('2026-11-15')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
  it.each(['unavailable', 'stale', 'conflict', 'unconfirmed', 'not_found'] as const)('exposes %s without showing an association as normal', status => {
    const wrapper = render({ ...context, available: false, affiliation_status: status })
    expect(wrapper.findAll('button')).toHaveLength(0)
    expect(wrapper.find('dl').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('未关联')
  })
  it('honors module feature permissions', () => {
    mocks.allowed = false
    expect(render(context).findAll('button')).toHaveLength(0)
  })
  it('treats a missing response as unavailable', () => {
    expect(render().text()).toContain('上下文不可用')
  })
})
