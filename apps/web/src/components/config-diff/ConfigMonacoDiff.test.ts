// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ConfigMonacoDiff from './ConfigMonacoDiff.vue'

const mocks = vi.hoisted(() => ({
  loadMonacoEditor: vi.fn(),
}))

vi.mock('../../platform/monacoEnvironment', () => ({
  loadMonacoEditor: mocks.loadMonacoEditor,
}))

interface MockModel {
  getValue: ReturnType<typeof vi.fn>
  setValue: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
}

describe('ConfigMonacoDiff', () => {
  let createDiffEditor: ReturnType<typeof vi.fn>
  let createModel: ReturnType<typeof vi.fn>
  let setTheme: ReturnType<typeof vi.fn>
  let editor: ReturnType<typeof createEditor>
  let models: MockModel[]
  let resizeDisconnect: ReturnType<typeof vi.fn>

  beforeEach(() => {
    models = []
    editor = createEditor()
    createDiffEditor = vi.fn(() => editor)
    createModel = vi.fn((value: string) => {
      let current = value
      const model: MockModel = {
        getValue: vi.fn(() => current),
        setValue: vi.fn((next: string) => {
          current = next
        }),
        dispose: vi.fn(),
      }
      models.push(model)
      return model
    })
    setTheme = vi.fn()
    mocks.loadMonacoEditor.mockResolvedValue({
      editor: { createDiffEditor, createModel, setTheme },
      Uri: { parse: vi.fn((value: string) => value) },
    })
    resizeDisconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      observe = vi.fn()
      disconnect = resizeDisconnect
    })
    document.documentElement.dataset.theme = 'light'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    document.documentElement.removeAttribute('data-theme')
  })

  it('creates one read-only diff editor and renders labels for empty text', async () => {
    const wrapper = mountComponent({ originalText: '', modifiedText: '' })
    await flushPromises()

    expect(createDiffEditor).toHaveBeenCalledTimes(1)
    expect(createDiffEditor).toHaveBeenCalledWith(expect.any(HTMLElement), expect.objectContaining({
      readOnly: true,
      originalEditable: false,
      renderSideBySide: true,
      minimap: { enabled: false },
    }))
    expect(createModel).toHaveBeenCalledTimes(2)
    expect(createModel).toHaveBeenNthCalledWith(1, '', 'plaintext', expect.stringContaining('/original.cfg'))
    expect(createModel).toHaveBeenNthCalledWith(2, '', 'plaintext', expect.stringContaining('/modified.cfg'))
    expect(editor.setModel).toHaveBeenCalledWith({ original: models[0], modified: models[1] })
    expect(wrapper.get('[data-testid="monaco-original-label"]').text()).toBe('原配置')
    expect(wrapper.get('[data-testid="monaco-modified-label"]').text()).toBe('新配置')
    expect(wrapper.emitted('ready')).toHaveLength(1)
    wrapper.unmount()
  })

  it('renders identical non-empty text and reports completed diff calculations', async () => {
    const wrapper = mountComponent({ originalText: 'same', modifiedText: 'same' })
    await flushPromises()
    editor.getLineChanges.mockReturnValue([{}])

    editor.triggerDiffUpdate()

    expect(createModel).toHaveBeenNthCalledWith(1, 'same', 'plaintext', expect.anything())
    expect(createModel).toHaveBeenNthCalledWith(2, 'same', 'plaintext', expect.anything())
    expect(wrapper.emitted('diffUpdated')).toEqual([[1]])
    wrapper.unmount()
  })

  it('updates text and display options without recreating the editor or models', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.setProps({
      originalText: 'old changed',
      modifiedText: 'new changed',
      renderSideBySide: false,
      wordWrap: true,
    })

    expect(models[0].setValue).toHaveBeenCalledWith('old changed')
    expect(models[1].setValue).toHaveBeenCalledWith('new changed')
    expect(editor.updateOptions).toHaveBeenCalledWith({ renderSideBySide: false })
    expect(editor.updateOptions).toHaveBeenCalledWith({ diffWordWrap: 'on', wordWrap: 'on' })
    expect(wrapper.emitted('layoutChange')).toEqual([[false]])
    expect(createDiffEditor).toHaveBeenCalledTimes(1)
    expect(createModel).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('replaces and releases models when the comparison identity changes', async () => {
    const wrapper = mountComponent()
    await flushPromises()

    await wrapper.setProps({ comparisonId: 'task-2' })

    expect(createDiffEditor).toHaveBeenCalledTimes(1)
    expect(createModel).toHaveBeenCalledTimes(4)
    expect(models[0].dispose).toHaveBeenCalledTimes(1)
    expect(models[1].dispose).toHaveBeenCalledTimes(1)
    expect(editor.setModel).toHaveBeenLastCalledWith({ original: models[2], modified: models[3] })
    wrapper.unmount()
  })

  it('keeps model URIs isolated across simultaneous viewer instances', async () => {
    const first = mountComponent({ comparisonId: 'same-task' })
    await flushPromises()
    const second = mountComponent({ comparisonId: 'same-task' })
    await flushPromises()

    const firstOriginalUri = createModel.mock.calls[0][2] as string
    const secondOriginalUri = createModel.mock.calls[2][2] as string
    expect(firstOriginalUri).not.toBe(secondOriginalUri)

    first.unmount()
    expect(models[0].dispose).toHaveBeenCalledTimes(1)
    expect(models[2].dispose).not.toHaveBeenCalled()
    second.unmount()
  })

  it('reveals both available lines and follows runtime theme changes', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    const exposed = wrapper.vm as unknown as {
      revealDifference: (leftLine: number | null, rightLine: number | null) => void
    }

    exposed.revealDifference(3, 4)
    exposed.revealDifference(5, null)
    expect(editor.originalEditor.revealLineInCenter).toHaveBeenCalledWith(3)
    expect(editor.originalEditor.revealLineInCenter).toHaveBeenCalledWith(5)
    expect(editor.modifiedEditor.revealLineInCenter).toHaveBeenCalledWith(4)

    document.documentElement.dataset.theme = 'dark'
    window.dispatchEvent(new CustomEvent('netconsole:theme-change'))
    expect(setTheme).toHaveBeenLastCalledWith('vs-dark')
    wrapper.unmount()
  })

  it('emits a safe failure and does not leave a partial editor', async () => {
    mocks.loadMonacoEditor.mockRejectedValueOnce(new Error('C:\\private\\worker.js'))
    const wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.text()).toContain('高级配置对比器加载失败')
    expect(wrapper.text()).not.toContain('C:\\private')
    expect(wrapper.emitted('initializationError')).toEqual([
      ['高级配置对比器加载失败，已切换到基础差异视图。'],
    ])
    expect(createDiffEditor).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('disposes the editor, current models, subscriptions and observers on unmount', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    setTheme.mockClear()

    wrapper.unmount()
    window.dispatchEvent(new CustomEvent('netconsole:theme-change'))

    expect(editor.diffSubscription.dispose).toHaveBeenCalledTimes(1)
    expect(editor.dispose).toHaveBeenCalledTimes(1)
    expect(models[0].dispose).toHaveBeenCalledTimes(1)
    expect(models[1].dispose).toHaveBeenCalledTimes(1)
    expect(resizeDisconnect).toHaveBeenCalled()
    expect(setTheme).not.toHaveBeenCalled()
  })
})

function mountComponent(overrides: Record<string, unknown> = {}) {
  return mount(ConfigMonacoDiff, {
    props: {
      originalText: 'old',
      modifiedText: 'new',
      originalLabel: '原配置',
      modifiedLabel: '新配置',
      comparisonId: 'task-1',
      ...overrides,
    },
    global: {
      stubs: {
        ElAlert: {
          props: ['title'],
          template: '<div>{{ title }}</div>',
        },
      },
    },
  })
}

function createEditor() {
  const originalEditor = {
    revealLineInCenter: vi.fn(),
    updateOptions: vi.fn(),
  }
  const modifiedEditor = {
    revealLineInCenter: vi.fn(),
    updateOptions: vi.fn(),
    focus: vi.fn(),
  }
  const diffSubscription = { dispose: vi.fn() }
  let diffListener: () => void = () => undefined
  return {
    setModel: vi.fn(),
    updateOptions: vi.fn(),
    layout: vi.fn(),
    dispose: vi.fn(),
    getLineChanges: vi.fn((): unknown[] => []),
    onDidUpdateDiff: vi.fn((listener: () => void) => {
      diffListener = listener
      return diffSubscription
    }),
    triggerDiffUpdate: () => diffListener(),
    getOriginalEditor: vi.fn(() => originalEditor),
    getModifiedEditor: vi.fn(() => modifiedEditor),
    originalEditor,
    modifiedEditor,
    diffSubscription,
  }
}
