// @vitest-environment happy-dom

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import ConfigDiffViewer from './ConfigDiffViewer.vue'
import type { SharedConfigDiffModel } from './configDiffTypes'

vi.mock('./ConfigMonacoDiff.vue', () => ({
  default: {
    props: ['originalText', 'modifiedText', 'originalLabel', 'modifiedLabel'],
    emits: ['ready', 'initializationError'],
    template: '<div data-testid="shared-monaco">{{ originalLabel }}|{{ modifiedLabel }}</div>',
  },
}))

describe('ConfigDiffViewer', () => {
  it('renders identical and empty configuration states without business dependencies', async () => {
    const identical = mountViewer(model({ original: 'same', modified: 'same', rows: [] }))
    expect(identical.get('[data-testid="shared-monaco"]').text()).toBe('left|right')
    identical.unmount()

    const empty = mountViewer(model({ original: '', modified: '', rows: [] }))
    await empty.findAll('button')[1].trigger('click')
    expect(empty.text()).toContain('配置内容为空')
    empty.unmount()
  })

  it('falls back to structured rows for oversized documents', () => {
    const wrapper = mountViewer(model({
      original: 'x'.repeat(4_000_001),
      modified: '',
      rows: [{
        originalLine: 1,
        originalText: 'old',
        modifiedLine: 1,
        modifiedText: 'new',
        status: 'modified',
      }],
    }))

    expect(wrapper.text()).toContain('配置内容过大')
    expect(wrapper.find('[data-testid="shared-monaco"]').exists()).toBe(false)
    expect(wrapper.get('[aria-label="配置差异双栏视图"]').text()).toContain('old')
    wrapper.unmount()
  })
})

function model(input: {
  original: string
  modified: string
  rows: SharedConfigDiffModel['rows']
}): SharedConfigDiffModel {
  return {
    comparisonId: 'test',
    original: { label: 'left', content: input.original },
    modified: { label: 'right', content: input.modified },
    summary: { added: 0, removed: 0, modified: 0 },
    rows: input.rows,
  }
}

function mountViewer(value: SharedConfigDiffModel) {
  return mount(ConfigDiffViewer, {
    props: { model: value },
    global: {
      stubs: {
        ElAlert: { props: ['title'], template: '<div>{{ title }}</div>' },
        ElButton: { template: '<button><slot /></button>' },
        ElButtonGroup: { template: '<div><slot /></div>' },
        ElCheckbox: { template: '<label><slot /></label>' },
        ElSelect: { template: '<div><slot /></div>' },
        ElOption: { template: '<span />' },
      },
    },
  })
}
