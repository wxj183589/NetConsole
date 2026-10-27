import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { DEVICE_MANAGEMENT_QUERY_DEFAULTS, useDeviceManagementQueryStore } from './deviceManagement'

describe('device management query state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('restores query state per site without persisting selection', () => {
    const store = useDeviceManagementQueryStore()
    const siteA = store.activateSite('site-a')
    siteA.search = 'AC1'
    siteA.group = '10'
    siteA.group_values = ['10', '__ungrouped__']
    siteA.vendor_values = ['H3C', 'ZTE']
    siteA.connection_status_values = ['REACHABLE', 'ERROR']
    siteA.work_scope_status_values = ['included', 'excluded']
    siteA.work_scope_status = 'all'
    siteA.sort_by = 'primary_address'
    siteA.sort_order = 'desc'
    siteA.page = 3
    siteA.page_size = 100
    store.save('site-a', siteA)

    expect(store.activateSite('site-b')).toEqual(DEVICE_MANAGEMENT_QUERY_DEFAULTS)
    expect(store.activateSite('site-a')).toMatchObject(siteA)
    const active = store.activateSite('site-a')
    active.group_values.push('another-site')
    active.vendor_values.pop()
    active.connection_status_values.pop()
    expect(store.read('site-a')?.group_values).toEqual(['10', '__ungrouped__'])
    expect(store.read('site-a')?.vendor_values).toEqual(['H3C', 'ZTE'])
    expect(store.read('site-a')?.connection_status_values).toEqual(['REACHABLE', 'ERROR'])
    expect(store.read('site-b')?.work_scope_status_values).toEqual(['included'])
    expect(store.read('site-a')).not.toHaveProperty('selectedUuids')
  })
})
