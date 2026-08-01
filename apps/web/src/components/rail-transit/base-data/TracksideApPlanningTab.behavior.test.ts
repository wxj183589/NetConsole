// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'

import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'
import TracksideApPlanningTab from './TracksideApPlanningTab.vue'
import { reconcileTracksideApPlans, type PlanningStation } from './tracksideApPlanDraft'

const ButtonStub = defineComponent({
  props: { disabled: Boolean },
  emits: ['click'],
  template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
})

const stubs = {
  ElButton: ButtonStub,
  ElAlert: true,
  ElInput: true,
  ElInputNumber: true,
  ElOption: true,
  ElSelect: true,
  ElTag: true,
  NcDataTable: defineComponent({ template: '<div class="data-table"><slot /></div>' }),
}

function station(id: string, name: string, order: number, overrides: Partial<PlanningStation> = {}): PlanningStation {
  return {
    id,
    name,
    sort_order: order,
    enabled: true,
    node_type: 'station',
    participates_in_direction: true,
    ...overrides,
  }
}

function plan(stationId: string, name: string): TracksideApPlanRow {
  return {
    station_id: stationId,
    station_name: name,
    sequence_no: 1,
    planned_ap_count: 6,
    management_vlan: 120,
    remark: '保留值',
    relation_status: 'resolved',
    candidate_station_ids: [],
  }
}

describe('trackside AP planning controlled draft', () => {
  it('reconciles by station_id and preserves user planning values after a rename', () => {
    const rows = reconcileTracksideApPlans(
      [plan('station:1', '旧站名')],
      [station('station:1', '新站名', 9)],
      [],
    )

    expect(rows).toEqual([expect.objectContaining({
      station_id: 'station:1',
      station_name: '新站名',
      sequence_no: 9,
      planned_ap_count: 6,
      management_vlan: 120,
      remark: '保留值',
      relation_status: 'resolved',
    })])
  })

  it('retains a missing legacy row as stale and only appends eligible generated stations', () => {
    const rows = reconcileTracksideApPlans(
      [plan('station:legacy', '历史站')],
      [
        station('station:1', '一站', 1),
        station('station:2', '停车场', 2, { node_type: 'parking_lot' }),
        station('station:3', '未启用站', 3, { enabled: false }),
      ],
      ['station:1', 'station:2', 'station:3'],
    )

    expect(rows).toHaveLength(2)
    expect(rows.find((row) => row.station_id === 'station:legacy')).toEqual(
      expect.objectContaining({ relation_status: 'stale' }),
    )
    expect(rows.find((row) => row.station_id === 'station:1')).toEqual(expect.objectContaining({
      station_id: 'station:1',
      planned_ap_count: 0,
      management_vlan: null,
      remark: '',
    }))
  })

  it('immediately creates eleven stable-ID rows for eleven generated ordinary stations', () => {
    const stations = Array.from({ length: 11 }, (_, index) =>
      station(`station:${index + 1}`, `验收站${index + 1}`, index + 1))
    const rows = reconcileTracksideApPlans([], stations, stations.map((item) => item.id))

    expect(rows).toHaveLength(11)
    expect(rows.every((row) => row.station_id.startsWith('station:'))).toBe(true)
    expect(rows.every((row) => row.relation_status === 'resolved')).toBe(true)
  })

  it('does not merge two formal stations that share the same display name', () => {
    const rows = reconcileTracksideApPlans(
      [plan('station:1', '同名站'), plan('station:2', '同名站')],
      [station('station:1', '同名站', 1), station('station:2', '同名站', 2)],
      [],
    )

    expect(rows.map((row) => row.station_id)).toEqual(['station:1', 'station:2'])
  })

  it('publishes a new row through v-model without owning a save action', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        modelValue: [],
        stations: [station('station:1', '一站', 1)],
        readonly: false,
        saving: false,
      },
      global: { stubs },
    })

    const addButton = wrapper.findAll('button').find((button) => button.text().includes('新增规划行'))
    expect(addButton).toBeDefined()
    await addButton!.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]?.[0]).toEqual([
      expect.objectContaining({ station_id: 'station:1', station_name: '一站' }),
    ])
    expect(wrapper.emitted('validation-change')?.[0]).toEqual([true, []])
    expect(wrapper.text()).not.toContain('保存')
  })

  it('disables draft actions in read-only mode and delegates station generation', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: { modelValue: [], stations: [], readonly: true, saving: false },
      global: { stubs },
    })
    const generate = wrapper.findAll('button').find((button) => button.text().includes('从设备管理生成站点'))!
    expect(generate.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ readonly: false })
    await generate.trigger('click')
    expect(wrapper.emitted('request-generate-stations')).toHaveLength(1)
  })
})
