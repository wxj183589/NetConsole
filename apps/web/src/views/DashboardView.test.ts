// @vitest-environment happy-dom

import { defineComponent, h, nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { flattenNavigation } from '../navigation/registry'
import { appRoutes } from '../router/routes'
import DashboardView from './DashboardView.vue'
import source from './DashboardView.vue?raw'
import deviceManagementSource from './devices/DeviceManagementView.vue?raw'
import fileManagementSource from './file-management/FileManagementView.vue?raw'
import jobCenterSource from './job-center/JobCenterView.vue?raw'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
}))
let warnSpy: ReturnType<typeof vi.spyOn>

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

const passthrough = defineComponent({
  inheritAttrs: false,
  setup(_props, { attrs, slots }) {
    return () => h('div', attrs, slots.default?.())
  },
})

const buttonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  setup(_props, { attrs, emit, slots }) {
    return () => h('button', { ...attrs, onClick: () => emit('click') }, slots.default?.())
  },
})

const alertStub = defineComponent({
  props: { title: String },
  setup(props, { slots }) {
    return () => h('div', [h('strong', props.title), slots.default?.()])
  },
})

async function mountView() {
  return mount(DashboardView, {
    global: {
      stubs: {
        ElAlert: alertStub,
        ElButton: buttonStub,
        ElIcon: passthrough,
        ElTag: passthrough,
      },
    },
  })
}

beforeEach(() => {
  mocks.push.mockReset()
  mocks.push.mockResolvedValue(undefined)
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
})

afterEach(() => {
  warnSpy.mockRestore()
})

describe('Dashboard home page', () => {
  it('renders the updated homepage copy and keeps the command reference button ahead of tasks', async () => {
    expect(source).toContain('当前版本功能状态')
    expect(source).toContain('已重点完善的功能')
    expect(source).toContain('当前设备适配范围')
    expect(source).toContain('测试功能与报告免责声明')
    expect(source).toContain('设备操作安全说明')
    expect(source).toContain('Comware V7、Comware V9')
    expect(source).toContain('H3C 交换机')
    expect(source).toContain('车载 MR')
    expect(source).toContain('Cloud AP')
    expect(source).toContain('查看命令说明')
    expect(source).toContain('打开任务中心')
    expect(source).toContain('不提供删除设备、重启设备等高风险设备操作命令')
    expect(source).toContain('不向 Web 页面开放任意命令执行能力')
    expect(source).not.toContain('<el-input')
    expect(source).not.toContain('<textarea')
    expect(source).not.toContain("router.push('/tasks')")
    expect(source).not.toContain('全面兼容')
    expect(source).not.toContain('完全支持')
  })

  it('navigates to the existing command reference and task center routes without a blank failure state', async () => {
    const wrapper = await mountView()
    await nextTick()
    const buttons = wrapper.findAll('button')
    expect(buttons[0].text()).toBe('查看命令说明')
    expect(buttons[1].text()).toBe('打开任务中心')

    await buttons[0].trigger('click')
    await flushPromises()
    expect(mocks.push).toHaveBeenCalledWith({ name: 'command-reference' })

    mocks.push.mockRejectedValueOnce(new Error('navigation failed'))
    await buttons[1].trigger('click')
    await flushPromises()
    expect(mocks.push).toHaveBeenCalledWith({ name: 'tasks' })
    expect(wrapper.text()).toContain('任务中心暂时无法打开')
  })

  it('keeps command reference registered once and leaves no direct CLI input surface on the dashboard', () => {
    const commandReferenceRoutes = appRoutes
      .flatMap((route) => route.children ?? [])
      .filter((route) => route.name === 'command-reference')
    expect(commandReferenceRoutes).toHaveLength(1)
    expect(flattenNavigation().filter((item) => item.navigation_id === 'command-reference')).toHaveLength(1)
    expect(source).not.toContain('命令输入框')
    expect(source).not.toContain('CLI')
  })

  it('keeps the safety statement separate from local data management actions', () => {
    expect(deviceManagementSource).toContain('deleteDevices')
    expect(deviceManagementSource).toContain('删除后设备将从当前局点数据库移除')
    expect(fileManagementSource).toContain('clearFileDownloads')
    expect(fileManagementSource).toContain("actionLabels: ['取消', '重试', '打开', '所在目录']")
    expect(jobCenterSource).toContain('requestCancel')
    expect(jobCenterSource).toContain('保存导出表格')
  })
})
