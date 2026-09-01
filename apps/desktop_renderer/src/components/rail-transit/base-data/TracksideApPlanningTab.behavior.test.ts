// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, ref, watch } from 'vue'

import type { TracksideApPlanRow } from '../../../types/tracksideApBusiness'
import TracksideApPlanningTab from './TracksideApPlanningTab.vue'
import {
  participatesInMainlineTopology,
  reconcileTracksideApPlans,
  type PlanningStation,
} from './tracksideApPlanDraft'

const ButtonStub = defineComponent({
  props: { disabled: Boolean },
  emits: ['click'],
  template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
})

const InputNumberStub = defineComponent({
  props: {
    modelValue: { type: Number, default: null },
    disabled: Boolean,
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const draft = ref(props.modelValue == null ? '' : String(props.modelValue))
    watch(() => props.modelValue, (value) => {
      draft.value = value == null ? '' : String(value)
    })
    return {
      draft,
      publish: (value: string) => {
        draft.value = value
        emit('update:modelValue', value === '' ? undefined : Number(value))
      },
    }
  },
  template: '<input class="input-number" type="number" :value="draft" :disabled="disabled" @input="publish($event.target.value)">',
})

const DataTableStub = defineComponent({
  props: { data: { type: Array, default: () => [] } },
  setup(props, { slots }) {
    return () => h('div', { class: 'data-table' }, (props.data as TracksideApPlanRow[]).map((row, index) =>
      h('div', { class: 'table-row', key: `${row.station_id}-${index}`, 'data-station-id': row.station_id }, [
        h('div', { class: 'sequence-cell' }, slots['cell-sequence_no']?.({ row, $index: index })),
        h('div', { class: 'station-cell' }, [
          h('span', { class: 'station-name' }, row.station_name),
          slots['cell-station_name']?.({ row, $index: index }),
        ]),
        h('div', { class: 'count-cell' }, slots['cell-planned_ap_count']?.({ row, $index: index })),
        h('div', { class: 'vlan-cell' }, slots['cell-management_vlan']?.({ row, $index: index })),
      ])))
  },
})

const stubs = {
  ElButton: ButtonStub,
  ElAlert: true,
  ElInput: true,
  ElInputNumber: InputNumberStub,
  ElOption: true,
  ElSelect: true,
  ElTag: true,
  NcDataTable: DataTableStub,
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

function plan(stationId: string, name: string, overrides: Partial<TracksideApPlanRow> = {}): TracksideApPlanRow {
  return {
    station_id: stationId,
    station_name: name,
    sequence_no: 1,
    planned_ap_count: 6,
    management_vlan: 120,
    remark: '保留值',
    relation_status: 'resolved',
    candidate_station_ids: [],
    ...overrides,
  }
}

describe('trackside AP planning controlled draft', () => {
  it('mounts with the real NcDataTable column contract', () => {
    const { NcDataTable: _ncDataTable, ...controlStubs } = stubs
    const wrapper = mount(TracksideApPlanningTab, {
      props: {
        modelValue: [plan('station:1', '一站')],
        stations: [station('station:1', '一站', 1)],
        editing: false,
        readonly: false,
        saving: false,
      },
      global: { stubs: controlStubs },
    })

    expect(wrapper.text()).toContain('AP 规划')
    expect(wrapper.find('.planning-tab').exists()).toBe(true)
  })

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

    expect(rows).toHaveLength(3)
    expect(rows.find((row) => row.station_id === 'station:legacy')).toEqual(
      expect.objectContaining({ relation_status: 'stale' }),
    )
    expect(rows.find((row) => row.station_id === 'station:1')).toEqual(expect.objectContaining({
      station_id: 'station:1',
      planned_ap_count: 0,
      management_vlan: null,
      remark: '',
    }))
    expect(rows.find((row) => row.station_id === 'station:2')).toEqual(expect.objectContaining({
      station_name: '停车场',
      relation_status: 'resolved',
    }))
  })

  it('creates eleven planning rows for ten ordinary stations and one depot without changing topology eligibility', () => {
    const stations = [
      ...Array.from({ length: 10 }, (_, index) =>
        station(`station:${index + 1}`, `验收站${index + 1}`, index + 1)),
      station('station:depot', '车辆段', 0, {
        node_type: 'depot',
        sort_order: null,
        participates_in_direction: false,
      }),
    ]
    const rows = reconcileTracksideApPlans([], stations, stations.map((item) => item.id))

    expect(rows).toHaveLength(11)
    expect(new Set(rows.map((row) => row.station_id)).size).toBe(11)
    expect(rows.every((row) => row.relation_status === 'resolved')).toBe(true)
    expect(rows.at(-1)).toEqual(expect.objectContaining({
      station_id: 'station:depot',
      station_name: '车辆段',
      planned_ap_count: 0,
      management_vlan: null,
    }))
    expect(stations.at(-1)?.node_type).toBe('depot')
    expect(stations.at(-1)?.participates_in_direction).toBe(false)
    expect(participatesInMainlineTopology(stations.at(-1)!)).toBe(false)
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
        editing: true,
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

  it('keeps a typed VLAN after focus moves to another row', async () => {
    const draft = ref([
      plan('station:1', '一站'),
      plan('station:2', '二站'),
    ])
    draft.value[0].management_vlan = null
    draft.value[1].management_vlan = null
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({
        draft,
        stations: [station('station:1', '一站', 1), station('station:2', '二站', 2)],
      }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })
    const inputs = wrapper.findAll('.vlan-cell input')

    await inputs[0].setValue('921')
    await inputs[1].trigger('focus')
    await nextTick()

    expect(draft.value[0].management_vlan).toBe(921)
    expect((wrapper.findAll('.vlan-cell input')[0].element as HTMLInputElement).value).toBe('921')
  })

  it('pastes multiple Excel VLAN rows and keeps empty VLAN cells nullable', async () => {
    const draft = ref([plan('station:1', '一站'), plan('station:2', '二站')])
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations: [station('station:1', '一站', 1), station('station:2', '二站', 2)] }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })
    const firstVlan = wrapper.findAll('.vlan-cell input')[0]

    await firstVlan.trigger('paste', {
      clipboardData: { getData: () => '921\n\t' },
    })
    await nextTick()

    expect(draft.value.map((row) => row.management_vlan)).toEqual([921, null])
  })

  it('pastes consecutive rows in sorted display order for an out-of-order modelValue', async () => {
    const stations = [
      station('station:1', '01站', 1),
      station('station:2', '02站', 2),
      station('station:3', '03站', 3),
      station('station:depot', '车辆段', 0, {
        sort_order: null,
        node_type: 'depot',
        participates_in_direction: false,
      }),
    ]
    const draft = ref([
      plan('station:depot', '车辆段', { sequence_no: 4, display_order: 4 }),
      plan('station:3', '03站', { sequence_no: 3, display_order: 3 }),
      plan('station:1', '01站', { sequence_no: 1, display_order: 1 }),
      plan('station:2', '02站', { sequence_no: 2, display_order: 2 }),
    ])
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })

    expect(wrapper.findAll('.table-row').map((row) => row.attributes('data-station-id'))).toEqual([
      'station:1', 'station:2', 'station:3', 'station:depot',
    ])
    await wrapper.findAll('.vlan-cell input')[0].trigger('paste', {
      clipboardData: { getData: () => '921\n922' },
    })
    await nextTick()

    const values = new Map(draft.value.map((row) => [row.station_id, row.management_vlan]))
    expect(values.get('station:1')).toBe(921)
    expect(values.get('station:2')).toBe(922)
    expect(values.get('station:3')).toBe(120)
    expect(values.get('station:depot')).toBe(120)
  })

  it('continues a multi-row paste from the next visible row instead of the raw array position', async () => {
    const stations = [
      station('station:1', '01站', 1),
      station('station:2', '02站', 2),
      station('station:3', '03站', 3),
      station('station:depot', '车辆段', 0, {
        sort_order: null,
        node_type: 'depot',
        participates_in_direction: false,
      }),
    ]
    const draft = ref([
      plan('station:depot', '车辆段', { sequence_no: 4, display_order: 4 }),
      plan('station:3', '03站', { sequence_no: 3, display_order: 3 }),
      plan('station:1', '01站', { sequence_no: 1, display_order: 1 }),
      plan('station:2', '02站', { sequence_no: 2, display_order: 2 }),
    ])
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })

    await wrapper.findAll('.table-row')[1].find('.vlan-cell input').trigger('paste', {
      clipboardData: { getData: () => '931\n932' },
    })
    await nextTick()

    const values = new Map(draft.value.map((row) => [row.station_id, row.management_vlan]))
    expect(values.get('station:1')).toBe(120)
    expect(values.get('station:2')).toBe(931)
    expect(values.get('station:3')).toBe(932)
    expect(values.get('station:depot')).toBe(120)
  })

  it('attaches validation errors to the matching sorted display row', async () => {
    const stations = [
      station('station:1', '01站', 1),
      station('station:2', '02站', 2),
      station('station:3', '03站', 3),
      station('station:depot', '车辆段', 0, {
        sort_order: null,
        node_type: 'depot',
        participates_in_direction: false,
      }),
    ]
    const draft = ref([
      plan('station:depot', '车辆段', { sequence_no: 4, display_order: 4 }),
      plan('station:3', '03站', { sequence_no: 3, display_order: 3 }),
      plan('station:2', '02站', { sequence_no: 2, display_order: 2, management_vlan: 5000 }),
      plan('station:1', '01站', { sequence_no: 1, display_order: 1 }),
    ])
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })

    const errorRows = wrapper.findAll('.table-row').filter((row) => row.find('.vlan-cell .field-error').exists())
    expect(errorRows).toHaveLength(1)
    expect(errorRows[0].attributes('data-station-id')).toBe('station:2')
    expect(errorRows[0].find('.station-name').text()).toBe('02站')
    expect(errorRows[0].find('.vlan-cell .plan-cell').attributes('title')).toContain('VLAN')
  })

  it('restores the same station after sequence editing changes its sorted display position', async () => {
    const draft = ref([
      plan('station:2', '02站', { sequence_no: 1, display_order: 1 }),
      plan('station:1', '01站', { sequence_no: 2, display_order: 2 }),
    ])
    const stations = [station('station:1', '01站', 1), station('station:2', '02站', 2)]
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })

    const secondStation = wrapper.findAll('.table-row')[0].find('.sequence-cell input')
    await secondStation.trigger('focus')
    await secondStation.setValue('3')
    await nextTick()

    expect(wrapper.findAll('.table-row').map((row) => row.attributes('data-station-id'))).toEqual([
      'station:1', 'station:2',
    ])
    await wrapper.findAll('.table-row')[1].find('.sequence-cell input').trigger('keydown', { key: 'Escape' })
    await nextTick()

    const values = new Map(draft.value.map((row) => [row.station_id, row.sequence_no]))
    expect(values.get('station:1')).toBe(2)
    expect(values.get('station:2')).toBe(1)
  })

  it('restores the focused cell baseline on Escape', async () => {
    const draft = ref([plan('station:1', '一站')])
    const Host = defineComponent({
      components: { TracksideApPlanningTab },
      setup: () => ({ draft, stations: [station('station:1', '一站', 1)] }),
      template: '<TracksideApPlanningTab v-model="draft" :stations="stations" editing :readonly="false" :saving="false" />',
    })
    const wrapper = mount(Host, { global: { stubs } })
    const vlan = wrapper.get('.vlan-cell input')

    await vlan.trigger('focus')
    await vlan.setValue('921')
    await vlan.trigger('keydown', { key: 'Escape' })
    await nextTick()

    expect(draft.value[0].management_vlan).toBe(120)
  })

  it('uses pure display mode by default and only exposes draft actions while editing', async () => {
    const wrapper = mount(TracksideApPlanningTab, {
      props: { modelValue: [plan('station:1', '一站')], stations: [station('station:1', '一站', 1)], editing: false, readonly: false, saving: false },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('当前显示已保存的 AP 规划')
    expect(wrapper.text()).not.toContain('从设备管理匹配正式站点')
    expect(wrapper.text()).not.toContain('新增规划行')

    await wrapper.setProps({ editing: true, readonly: true })
    const generate = wrapper.findAll('button').find((button) => button.text().includes('从设备管理匹配正式站点'))!
    expect(generate.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ readonly: false })
    await generate.trigger('click')
    expect(wrapper.emitted('request-generate-stations')).toHaveLength(1)
  })
})
