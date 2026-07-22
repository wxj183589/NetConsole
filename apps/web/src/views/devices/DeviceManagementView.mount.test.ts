// @vitest-environment happy-dom

import { defineComponent, h, reactive, useAttrs, type Component } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listDevices: vi.fn(),
  getDeviceEditProfile: vi.fn(),
  getDeviceConnectionTest: vi.fn(),
  updateDevice: vi.fn(),
  startBatchRefreshDetails: vi.fn(),
  startDeviceFormConnectionTest: vi.fn(),
  downloadBackendResource: vi.fn(),
  openPath: vi.fn(),
  showItemInFolder: vi.fn(),
  routerPush: vi.fn(),
  openTaskWindow: vi.fn(),
  featureEnabled: vi.fn(() => true),
  messages: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  taskStore: null as null | {
    tasks: Array<Record<string, unknown>>
    refresh: ReturnType<typeof vi.fn>
    acquirePolling: ReturnType<typeof vi.fn>
    releasePolling: ReturnType<typeof vi.fn>
  },
}))

vi.mock('../../api/deviceManagement', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api/deviceManagement')>(),
  listDevices: mocks.listDevices,
  getDeviceEditProfile: mocks.getDeviceEditProfile,
  getDeviceConnectionTest: mocks.getDeviceConnectionTest,
  updateDevice: mocks.updateDevice,
  startBatchRefreshDetails: mocks.startBatchRefreshDetails,
  startDeviceFormConnectionTest: mocks.startDeviceFormConnectionTest,
}))

vi.mock('../../features', () => ({ isFeatureEnabled: mocks.featureEnabled }))
vi.mock('../../stores/tasks', () => ({ useTaskStore: () => mocks.taskStore }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.routerPush }) }))
vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: mocks.downloadBackendResource,
  getRuntimeConfig: () => ({ hostType: 'electron', apiBaseUrl: '', apiToken: '' }),
  getPlatformAdapter: () => ({
    openPath: mocks.openPath,
    showItemInFolder: mocks.showItemInFolder,
    selectFile: vi.fn(),
    openExternalUrl: vi.fn(),
  }),
}))
vi.mock('element-plus', async (importOriginal) => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: mocks.messages,
  ElMessageBox: { confirm: vi.fn(async () => undefined) },
}))

import DeviceManagementView from './DeviceManagementView.vue'

const listItem = {
  id: 1,
  device_uuid: 'device-1',
  name: 'MR2',
  system_name: 'MR-02',
  station: '车站 A',
  group_id: 1,
  group_name: '车载 MR',
  device_vendor: 'H3C',
  device_type: 'AC',
  primary_address: '192.0.2.12',
  backup_address: '',
  updated_at: '2026-07-17T00:00:00+00:00',
  capabilities: { ssh: true, ssh_port: 22, telnet: false, telnet_port: 23, snmp: true, snmp_versions: ['v2c'], snmp_port: 161 },
  connection_status: 'UNKNOWN',
  last_test_task_id: '',
  last_test_time: '',
}

const detail = {
  device: {
    ...listItem,
    location: '',
    mac_address: '',
    https_port: 443,
    web_url: 'https://192.0.2.12:443',
    ssh_username: 'admin',
    telnet_username: '',
    tunnel_enabled: false,
    tunnel1_enabled: false,
    tunnel1_host: '',
    tunnel1_port: 22,
    tunnel1_username: '',
    tunnel2_enabled: false,
    tunnel2_host: '',
    tunnel2_port: 22,
    tunnel2_username: '',
    snmp_v1_enabled: false,
    snmp_v2c_enabled: true,
    snmp_timeout_ms: 2000,
    snmp_retries: 1,
    ssh_secret_configured: true,
    telnet_secret_configured: false,
    tunnel1_secret_configured: false,
    tunnel2_secret_configured: false,
    snmp_ro_secret_configured: true,
    remark: '',
    created_at: '2026-07-17T00:00:00+00:00',
  },
  fact: null,
  recent_tasks: [],
  recent_collection: null,
  recent_errors: [],
  connection_commands: [],
  interfaces: [],
  optical_modules: [],
  lldp_neighbors: [],
  trackside_ap_business: [],
}

const editProfile = {
  device_uuid: 'device-1',
  name: 'MR2', system_name: 'MR-02', station: '车站 A', location: '', group_id: 1, device_vendor: 'H3C', device_type: 'AC',
  primary_address: '192.0.2.12', backup_address: '',
  ssh_enabled: true, ssh_port: 22, ssh_username: 'admin', telnet_enabled: false, telnet_port: 23, telnet_username: '',
  tunnel_enabled: false, tunnel1_enabled: false, tunnel1_host: '', tunnel1_port: 22, tunnel1_username: '',
  tunnel2_enabled: false, tunnel2_host: '', tunnel2_port: 22, tunnel2_username: '',
  snmp_enabled: true, snmp_v1_enabled: false, snmp_v2c_enabled: true, snmp_port: 161, snmp_timeout_ms: 2000, snmp_retries: 1,
  https_port: 443, remark: '', ssh_secret_configured: true, telnet_secret_configured: false,
  tunnel1_secret_configured: false, tunnel2_secret_configured: false, snmp_ro_secret_configured: true,
}

function task(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'device-task-1',
    type: 'device_connection_test',
    name: '设备连接测试',
    status: 'PENDING',
    progress: 0,
    phase: '',
    stage: '',
    message: '等待执行',
    site_name: 'demo',
    owner: 'web_device_management',
    executor: 'local',
    source: 'local',
    device_id: 'device-1',
    device_name: 'MR2',
    agent: '',
    mr_name: '',
    session_id: '',
    mapping_state: '',
    created_time: '',
    started_time: '',
    finished_time: '',
    updated_time: '',
    duration_seconds: 0,
    error_code: '',
    error_summary: '',
    has_warning: false,
    snapshot_id: null,
    records_count: null,
    parser_version: '',
    module: 'devices',
    artifact_download: null,
    ...overrides,
  }
}

async function renderView(): Promise<VueWrapper> {
  const wrapper = mount(DeviceManagementView, {
    attachTo: document.body,
    global: {
      directives: { loading: () => undefined },
      stubs: elementStubs,
    },
  })
  await flushPromises()
  return wrapper
}

async function openEdit(wrapper: VueWrapper): Promise<void> {
  await wrapper.get('[data-testid="select-first-device"]').trigger('click')
  const button = wrapper.findAll('button').find((item) => item.text() === '编辑' && item.attributes('disabled') === undefined)
  expect(button).toBeTruthy()
  await button!.trigger('click')
  await flushPromises()
  expect(mocks.getDeviceEditProfile).toHaveBeenCalledWith('device-1', expect.any(AbortSignal))
  expect(wrapper.find('[data-testid="device-save"]').exists()).toBe(true)
}

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { slots }) {
    const attrs = useAttrs()
    return () => h('div', attrs, slots.default?.())
  },
})

const buttonStub = defineComponent({
  inheritAttrs: false,
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', {
      ...attrs,
      disabled: props.disabled || props.loading,
      onClick: (event: Event) => emit('click', event),
    }, slots.default?.())
  },
})

const inputStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: { type: [String, Number], default: '' }, disabled: Boolean },
  emits: ['update:modelValue'],
  setup(props, { attrs, emit }) {
    return () => h('span', attrs, [h('input', {
      value: props.modelValue,
      disabled: props.disabled,
      onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
    })])
  },
})

const checkboxStub = defineComponent({
  inheritAttrs: false,
  props: { modelValue: Boolean, disabled: Boolean },
  emits: ['update:modelValue', 'change'],
  setup(props, { attrs, emit, slots }) {
    return () => h('label', attrs, [
      h('input', {
        type: 'checkbox',
        checked: props.modelValue,
        disabled: props.disabled,
        onChange: (event: Event) => {
          const checked = (event.target as HTMLInputElement).checked
          emit('update:modelValue', checked)
          emit('change', checked)
        },
      }),
      slots.default?.(),
    ])
  },
})

const tableStub = defineComponent({
  inheritAttrs: false,
  props: { data: { type: Array, default: () => [] } },
  emits: ['selection-change'],
  setup(props, { emit, expose, slots }) {
    expose({ clearSelection: vi.fn(), toggleRowSelection: vi.fn() })
    return () => h('div', [
      props.data.length
        ? h('button', { 'data-testid': 'select-first-device', onClick: () => emit('selection-change', [props.data[0]]) }, '选择首台设备')
        : null,
      props.data.length > 1
        ? h('button', { 'data-testid': 'select-second-device', onClick: () => emit('selection-change', [props.data[1]]) }, '选择第二台设备')
        : null,
      slots.default?.(),
    ])
  },
})

const dialogStub = defineComponent({
  props: { modelValue: Boolean },
  setup(props, { slots }) {
    return () => props.modelValue ? h('section', [slots.default?.(), slots.footer?.()]) : null
  },
})

const elementStubs: Record<string, Component | boolean> = {
  teleport: true,
  ElAlert: passthrough,
  ElButton: buttonStub,
  ElCheckbox: checkboxStub,
  ElDescriptions: passthrough,
  ElDescriptionsItem: passthrough,
  ElDialog: dialogStub,
  ElDrawer: dialogStub,
  ElDropdown: passthrough,
  ElDropdownItem: passthrough,
  ElDropdownMenu: passthrough,
  ElEmpty: passthrough,
  ElForm: passthrough,
  ElFormItem: passthrough,
  ElInput: inputStub,
  ElInputNumber: inputStub,
  ElOption: passthrough,
  ElPagination: passthrough,
  ElSelect: passthrough,
  ElTabPane: passthrough,
  ElTabs: passthrough,
  ElTable: tableStub,
  ElTableColumn: true,
  ElTag: passthrough,
  ElTooltip: passthrough,
}

beforeEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
  mocks.listDevices.mockResolvedValue({ items: [listItem], groups: [{ id: 1, name: '车载 MR' }], total: 1, page: 1, page_size: 50, total_pages: 1 })
  mocks.getDeviceEditProfile.mockResolvedValue(editProfile)
  mocks.updateDevice.mockResolvedValue({ action: 'updated', device: detail.device })
  mocks.startBatchRefreshDetails.mockResolvedValue({ action: 'batch_refresh_details', tasks: [] })
  mocks.startDeviceFormConnectionTest.mockResolvedValue({
    task_id: 'form-test-1', task_status: 'PENDING', device_uuid: 'device-1', protocol: 'SSH', success: null,
    result_status: '', failure_category: '', message: '等待执行', safe_message: '等待执行', method: '', host: '', port: null, latency_ms: null, elapsed_ms: null, tested_at: '', system_name: '',
    model: '', os_family: '', interface_count: null, error_type: '', suggestion: '', created_time: '', updated_time: '',
  })
  mocks.getDeviceConnectionTest.mockResolvedValue({
    task_id: 'form-test-1', task_status: 'COMPLETED', device_uuid: 'device-1', protocol: 'SSH', success: true,
    result_status: 'ok', failure_category: '', message: 'SSH 连接成功', safe_message: 'SSH 连接成功', method: 'primary_direct', host: '192.0.2.12', port: 22, latency_ms: 3, elapsed_ms: 3, tested_at: '2026-07-22T00:00:00Z', system_name: 'MR-02',
    model: '', os_family: '', interface_count: null, error_type: '', suggestion: '', created_time: '', updated_time: '',
  })
  const store = reactive({
    tasks: [] as Array<Record<string, unknown>>,
    refresh: vi.fn(async () => undefined),
    acquirePolling: vi.fn(),
    releasePolling: vi.fn(),
  })
  mocks.taskStore = store
  mocks.downloadBackendResource.mockResolvedValue({ status: 'saved', capabilityId: '8a02d34f-ec8f-4c17-9a8a-b266bdf9e137' })
  mocks.openPath.mockResolvedValue({ success: true })
  mocks.showItemInFolder.mockResolvedValue({ success: true })
  mocks.openTaskWindow.mockResolvedValue({ success: true })
  Object.defineProperty(window, 'netconsoleDesktop', {
    configurable: true,
    value: { openTaskWindow: mocks.openTaskWindow },
  })
})

describe('DeviceManagementView mounted interactions', () => {
  it('ignores stale edit profile responses and keeps save/test bound to the editing UUID', async () => {
    let resolveFirst!: (value: typeof editProfile) => void
    let resolveSecond!: (value: typeof editProfile) => void
    const firstProfile = new Promise<typeof editProfile>((resolve) => { resolveFirst = resolve })
    const secondProfile = new Promise<typeof editProfile>((resolve) => { resolveSecond = resolve })
    const secondRow = { ...listItem, device_uuid: 'device-2', name: 'MR3' }
    mocks.listDevices.mockResolvedValue({ items: [listItem, secondRow], groups: [{ id: 1, name: '车载 MR' }], total: 2, page: 1, page_size: 50, total_pages: 1 })
    mocks.getDeviceEditProfile
      .mockImplementationOnce(() => firstProfile)
      .mockImplementationOnce(() => secondProfile)

    const wrapper = await renderView()
    await wrapper.get('[data-testid="select-first-device"]').trigger('click')
    await wrapper.findAll('button').find((item) => item.text() === '编辑' && item.attributes('disabled') === undefined)!.trigger('click')
    await wrapper.get('[data-testid="select-second-device"]').trigger('click')
    await wrapper.findAll('button').find((item) => item.text() === '编辑' && item.attributes('disabled') === undefined)!.trigger('click')

    expect(mocks.getDeviceEditProfile).toHaveBeenCalledTimes(2)
    expect(mocks.getDeviceEditProfile.mock.calls[0][1].aborted).toBe(true)
    resolveSecond({ ...editProfile, device_uuid: 'device-2', name: 'MR3' })
    await flushPromises()
    expect((wrapper.get('[data-testid="device-name"] input').element as HTMLInputElement).value).toBe('MR3')

    await wrapper.get('[data-testid="device-save"]').trigger('click')
    await flushPromises()
    expect(mocks.updateDevice).toHaveBeenCalledWith('device-2', expect.objectContaining({ name: 'MR3' }))

    resolveFirst({ ...editProfile, device_uuid: 'device-1', name: '旧设备' })
    await flushPromises()
    expect(mocks.updateDevice).toHaveBeenCalledWith('device-2', expect.objectContaining({ name: 'MR3' }))
    wrapper.unmount()
  })

  it('saves an edit and reports backend validation and write failures', async () => {
    const wrapper = await renderView()
    await openEdit(wrapper)
    await wrapper.get('[data-testid="device-name"] input').setValue('MR2-已保存')
    await wrapper.get('[data-testid="device-save"]').trigger('click')
    await flushPromises()

    expect(mocks.updateDevice).toHaveBeenCalledWith('device-1', expect.objectContaining({ name: 'MR2-已保存' }))
    expect(mocks.messages.success).toHaveBeenCalledWith('设备已保存')
    wrapper.unmount()

    mocks.updateDevice.mockRejectedValueOnce(new Error('主地址格式无效'))
    const failed = await renderView()
    await openEdit(failed)
    await failed.get('[data-testid="device-address"] input').setValue('not-an-address')
    await failed.get('[data-testid="device-save"]').trigger('click')
    await flushPromises()

    expect(mocks.updateDevice).toHaveBeenCalledWith('device-1', expect.objectContaining({ primary_address: 'not-an-address' }))
    expect(mocks.messages.error).toHaveBeenCalledWith('主地址格式无效')
    failed.unmount()

    mocks.updateDevice.mockRejectedValueOnce(new Error('设备数据库写入失败'))
    const writeFailed = await renderView()
    await openEdit(writeFailed)
    await writeFailed.get('[data-testid="device-save"]').trigger('click')
    await flushPromises()

    expect(mocks.messages.error).toHaveBeenCalledWith('设备数据库写入失败')
    writeFailed.unmount()
  })

  it.each([
    ['unchanged', '', false, ''],
    ['replaced', 'replacement-secret', false, 'replacement-secret'],
    ['cleared', '', true, undefined],
  ])('submits credential state %s without echoing an existing secret', async (_state, input, clear, expected) => {
    const wrapper = await renderView()
    await openEdit(wrapper)
    if (input) await wrapper.get('[data-testid="ssh-password"] input').setValue(input)
    if (clear) await wrapper.get('[data-testid="ssh-clear"] input').setValue(true)
    await wrapper.get('[data-testid="device-save"]').trigger('click')
    await flushPromises()

    const payload = mocks.updateDevice.mock.calls[0][1]
    expect(payload.ssh_password).toBe(expected)
    expect(payload.clear_secret_fields || []).toEqual(clear ? ['ssh_password'] : [])
    expect(JSON.stringify(payload)).not.toContain('secret-password')
    wrapper.unmount()
  })

  it('submits form testing without saving, tracks its result, and keeps a task-window entry', async () => {
    const wrapper = await renderView()
    await openEdit(wrapper)
    await wrapper.get('[data-testid="ssh-password"] input').setValue('ephemeral-form-secret')
    mocks.taskStore!.refresh.mockImplementation(async () => {
      mocks.taskStore!.tasks = [task({ id: 'form-test-1' })]
    })

    await wrapper.get('[data-testid="form-connection-test"]').trigger('click')
    await flushPromises()

    expect(mocks.startDeviceFormConnectionTest).toHaveBeenCalledWith(expect.objectContaining({
      device_uuid: 'device-1', protocol: 'SSH', ssh_password: 'ephemeral-form-secret',
    }))
    expect(mocks.updateDevice).not.toHaveBeenCalled()
    expect(mocks.openTaskWindow).not.toHaveBeenCalled()
    expect((wrapper.get('[data-testid="form-connection-test"]').element as HTMLButtonElement).disabled).toBe(true)

    mocks.taskStore!.tasks = [task({ id: 'form-test-1', status: 'COMPLETED', updated_time: 'done' })]
    await flushPromises()
    expect(mocks.getDeviceConnectionTest).toHaveBeenCalledWith('form-test-1')
    expect(mocks.messages.success).toHaveBeenCalledWith('SSH 连接成功')
    await wrapper.get('[data-testid="form-connection-task"]').trigger('click')
    expect(mocks.openTaskWindow).toHaveBeenCalledWith(expect.objectContaining({ taskId: 'form-test-1', module: 'devices' }))

    await wrapper.get('[data-testid="device-form-cancel"]').trigger('click')
    await flushPromises()
    await openEdit(wrapper)
    expect((wrapper.get('[data-testid="ssh-password"] input').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('enables SSH form testing only when the current form has usable authentication', async () => {
    const edited = await renderView()
    await openEdit(edited)
    expect((edited.get('[data-testid="form-connection-test"]').element as HTMLButtonElement).disabled).toBe(false)

    await edited.get('[data-testid="ssh-clear"] input').setValue(true)
    await flushPromises()
    expect((edited.get('[data-testid="form-connection-test"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(edited.get('[data-testid="form-connection-disabled-reason"]').text()).toContain('请输入 SSH 密码')
    edited.unmount()

    const created = await renderView()
    await created.findAll('button').find((button) => button.text() === '新建设备')!.trigger('click')
    await created.get('[data-testid="device-address"] input').setValue('192.0.2.88')
    await created.get('[data-testid="ssh-username"] input').setValue('admin')
    await flushPromises()
    expect(created.get('[data-testid="form-connection-disabled-reason"]').text()).toContain('缺少认证信息')

    await created.get('[data-testid="ssh-password"] input').setValue('temporary-secret')
    await flushPromises()
    expect((created.get('[data-testid="form-connection-test"]').element as HTMLButtonElement).disabled).toBe(false)

    await created.get('[data-testid="ssh-port"] input').setValue('0')
    await flushPromises()
    expect(created.get('[data-testid="form-connection-disabled-reason"]').text()).toContain('有效的 SSH 端口')

    await created.get('[data-testid="ssh-enabled"] input').setValue(false)
    await flushPromises()
    expect((created.get('[data-testid="form-connection-test"]').element as HTMLButtonElement).disabled).toBe(true)
    created.unmount()
  })

  it('keeps task submission successful when task refresh fails', async () => {
    const wrapper = await renderView()
    await openEdit(wrapper)
    mocks.taskStore!.refresh.mockRejectedValueOnce(new Error('task store unavailable'))

    await wrapper.get('[data-testid="form-connection-test"]').trigger('click')
    await flushPromises()

    expect(mocks.startDeviceFormConnectionTest).toHaveBeenCalled()
    expect(mocks.messages.warning).toHaveBeenCalledWith('连接测试任务已提交，但任务状态刷新失败；可使用“打开任务窗口”继续查看')
    expect(mocks.messages.error).not.toHaveBeenCalledWith('表单连接测试任务提交失败')
    expect(mocks.messages.success).not.toHaveBeenCalledWith('SSH 表单连接测试任务已提交')
    expect(mocks.openTaskWindow).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('confirms batch refresh, locks the button and uses the selected snapshot', async () => {
    let resolveBatch!: (value: { action: string; tasks: Array<{ task_id: string; task_status: string; action: string; message: string }> }) => void
    const batchPromise = new Promise<{ action: string; tasks: Array<{ task_id: string; task_status: string; action: string; message: string }> }>((resolve) => {
      resolveBatch = resolve
    })
    mocks.startBatchRefreshDetails.mockReturnValue(batchPromise)
    const secondRow = { ...listItem, device_uuid: 'device-2', name: 'MR3' }
    mocks.listDevices.mockResolvedValue({ items: [listItem, secondRow], groups: [{ id: 1, name: '车载 MR' }], total: 2, page: 1, page_size: 50, total_pages: 1 })
    const wrapper = await renderView()

    await wrapper.get('[data-testid="select-first-device"]').trigger('click')
    const batchButton = wrapper.get('[data-testid="batch-refresh-details"]')
    expect((batchButton.element as HTMLButtonElement).disabled).toBe(false)
    await batchButton.trigger('click')
    await flushPromises()

    expect(mocks.startBatchRefreshDetails).toHaveBeenCalledWith(['device-1'])
    expect((batchButton.element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.get('[data-testid="select-second-device"]').trigger('click')
    resolveBatch({
      action: 'batch_refresh_details',
      tasks: [{ task_id: 'task-batch-1', task_status: 'PENDING', action: 'device.inventory.collect', message: '' }],
    })
    await flushPromises()

    expect(mocks.startBatchRefreshDetails).toHaveBeenCalledTimes(1)
    expect(mocks.openTaskWindow).toHaveBeenCalledWith(expect.objectContaining({ taskId: 'task-batch-1', module: 'devices' }))
    expect(mocks.messages.info).toHaveBeenCalledWith('正在提交 1 台设备详情更新任务...')
    expect(mocks.messages.success).toHaveBeenCalledWith('已提交 1 台设备详情刷新任务')
    wrapper.unmount()
  })

  it('consumes the public diagnostic artifact capability for save, open and reveal', async () => {
    mocks.taskStore!.tasks = [task({
      id: 'diagnostic-1',
      type: 'device_diagnostic_download',
      name: '设备诊断',
      status: 'COMPLETED',
      artifact_download: {
        artifact_id: 'artifact-1',
        api_path: '/api/device-management/diagnostics/diagnostic-1/download',
        query: { artifact_id: 'artifact-1' },
        display_name: '设备诊断信息.zip',
      },
    })]
    const wrapper = await renderView()
    const save = wrapper.findAll('button').find((button) => button.text() === '另存 Artifact')
    expect(save).toBeTruthy()
    await save!.trigger('click')
    await flushPromises()

    expect(mocks.downloadBackendResource).toHaveBeenCalledWith({
      apiPath: '/api/device-management/diagnostics/diagnostic-1/download',
      query: { artifact_id: 'artifact-1' },
      suggestedName: '设备诊断信息.zip',
    })
    await wrapper.findAll('button').find((button) => button.text() === '打开文件')!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === '所在目录')!.trigger('click')
    expect(mocks.openPath).toHaveBeenCalledWith('8a02d34f-ec8f-4c17-9a8a-b266bdf9e137')
    expect(mocks.showItemInFolder).toHaveBeenCalledWith('8a02d34f-ec8f-4c17-9a8a-b266bdf9e137')
    wrapper.unmount()
  })
})
