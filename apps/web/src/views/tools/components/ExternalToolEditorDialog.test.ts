// @vitest-environment happy-dom

import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../../../api/externalTools'
import ExternalToolEditorDialog from './ExternalToolEditorDialog.vue'

vi.mock('../../../api/externalTools', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../../api/externalTools')>()
  return {
    ...original,
    selectExternalToolExecutable: vi.fn(),
    selectExternalToolWorkingDirectory: vi.fn(),
    selectExternalToolIcon: vi.fn(),
  }
})

const categories = [{
  id: 'e5057ec4-03c5-4c17-b24d-b8111ee8f942',
  name: '其他工具',
  sort_order: 10,
  builtin: true,
}]

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.selectExternalToolExecutable).mockResolvedValue({
    cancelled: false,
    path: 'C:\\Tools\\Wireshark.exe',
    suggestedName: 'Wireshark',
    workingDirectory: 'C:\\Tools',
    iconDataUrl: 'data:image/png;base64,AA==',
  })
})

describe('ExternalToolEditorDialog', () => {
  it('auto-fills the executable name and working directory from the native selector', async () => {
    const wrapper = shallowMount(ExternalToolEditorDialog, {
      props: { modelValue: true, categories },
    })
    const vm = wrapper.vm as unknown as {
      chooseExecutable(): Promise<void>
      form: { name: string; executablePath: string; workingDirectory: string }
    }
    await vm.chooseExecutable()
    expect(vm.form.name).toBe('Wireshark')
    expect(vm.form.executablePath).toBe('C:\\Tools\\Wireshark.exe')
    expect(vm.form.workingDirectory).toBe('C:\\Tools')
  })

  it('keeps the form unchanged when executable selection is cancelled', async () => {
    vi.mocked(api.selectExternalToolExecutable).mockResolvedValueOnce({ cancelled: true })
    const wrapper = shallowMount(ExternalToolEditorDialog, {
      props: { modelValue: true, categories },
    })
    const vm = wrapper.vm as unknown as {
      chooseExecutable(): Promise<void>
      form: { name: string; executablePath: string; workingDirectory: string }
    }

    await vm.chooseExecutable()

    expect(vm.form.name).toBe('')
    expect(vm.form.executablePath).toBe('')
    expect(vm.form.workingDirectory).toBe('')
    expect(wrapper.emitted('save')).toBeUndefined()
  })

  it('emits a strict argv request and rejects shell syntax before save', async () => {
    const wrapper = shallowMount(ExternalToolEditorDialog, {
      props: { modelValue: true, categories },
    })
    const vm = wrapper.vm as unknown as {
      chooseExecutable(): Promise<void>
      submit(launch: boolean): Promise<void>
      form: { argumentsText: string }
    }
    await vm.chooseExecutable()
    vm.form.argumentsText = '--profile "现场 维护"'
    await vm.submit(false)
    expect(wrapper.emitted('save')?.[0]?.[0]).toMatchObject({
      name: 'Wireshark',
      executablePath: 'C:\\Tools\\Wireshark.exe',
      arguments: ['--profile', '现场 维护'],
      workingDirectory: 'C:\\Tools',
      categoryId: categories[0].id,
    })

    const unsafe = shallowMount(ExternalToolEditorDialog, {
      props: { modelValue: true, categories },
    })
    const unsafeVm = unsafe.vm as unknown as {
      chooseExecutable(): Promise<void>
      submit(launch: boolean): Promise<void>
      form: { argumentsText: string }
    }
    await unsafeVm.chooseExecutable()
    unsafeVm.form.argumentsText = 'x && calc'
    await unsafeVm.submit(false)
    expect(unsafe.emitted('save')).toBeUndefined()
  })

  it('keeps system setting reference paths read-only and omits them from updates', async () => {
    const wrapper = shallowMount(ExternalToolEditorDialog, {
      props: {
        modelValue: true,
        categories,
        tool: {
          id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
          name: 'SecureCRT',
          source_type: 'system_setting',
          source_key: 'securecrt',
          executable_path: 'C:\\Tools\\SecureCRT.exe',
          executable_name: 'SecureCRT.exe',
          arguments: [],
          working_directory: 'C:\\Tools',
          category_id: categories[0].id,
          category_name: categories[0].name,
          favorite: true,
          sort_order: 10,
          icon_mode: 'auto',
          custom_icon_path: null,
          icon_data_url: null,
          launch_privilege: 'normal',
          launch_count: 0,
          administrator_launch_count: 0,
          last_launched_at: null,
          last_launch_mode: null,
          status: 'AVAILABLE',
          status_message: '可用',
          created_at: '2026-07-30T00:00:00.000Z',
          updated_at: '2026-07-30T00:00:00.000Z',
        },
      },
    })
    const vm = wrapper.vm as unknown as { submit(launch: boolean): Promise<void> }

    await vm.submit(false)
    expect(wrapper.emitted('save')?.[0]?.[0]).toMatchObject({
      id: '7c890030-3a3f-4d6b-b58e-7624d21daff9',
      launchPrivilege: 'normal',
      arguments: [],
    })
    expect(wrapper.emitted('save')?.[0]?.[0]).not.toHaveProperty('executablePath')
    expect(wrapper.emitted('save')?.[0]?.[0]).not.toHaveProperty('workingDirectory')
  })
})
