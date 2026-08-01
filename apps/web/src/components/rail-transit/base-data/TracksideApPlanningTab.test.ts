import { describe, expect, it } from 'vitest'

import source from './TracksideApPlanningTab.vue?raw'

describe('trackside AP planning base-data tab source contract', () => {
  it('is a controlled editor with stable-ID association and no persistence ownership', () => {
    for (const contract of [
      'modelValue: TracksideApPlanRow[]',
      'stations: PlanningStation[]',
      'readonly: boolean',
      'saving: boolean',
      "'update:modelValue'",
      "'validation-change'",
      "'request-generate-stations'",
      'station_id',
      '待关联历史规划',
      'overflow-x: auto',
      'route-key="/rail-transit/base-data"',
    ]) expect(source).toContain(contract)

    for (const forbidden of [
      'getTracksideApPlan',
      'saveTracksideApPlan',
      'previewTracksideApPlan',
      'useTaskStore',
      'locked',
      '解锁',
      'setTimeout',
      'nextTick',
      'allow-create',
      '<el-table',
    ]) expect(source).not.toContain(forbidden)
  })
})
