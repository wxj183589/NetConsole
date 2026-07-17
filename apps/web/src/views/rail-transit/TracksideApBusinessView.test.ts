import { describe, expect, it } from 'vitest'

import source from './TracksideApBusinessView.vue?raw'

describe('trackside AP business view', () => {
  it('exposes the Qt query, scoped update, recovery and unified task-window boundaries', () => {
    for (const contract of [
      'listTracksideApBusiness', 'startTracksideApUpdate', 'recoverTracksideApTasks',
      "openTaskWindow({ module: 'rail'",
      '更新全部光衰', '更新站点', '更新 AP', '仅光衰异常', '当前轨旁 AP',
      "isFeatureEnabled('web.rail_trackside_ap_business_update')",
    ]) expect(source).toContain(contract)
    expect(source).not.toContain('cancelTracksideApTask')
    expect(source).not.toContain('READ ONLY')
    expect(source).not.toContain('只读')
  })
})
