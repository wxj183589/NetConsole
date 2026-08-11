// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import type { TrainCommunicationRow, TrainCommunicationTopology } from '../../types/trainCommunication'
import TrainCommunicationView from './TrainCommunicationView.vue'

const routerPush = vi.hoisted(() => vi.fn())
const api = vi.hoisted(() => ({
  getTrainCommunicationCheck: vi.fn(),
  getTrainCommunicationSummary: vi.fn(),
  getTrainCommunicationTopology: vi.fn(),
  listTrainCommunications: vi.fn(),
  recoverTrainCommunicationChecks: vi.fn(),
  startTrainCommunicationCheck: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../api/trainCommunication', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))

const FixedTrainTopologyStub = defineComponent({
  props: ['topology', 'checking'],
  emits: ['select-node'],
  template: '<div class="fixed-topology">{{ topology?.point_table_status || "empty-topology" }}</div>',
})

const PointTableDialogStub = defineComponent({
  props: ['modelValue', 'train'],
  emits: ['update:modelValue', 'saved'],
  template: `
    <div v-if="modelValue" class="point-table-dialog">
      <span>Dialog 打开</span>
      <button class="emit-saved" @click="$emit('saved', { trainId: train?.train_id || '', revision: 'rev-2', rowCount: 6 })">模拟保存</button>
    </div>
  `,
})

const stubs = {
  CarNetworkPointTableDialog: PointTableDialogStub,
  ElAlert: { props: ['title', 'description'], template: '<div class="el-alert"><strong>{{ title }}</strong><span>{{ description }}</span><slot /></div>' },
  ElButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>' },
  ElOption: { props: ['label', 'value'], template: '<div class="el-option">{{ label }}</div>' },
  ElSelect: { props: ['modelValue', 'loading'], emits: ['update:modelValue'], template: '<div class="el-select"><slot /><slot name="empty" /></div>' },
  ElTag: { template: '<span class="el-tag"><slot /></span>' },
  ElTooltip: { template: '<span class="el-tooltip"><slot /></span>' },
  FixedTrainTopology: FixedTrainTopologyStub,
}

const onlineTrain: TrainCommunicationRow = {
  train_id: 'train:01',
  train_no: '01',
  train_name: '列车01',
  communication_status: 'warning',
  canonical_train_id: 'train:01',
  display_name: '列车01 / 01车',
  overall_status: 'ONE_SIDE_ONLINE',
  ct_online_status: 'ONLINE',
  tc_online_status: 'OFFLINE',
  ct_mr_id: 'mr-ct',
  ct_mr_name: '列车01-MR-CT',
  tc_mr_id: 'mr-tc',
  tc_mr_name: '列车01-MR-CW',
  updated_at: '2026-07-22T10:00:00+00:00',
  data_status: 'FRESH',
  online_reason: 'CT 端 Mesh-Link 在线',
  diagnostic_status: 'not_detected',
  tc1_diagnostic_status: 'not_detected',
  tc2_diagnostic_status: 'not_detected',
  last_diagnostic_at: null,
  mrs: [],
  current_mesh_links: 1,
  active_sessions: 0,
  warning_count: 0,
  last_updated_at: '2026-07-22T10:00:00+00:00',
}

const topology: TrainCommunicationTopology = {
  train_id: 'train:01',
  train_name: '列车01',
  train_status: 'normal',
  checked_at: '2026-07-22T10:01:00+00:00',
  point_table_status: 'configured',
  point_table_message: '检测点表已配置',
  point_table_revision: 'rev-1',
  point_table_missing_nodes: [],
  tc1_nodes: [{ node_id: 'TC1-MR', side: 'TC1', role: 'MR', name: 'TC1-MR', device_id: 'mr-ct', ip_address: '10.0.0.1', status: 'not_detected', message: '', updated_at: null }],
  tc2_nodes: [],
  links: [],
  vrrp: { status: 'not_detected', master_side: null, virtual_ip: null, master_device: null, backup_device: null, message: '', updated_at: null },
  cross_end: { status: 'not_detected', message: '', updated_at: null },
}

function mountView() {
  return mount(TrainCommunicationView, {
    global: {
      directives: { loading: () => undefined },
      stubs,
    },
  })
}

describe('车内通信检测页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getTrainCommunicationSummary.mockResolvedValue({
      site_id: '宁波地铁12号线',
      registered_trains: 1,
      registered_mrs: 2,
      normal_trains: 1,
      warning_trains: 0,
      critical_trains: 0,
      stale_trains: 0,
      unknown_trains: 0,
      current_mesh_links: 1,
      active_online_mr_sessions: 0,
      agent_imported_sessions: 0,
      latest_updated_at: '2026-07-22T10:00:00+00:00',
    })
    api.listTrainCommunications.mockResolvedValue({ items: [onlineTrain], total: 1, page: 1, page_size: 200 })
    api.getTrainCommunicationTopology.mockResolvedValue(topology)
    api.recoverTrainCommunicationChecks.mockResolvedValue([])
    api.startTrainCommunicationCheck.mockResolvedValue({ task_id: 'task-1', status: 'RUNNING', action: 'car_network_diagnostic', message: '已提交' })
  })

  it('使用全部列车接口并按点表启动检测', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(api.listTrainCommunications).toHaveBeenCalledWith({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' })
    expect(wrapper.text()).toContain('轨道交通 / 车内通信检测')
    expect(wrapper.text()).toContain('列车01 / 01车')
    expect(wrapper.text()).not.toContain('No data')

    await wrapper.findAll('button').find((button) => button.text() === '开始检测')!.trigger('click')

    expect(api.startTrainCommunicationCheck).toHaveBeenCalledWith('train:01')
    wrapper.unmount()
  })

  it('没有在线列车时仍显示全部基础资料列车并允许选择', async () => {
    const trains = Array.from({ length: 18 }, (_, index) => {
      const no = String(index + 1).padStart(2, '0')
      return {
        ...onlineTrain,
        train_id: `train:${no}`,
        canonical_train_id: `train:${no}`,
        train_no: no,
        train_name: `${no}车`,
        display_name: `${no}车`,
        overall_status: 'BOTH_OFFLINE' as const,
        ct_online_status: 'OFFLINE' as const,
        tc_online_status: 'OFFLINE' as const,
        data_status: 'FRESH',
      }
    })
    api.listTrainCommunications.mockResolvedValue({ items: trains, total: 18, page: 1, page_size: 200 })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('.train-row')).toHaveLength(18)
    expect(wrapper.text()).toContain('01车')
    expect(wrapper.text()).toContain('18车')
    expect(wrapper.text()).toContain('当前离线')
    expect(wrapper.text()).not.toContain('当前未检测到在线列车')
    expect(wrapper.text()).not.toContain('AC Mesh-Link 数据不存在')

    await wrapper.findAll('.train-row')[17].trigger('click')
    await flushPromises()
    expect(api.getTrainCommunicationTopology).toHaveBeenLastCalledWith('train:18')
    wrapper.unmount()
  })

  it('在线数据过期时不阻止检测', async () => {
    api.listTrainCommunications.mockResolvedValue({
      items: [{ ...onlineTrain, overall_status: 'STALE', data_status: 'STALE', ct_online_status: 'STALE', tc_online_status: 'STALE' }],
      total: 1,
      page: 1,
      page_size: 200,
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('数据过期')
    await wrapper.findAll('button').find((button) => button.text() === '开始检测')!.trigger('click')
    expect(api.startTrainCommunicationCheck).toHaveBeenCalledWith('train:01')
    wrapper.unmount()
  })

  it('点表缺失时禁用开始检测并保留点表入口', async () => {
    api.getTrainCommunicationTopology.mockResolvedValue({ ...topology, point_table_status: 'missing', point_table_message: '检测点表未配置', tc1_nodes: [] })
    const wrapper = mountView()
    await flushPromises()

    const start = wrapper.findAll('button').find((button) => button.text() === '开始检测')!
    expect(start.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('打开点表')
    expect(wrapper.text()).toContain('检测点表未配置')
    wrapper.unmount()
  })

  it('点表保存事件会刷新在线列车和当前拓扑', async () => {
    const wrapper = mountView()
    await flushPromises()

    api.listTrainCommunications.mockClear()
    api.getTrainCommunicationTopology.mockClear()
    await wrapper.findAll('button').find((button) => button.text() === '打开点表')!.trigger('click')
    expect(wrapper.text()).toContain('Dialog 打开')

    await wrapper.find('.emit-saved').trigger('click')
    await flushPromises()

    expect(api.listTrainCommunications).toHaveBeenCalledWith({ page: 1, page_size: 200, sort_by: 'train_no', sort_order: 'asc' })
    expect(api.getTrainCommunicationTopology).toHaveBeenCalledWith('train:01')
    expect(wrapper.text()).toContain('检测点表已保存，可以开始检测')
    wrapper.unmount()
  })

  it('刷新后保留当前选择', async () => {
    const second = { ...onlineTrain, train_id: 'train:02', canonical_train_id: 'train:02', train_no: '02', train_name: '02车', display_name: '02车' }
    api.listTrainCommunications.mockResolvedValue({ items: [onlineTrain, second], total: 2, page: 1, page_size: 200 })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('.train-row')[1].trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '刷新')!.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.train-row')[1].classes()).toContain('selected')
    expect(api.getTrainCommunicationTopology).toHaveBeenLastCalledWith('train:02')
    wrapper.unmount()
  })
})
