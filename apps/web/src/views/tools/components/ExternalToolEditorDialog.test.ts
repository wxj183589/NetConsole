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
})
