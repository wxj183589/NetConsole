// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import View from './RailTransitInfrastructureView.vue'
import { useRailInfrastructureStore } from '../../stores/railInfrastructure'
import { useRailTransitBaseDataStore } from '../../stores/railTransitBaseData'
import { setActiveSiteContext } from '../../stores/siteContext'
import { navigationRegistry, visibleNavigation } from '../../navigation/registry'
import { setRendererFeaturesForTest, isFeatureVisible } from '../../features'
import { enforceRouteFeature } from '../../router/featureGuard'
import { appRoutes } from '../../router/routes'

const api = vi.hoisted(() => ({ getInfrastructure: vi.fn(), getInfrastructureSwitchAps: vi.fn() }))
vi.mock('../../api/railInfrastructure', () => api)
const snapshot = { site_id:'demo',site_name:'Test',line_name:'Line',nodes:[{uid:'station-1',kind:'station',name:'Station',code:'01',aliases:[],projects:[],devices:[],sections:[],ac_service_stations:[]}],unassociated_devices:[],device_count:0,unassociated_device_count:0,unresolved_binding_count:0,schema_available:true }
beforeEach(() => { setActivePinia(createPinia()); setActiveSiteContext({site_id:'demo'}); api.getInfrastructure.mockResolvedValue(structuredClone(snapshot)) })
describe('independent rail modules', () => {
  it('has sibling navigation and separate feature-controlled routes', async () => {
    const rail = navigationRegistry.find(n => n.navigation_id === 'rail')!
    expect(rail.children.slice(0,2).map(n=>n.navigation_id)).toEqual(['rail.infrastructure','rail.base-data'])
    const routes = appRoutes[0]!.children!
    const base = routes.find(r=>r.name==='rail-transit-base-data')!, infra = routes.find(r=>r.name==='rail-transit-infrastructure')!
    expect(base.component).not.toBe(infra.component)
    for (const allowed of ['module.rail_base_data','module.rail_infrastructure']) {
      setRendererFeaturesForTest({ [allowed]:{visible:true,enabled:true}, 'module.rail_transit':{visible:true,enabled:true} })
      expect(await enforceRouteFeature({ meta: (allowed==='module.rail_base_data'?base:infra).meta! })).toBe(true)
      expect(await enforceRouteFeature({ meta: (allowed==='module.rail_base_data'?infra:base).meta! })).toEqual({name:'dashboard'})
      const entries = visibleNavigation(isFeatureVisible).find(n=>n.navigation_id==='rail')!.children
      expect(entries.some(n=>n.feature_id===allowed)).toBe(true)
      expect(entries.some(n=>n.feature_id===(allowed==='module.rail_base_data'?'module.rail_infrastructure':'module.rail_base_data'))).toBe(false)
    }
  })
  it('validates a node deep link and keeps infrastructure selection separate from base data filters', async () => {
    const router = createRouter({history:createMemoryHistory(),routes:[{path:'/rail-transit/infrastructure',component:View}]})
    await router.push('/rail-transit/infrastructure?node_uid=station-1'); await router.isReady()
    const base = useRailTransitBaseDataStore(), infra = useRailInfrastructureStore()
    base.apFilters.query='base-filter'
    const wrapper = mount(View,{global:{plugins:[router],stubs:{RelationshipEditor:true,DeviceDetailPanel:true,ElButton:true,ElAlert:true}}})
    await flushPromises()
    expect(wrapper.find('.organization').exists()).toBe(true)
    expect(wrapper.find('.selected-node').text()).toContain('Station')
    expect(wrapper.find('.node-facts').text()).toContain('01')
    expect(wrapper.find('.el-tabs').exists()).toBe(false)
    await wrapper.get('input[type=search]').setValue('Station')
    expect(infra.search).toBe('Station'); expect(base.apFilters.query).toBe('base-filter')
    await router.push('/rail-transit/infrastructure?node_uid=missing'); await flushPromises()
    expect(infra.error).toContain('不存在')
    wrapper.unmount()
  })
})
