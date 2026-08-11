// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TrainCommunicationRow } from '../../types/trainCommunication'
import type { CarNetworkPointRow, RailTransitTask } from '../../types/railTransitWeb'
import CarNetworkPointTableDialog from './CarNetworkPointTableDialog.vue'

const routerPush = vi.hoisted(() => vi.fn())
const confirmMock = vi.hoisted(() => vi.fn())
const api = vi.hoisted(() => ({
  exportCarNetworkPointTable: vi.fn(),
  generateCarNetworkPointTable: vi.fn(),
  getCarNetworkPointTable: vi.fn(),
  getCarNetworkPointTableTask: vi.fn(),
  previewCarNetworkPointTable: vi.fn(),
  recoverCarNetworkPointTableTasks: vi.fn(),
  saveCarNetworkPointTable: vi.fn(),
  transformCarNetworkPointTable: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('../../components/feedback/useConfirm', () => ({ useConfirm: () => ({ confirm: confirmMock }) }))
vi.mock('../../api/railTransitWeb', () => api)
vi.mock('../../features', () => ({ isFeatureEnabled: vi.fn(() => true) }))

const stubs = {
  ElAlert: { props: ['title', 'description'], template: '<div class="el-alert"><strong>{{ title }}</strong><span>{{ description }}</span><slot /></div>' },
  ElButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>' },
  ElCheckbox: { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<label><input type="checkbox" :disabled="disabled" @change="$emit(\'change\', true)" /><slot /></label>' },
  ElCollapse: { template: '<div><slot /></div>' },
  ElCollapseItem: { template: '<section><slot /></section>' },
  ElDescriptions: { template: '<dl><slot /></dl>' },
  ElDescriptionsItem: { props: ['label'], template: '<div><dt>{{ label }}</dt><dd><slot /></dd></div>' },
  ElDialog: { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<div v-if="modelValue" class="el-dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></div>' },
  ElInput: { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'input'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'input\', $event.target.value)" />' },
  ElInputNumber: { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<input type="number" :value="modelValue" :disabled="disabled" @change="$emit(\'change\', 1)" />' },
  ElOption: { props: ['label', 'value'], template: '<option>{{ label }}</option>' },
  ElSelect: { props: ['modelValue', 'disabled'], emits: ['update:modelValue', 'change'], template: '<select :disabled="disabled"><slot /></select>' },
  ElTag: { template: '<span><slot /></span>' },
  ElTooltip: { template: '<span><slot /></span>' },
  NcDataTable: { props: ['data'], emits: ['selection-change'], template: '<div class="nc-table"><div v-for="row in data" :key="row.node_name">{{ row.train_id }} {{ row.node_name }}</div><slot /></div>' },
}

const train: TrainCommunicationRow = {
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

const nodes: CarNetworkPointRow[] = ['TC1-MR', 'TC1-SW', 'TC1-SRV', 'TC2-MR', 'TC2-SW', 'TC2-SRV'].map((nodeName) => ({
  train_id: 'train:01',
  train_no: '01',
  display_name: '列车01 / 01车',
  tc: nodeName.startsWith('TC1') ? 'TC1' : 'TC2',
  end: nodeName.startsWith('TC1') ? 'CT' : 'CW',
  node_name: nodeName,
  node_type: nodeName.endsWith('-MR') ? 'MR' : nodeName.endsWith('-SW') ? '3SW' : 'SRV',
  device_id: nodeName === 'TC1-MR' ? 'mr-ct' : nodeName === 'TC2-MR' ? 'mr-tc' : '',
  device_name: nodeName === 'TC1-MR' ? '列车01-MR-CT' : nodeName === 'TC2-MR' ? '列车01-MR-CW' : '',
  device_group: '',
  station: '',
  primary_address: nodeName.endsWith('-MR') ? '10.1.0.1' : '',
  backup_address: '',
  ip_vehicle: '',
  ip_uplink: '',
  ssh_host: '',
  vrrp_ip: '',
  address_mapping_mode: 'global',
  primary_address_role: '',
  backup_address_role: '',
  remark: '',
}))

function task(action: string, resultSummary: Record<string, unknown>): RailTransitTask {
  return {
    task_id: `${action}-task`,
    status: 'COMPLETED',
    action,
    artifact_id: '',
    artifact_name: '',
    available: false,
    sha256: '',
    size_bytes: 0,
    message: '',
    error_message: '',
    result_summary: resultSummary,
  }
}

function findButton(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error(`button not found: ${text}`)
  return button
}

describe('在线列车车内通信点表 Dialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    confirmMock.mockResolvedValue(true)
    api.getCarNetworkPointTable.mockResolvedValueOnce({ rows: [], global_config: {}, locked: false, revision: 'rev-1' })
      .mockResolvedValue({ rows: nodes, global_config: {}, locked: false, revision: 'rev-2' })
    api.recoverCarNetworkPointTableTasks.mockResolvedValue([])
    api.generateCarNetworkPointTable.mockResolvedValue(task('car_network_generate_point_table', { nodes }))
    api.saveCarNetworkPointTable.mockResolvedValue(task('car_network_save_point_table', { revision: 'rev-2', nodes }))
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { openTaskWindow: vi.fn() },
    })
  })

  it('从当前列车生成六节点预览，保存后通知父页面', async () => {
    const wrapper = mount(CarNetworkPointTableDialog, {
      props: { modelValue: false, train },
      global: { directives: { loading: () => undefined }, stubs },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(wrapper.text()).toContain('当前列车尚未配置点表')
    expect(wrapper.text()).toContain('TC1-MR、TC1-SW、TC1-SRV、TC2-MR、TC2-SW、TC2-SRV')

    await findButton(wrapper, '为当前列车生成六节点点表').trigger('click')
    await flushPromises()

    expect(api.generateCarNetworkPointTable).toHaveBeenCalledWith([], expect.any(Object), expect.objectContaining({
      canonical_train_id: 'train:01',
      ct_mr_id: 'mr-ct',
      tc_mr_id: 'mr-tc',
    }))
    expect(wrapper.text()).toContain('已生成 6 行点表预览，尚未保存')
    expect(wrapper.text()).toContain('TC1-MR')
    expect(wrapper.text()).toContain('TC2-SRV')

    await findButton(wrapper, '保存点表').trigger('click')
    await flushPromises()

    expect(api.saveCarNetworkPointTable).toHaveBeenCalledWith(nodes, expect.any(Object), false, 'rev-1')
    expect(wrapper.text()).toContain('当前列车点表保存成功')
    expect(wrapper.emitted('saved')?.[0]?.[0]).toEqual({ trainId: 'train:01', revision: 'rev-2', rowCount: 6 })
    wrapper.unmount()
  })

  it('任务完成但未返回预览时保留编辑区并显示明确错误', async () => {
    api.generateCarNetworkPointTable.mockResolvedValue(task('car_network_generate_point_table', {}))
    const wrapper = mount(CarNetworkPointTableDialog, {
      props: { modelValue: false, train },
      global: { directives: { loading: () => undefined }, stubs },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    await findButton(wrapper, '为当前列车生成六节点点表').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('点表生成任务已完成，但未返回生成结果')
    expect(wrapper.text()).not.toContain('已生成 6 行点表预览，尚未保存')
    wrapper.unmount()
  })

  it('空预览不会清空现有编辑区，并记录计数不一致警告', async () => {
    api.getCarNetworkPointTable.mockReset()
    api.getCarNetworkPointTable.mockResolvedValue({ rows: nodes, global_config: {}, locked: false, revision: 'rev-1' })
    api.generateCarNetworkPointTable.mockResolvedValue(task('car_network_generate_point_table', { nodes: [], count: 6 }))
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const wrapper = mount(CarNetworkPointTableDialog, {
      props: { modelValue: false, train },
      global: { directives: { loading: () => undefined }, stubs },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    await findButton(wrapper, '生成当前列车六节点').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('未生成任何点表节点，请检查当前列车身份及设备映射。')
    expect(wrapper.text()).toContain('TC1-MR')
    expect(warning).not.toHaveBeenCalled()
    warning.mockRestore()
    wrapper.unmount()
  })

  it('以实际预览行数为准并记录后端计数不一致', async () => {
    api.generateCarNetworkPointTable.mockResolvedValue(task('car_network_generate_point_table', { nodes, count: 5 }))
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const wrapper = mount(CarNetworkPointTableDialog, {
      props: { modelValue: false, train },
      global: { directives: { loading: () => undefined }, stubs },
    })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    await findButton(wrapper, '为当前列车生成六节点点表').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已生成 6 行点表预览，尚未保存')
    expect(warning).toHaveBeenCalledWith('点表生成任务节点计数不一致', { expectedCount: 5, receivedCount: 6 })
    warning.mockRestore()
    wrapper.unmount()
  })
})
