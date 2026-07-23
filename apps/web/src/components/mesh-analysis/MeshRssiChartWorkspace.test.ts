// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, onBeforeUnmount } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { loadUiPreference, saveUiPreference } from '../../platform/uiPreferences'
import MeshRssiChartWorkspace from './MeshRssiChartWorkspace.vue'
import {
  normalizeMeshRssiLayoutMode,
  normalizeMeshRssiSplitRatio,
  resolveMeshRssiCompareLayout,
} from './meshRssiLayout'

describe('Mesh RSSI chart workspace', () => {
  beforeEach(() => {
    localStorage.clear()
    let frameId = 0
    const cancelledFrames = new Set<number>()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = ++frameId
      queueMicrotask(() => {
        if (!cancelledFrames.has(id)) callback(0)
      })
      return id
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => cancelledFrames.add(id))
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    })
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('fits both panes in one 2K workspace and uses limited internal scroll when short', () => {
    for (const height of [900, 1_060]) {
      const layout = resolveMeshRssiCompareLayout(height, 0.5)
      expect(layout.activePaneHeight).toBeGreaterThanOrEqual(300)
      expect(layout.tracksidePaneHeight).toBeGreaterThanOrEqual(300)
      expect(
        layout.activePaneHeight + layout.tracksidePaneHeight + 8,
      ).toBe(height)
      expect(layout.scrollable).toBe(false)
    }

    const short = resolveMeshRssiCompareLayout(560, 0.25)
    expect(short.minimumPaneHeight).toBe(240)
    expect(short.activePaneHeight).toBeGreaterThanOrEqual(240)
    expect(short.tracksidePaneHeight).toBeGreaterThanOrEqual(240)
    expect(short.scrollable).toBe(false)

    const veryShort = resolveMeshRssiCompareLayout(420, 0.75)
    expect(veryShort.innerHeight).toBe(488)
    expect(veryShort.scrollable).toBe(true)
  })

  it('keeps both slot trees mounted across the three layout modes', async () => {
    const unmounted = vi.fn()
    const PersistentPane = defineComponent({
      props: { name: { type: String, required: true } },
      setup(props) {
        onBeforeUnmount(unmounted)
        return () => h('div', { 'data-pane-child': props.name }, props.name)
      },
    })
    const wrapper = mount(MeshRssiChartWorkspace, {
      props: { mode: 'compare', splitRatio: 0.5, workspaceHeight: 900 },
      slots: {
        active: () => h(PersistentPane, { name: 'active' }),
        trackside: () => h(PersistentPane, { name: 'trackside' }),
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-rssi-pane="active"]').isVisible()).toBe(true)
    expect(wrapper.find('[data-rssi-pane="trackside"]').isVisible()).toBe(true)
    await wrapper.setProps({ mode: 'active-focus' })
    expect(wrapper.find('[data-rssi-pane="active"]').attributes('style') ?? '').not.toContain('display: none')
    expect(wrapper.find('[data-rssi-pane="trackside"]').attributes('style') ?? '').toContain('display: none')
    await wrapper.setProps({ mode: 'trackside-focus' })
    expect(wrapper.find('[data-rssi-pane="active"]').attributes('style') ?? '').toContain('display: none')
    expect(wrapper.find('[data-rssi-pane="trackside"]').attributes('style') ?? '').not.toContain('display: none')
    expect(unmounted).not.toHaveBeenCalled()

    wrapper.unmount()
    expect(unmounted).toHaveBeenCalledTimes(2)
  })

  it('reflows vertically when the available window height changes', async () => {
    const wrapper = mount(MeshRssiChartWorkspace, {
      props: { mode: 'compare', splitRatio: 0.5, workspaceHeight: 900 },
      slots: { active: '<div />', trackside: '<div />' },
    })
    expect(wrapper.find('.mesh-rssi-workspace__canvas').attributes('style')).toContain(
      'grid-template-rows: 446px 8px 446px',
    )

    await wrapper.setProps({ workspaceHeight: 420 })
    expect(wrapper.find('.mesh-rssi-workspace__canvas').attributes('style')).toContain(
      'grid-template-rows: 240px 8px 240px',
    )
    expect(wrapper.attributes('data-scrollable')).toBe('true')
    await flushPromises()
    expect(wrapper.emitted('resize')?.length).toBeGreaterThan(0)
    wrapper.unmount()
  })

  it('coalesces pointer drag, clamps the ratio and resets on double click', async () => {
    const setPointerCapture = vi.fn()
    const releasePointerCapture = vi.fn()
    const hasPointerCapture = vi.fn(() => true)
    Object.defineProperties(HTMLElement.prototype, {
      setPointerCapture: { configurable: true, value: setPointerCapture },
      releasePointerCapture: { configurable: true, value: releasePointerCapture },
      hasPointerCapture: { configurable: true, value: hasPointerCapture },
    })
    const wrapper = mount(MeshRssiChartWorkspace, {
      props: { mode: 'compare', splitRatio: 0.5, workspaceHeight: 1_208 },
      slots: { active: '<div />', trackside: '<div />' },
    })
    const canvas = wrapper.find('.mesh-rssi-workspace__canvas').element as HTMLElement
    canvas.getBoundingClientRect = () => ({
      x: 0,
      y: 100,
      top: 100,
      left: 0,
      right: 1_000,
      bottom: 1_308,
      width: 1_000,
      height: 1_208,
      toJSON: () => ({}),
    })
    const splitter = wrapper.find('.mesh-rssi-workspace__splitter')
    await splitter.trigger('pointerdown', { button: 0, pointerId: 7, clientY: 704 })
    await splitter.trigger('pointermove', { pointerId: 7, clientY: -1_000 })
    await splitter.trigger('pointerup', { pointerId: 7, clientY: -1_000 })

    expect(setPointerCapture).toHaveBeenCalledWith(7)
    expect(wrapper.emitted('update:splitRatio')?.at(-1)).toEqual([0.25])
    expect(releasePointerCapture).toHaveBeenCalledWith(7)
    await splitter.trigger('dblclick')
    expect(wrapper.emitted('update:splitRatio')?.at(-1)).toEqual([0.5])
    expect(wrapper.emitted('resize')?.length).toBeGreaterThan(0)
    await splitter.trigger('pointerdown', { button: 0, pointerId: 8, clientY: 704 })
    wrapper.unmount()
    expect(releasePointerCapture).toHaveBeenLastCalledWith(8)
  })

  it('validates browser fallback preferences before restoring them', async () => {
    await saveUiPreference('mesh-analysis-rssi.layout-mode', 'trackside-focus')
    await saveUiPreference('mesh-analysis-rssi.compare-split-ratio', 0.65)
    expect(normalizeMeshRssiLayoutMode(
      await loadUiPreference('mesh-analysis-rssi.layout-mode', 'compare'),
    )).toBe('trackside-focus')
    expect(normalizeMeshRssiSplitRatio(
      await loadUiPreference('mesh-analysis-rssi.compare-split-ratio', 0.5),
    )).toBe(0.65)

    await saveUiPreference('mesh-analysis-rssi.layout-mode', 'fullscreen')
    await saveUiPreference('mesh-analysis-rssi.compare-split-ratio', 0.9)
    expect(normalizeMeshRssiLayoutMode(
      await loadUiPreference('mesh-analysis-rssi.layout-mode', 'compare'),
    )).toBe('compare')
    expect(normalizeMeshRssiSplitRatio(
      await loadUiPreference('mesh-analysis-rssi.compare-split-ratio', 0.5),
    )).toBe(0.5)
  })
})
