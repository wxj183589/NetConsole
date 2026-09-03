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
    siteA.work_scope_status = 'all'
    siteA.sort_by = 'primary_address'
    siteA.sort_order = 'desc'
    siteA.page = 3
    siteA.page_size = 100
    store.save('site-a', siteA)

    expect(store.activateSite('site-b')).toEqual(DEVICE_MANAGEMENT_QUERY_DEFAULTS)
    expect(store.activateSite('site-a')).toMatchObject(siteA)
    expect(store.read('site-a')).not.toHaveProperty('selectedUuids')
  })
})
