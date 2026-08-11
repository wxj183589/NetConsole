// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TracksideFrameDetailPanel from './TracksideFrameDetailPanel.vue'
import type { PinnedTracksideFrame, TracksideTooltipEntry } from './tracksideTooltip'

function entry(index: number): TracksideTooltipEntry {
  return {
    seriesId: `series-${index}`,
    metaId: index,
    apName: `AP-${String(index).padStart(2, '0')}`,
    radio: index % 2 + 1,
    role: index === 0 ? 'ACTIVE' : 'STANDBY',
    tracksideRssi: 37 + index,
    mrRssi: 31 + index,
    station: '16-徐家漕长乐',
    section: null,
    activeDurationSeconds: index === 0 ? 5.856 : null,
    color: `rgb(${index}, 100, 200)`,
    rssiZeroRun: null,
  }
}

function frame(count = 13): PinnedTracksideFrame {
  return {
    timestamp: '2024-10-22 14:40:15.181',
    timestampMillis: Date.parse('2024-10-22 14:40:15.181'),
    entries: Array.from({ length: count }, (_, index) => entry(index)),
  }
}

describe('TracksideFrameDetailPanel', () => {
  it('shows every frame entry, role counts, and compact business fields', () => {
    const wrapper = mount(TracksideFrameDetailPanel, {
      props: { frame: frame(), outsideRange: true },
    })

    expect(wrapper.findAll('.trackside-frame-detail-entry')).toHaveLength(13)
    expect(wrapper.text()).toContain('采样时间：2024-10-22 14:40:15.181')
    expect(wrapper.text()).toContain('ACTIVE 1 条 · STANDBY 12 条 · 共 13 条')
    expect(wrapper.text()).toContain('轨旁 / MR RSSI：37 / 31')
    expect(wrapper.text()).toContain('站点 / 区间：16-徐家漕长乐 / —')
    expect(wrapper.text()).toContain('主链持续：5.856 s')
    expect(wrapper.text()).toContain('当前固定采样位于可见范围外')
    expect(wrapper.text()).not.toMatch(/Peer Radio MAC|Peer MAC|数据来源|dBm|series_id|run_id|link_id/i)
  })

  it('emits AP selection and close while containing wheel events', async () => {
    const wrapper = mount(TracksideFrameDetailPanel, {
      attachTo: document.body,
      props: { frame: frame(2) },
    })
    const parentWheel = vi.fn()
    wrapper.element.parentElement?.addEventListener('wheel', parentWheel)

    await wrapper.findAll('.trackside-frame-detail-entry__ap')[1].trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({
      seriesId: 'series-1',
      metaId: 1,
    })
    await wrapper.get('.trackside-frame-detail-panel__close').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.trigger('wheel')
    expect(parentWheel).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows sustained-zero timing in a pinned frame without a normal RSSI 0 row', () => {
    const zeroEntry = {
      ...entry(0),
      tracksideRssi: 0,
      rssiZeroRun: {
        state: 'sustained' as const,
        boundary: 'single' as const,
        start_time: '2026-07-24 20:41:21.000',
        end_time: '2026-07-24 20:41:25.000',
        duration_ms: 4_000,
        sample_count: 1,
        estimated_end: false,
      },
    }
    const wrapper = mount(TracksideFrameDetailPanel, {
      props: { frame: { ...frame(1), entries: [zeroEntry] } },
    })

    expect(wrapper.text()).toContain('状态：持续无有效 RSSI')
    expect(wrapper.text()).toContain('结束时间：2026-07-24 20:41:25.000')
    expect(wrapper.text()).not.toContain('轨旁 / MR RSSI：0')
  })
})
