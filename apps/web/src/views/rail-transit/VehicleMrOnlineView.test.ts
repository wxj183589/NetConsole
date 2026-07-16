import { describe, expect, it } from 'vitest'

import source from './VehicleMrOnlineView.vue?raw'

describe('vehicle MR online view', () => {
  it('exposes persisted CT/TC state and real refresh and mapping actions', () => {
    expect(source).toContain('MR-CT 当前 AP')
    expect(source).toContain('MR-TC 当前 AP')
    expect(source).toContain('refreshVehicleMrOnline')
    expect(source).toContain('refreshVehicleMrApMapping')
    expect(source).toContain('saveVehicleMrMappings')
    expect(source).toContain('取消任务')
    expect(source).toContain('恢复任务')
    expect(source).not.toMatch(/READ ONLY|只读|迁移/)
  })
})
