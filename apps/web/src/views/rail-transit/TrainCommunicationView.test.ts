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
  listOnlineTrainCommunications: vi.fn(),
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
  tc1_nodes: [],
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

describe('在线列车车内通信检测页面', () => {
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
    api.listOnlineTrainCommunications.mockResolvedValue({ items: [onlineTrain], total: 1, page: 1, page_size: 200 })
    api.getTrainCommunicationTopology.mockResolvedValue(topology)
    api.recoverTrainCommunicationChecks.mockResolvedValue([])
    api.startTrainCommunicationCheck.mockResolvedValue({ task_id: 'task-1', status: 'RUNNING', action: 'car_network_diagnostic', message: '已提交' })
  })

  it('使用正式在线列车接口，不依赖 Online MR 活跃采集 Session', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(api.listOnlineTrainCommunications).toHaveBeenCalledWith(1, 200)
    expect(wrapper.text()).toContain('列车01 / 01车 · 单端在线（CT）')
    expect(wrapper.text()).not.toContain('No data')

    await wrapper.findAll('button').find((button) => button.text() === '立即检测')!.trigger('click')

    expect(api.startTrainCommunicationCheck).toHaveBeenCalledWith('train:01')
    wrapper.unmount()
  })

  it('在线列车为空时显示中文原因和导航入口', async () => {
    api.listOnlineTrainCommunications.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('当前未检测到在线列车')
    expect(wrapper.text()).toContain('AC Mesh-Link 数据不存在')
    expect(wrapper.text()).toContain('打开列车 MR 映射')
    expect(wrapper.text()).not.toContain('No data')

    await wrapper.findAll('button').find((button) => button.text().includes('前往“列车在线情况”'))!.trigger('click')
    expect(routerPush).toHaveBeenCalledWith({ path: '/rail-transit/train-online', query: {} })
    wrapper.unmount()
  })

  it('点表保存事件会刷新在线列车和当前拓扑', async () => {
    const wrapper = mountView()
    await flushPromises()

    api.listOnlineTrainCommunications.mockClear()
    api.getTrainCommunicationTopology.mockClear()
    await wrapper.findAll('button').find((button) => button.text() === '点表管理')!.trigger('click')
    expect(wrapper.text()).toContain('Dialog 打开')

    await wrapper.find('.emit-saved').trigger('click')
    await flushPromises()

    expect(api.listOnlineTrainCommunications).toHaveBeenCalledWith(1, 200)
    expect(api.getTrainCommunicationTopology).toHaveBeenCalledWith('train:01')
    expect(wrapper.text()).toContain('检测点表已保存，可以开始检测')
    wrapper.unmount()
  })
})
