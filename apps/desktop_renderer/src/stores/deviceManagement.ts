import { reactive, ref } from 'vue'
import { defineStore } from 'pinia'

import type { DeviceManagementQueryState } from '../types/deviceManagement'

export const DEVICE_MANAGEMENT_QUERY_DEFAULTS: DeviceManagementQueryState = {
  search: '',
  group: '',
  vendor: '',
  device_type: '',
  connection_status: '',
  project_phase: 'all',
  work_scope_status: 'included',
  sort_by: 'default',
  sort_order: 'asc',
  page: 1,
  page_size: 50,
}

function copyState(state: DeviceManagementQueryState): DeviceManagementQueryState {
  return { ...state }
}

export const useDeviceManagementQueryStore = defineStore('device-management-query', () => {
  const statesBySite = reactive<Record<string, DeviceManagementQueryState>>({})
  const activeSiteId = ref('')

  function ensure(siteId: string): DeviceManagementQueryState {
    const key = String(siteId || '').trim()
    if (!key) throw new Error('设备管理状态缺少局点标识')
    if (!statesBySite[key]) statesBySite[key] = copyState(DEVICE_MANAGEMENT_QUERY_DEFAULTS)
    return statesBySite[key]
  }

  function activateSite(siteId: string): DeviceManagementQueryState {
    const key = String(siteId || '').trim()
    const state = ensure(key)
    activeSiteId.value = key
    return copyState(state)
  }

  function save(siteId: string, state: DeviceManagementQueryState): void {
    Object.assign(ensure(siteId), copyState(state))
  }

  function read(siteId: string): DeviceManagementQueryState {
    return copyState(ensure(siteId))
  }

  return { statesBySite, activeSiteId, activateSite, save, read }
})
