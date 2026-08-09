import { describe, expect, it } from 'vitest'

import {
  nearestRailTimelineSample,
  railMetricToleranceMs,
  useRailTimelineController,
} from './railTimeline'

describe('rail timeline controller', () => {
  it('snapshots and restores viewport, cursor, selection, and locks without sharing objects', () => {
    const viewport = {
      start_time: '2026-07-21 15:52:00',
      end_time: '2026-07-21 15:54:00',
      start_percent: 20,
      end_percent: 60,
      full_start_time: '2026-07-21 15:50:00',
      full_end_time: '2026-07-21 15:55:00',
      source: 'user_zoom' as const,
    }
    const controller = useRailTimelineController()
    controller.setViewport(viewport)
    controller.setCursor({ time: '2026-07-21 15:52:31.600', source_chart: 'active-rssi' })
    controller.selectTime('2026-07-21 15:52:31.600', true)
    controller.timeRangeLocked.value = true

    const snapshot = controller.snapshot()
    controller.viewport.value!.start_time = 'changed'
    const restored = useRailTimelineController()
    restored.restore(snapshot)

    expect(snapshot.viewport).toEqual(viewport)
    expect(restored.snapshot()).toEqual(snapshot)
    expect(restored.viewport.value).not.toBe(snapshot.viewport)
  })

  it('keeps range locking independent from analysis-time locking', () => {
    const controller = useRailTimelineController({ timeRangeLocked: true })

    controller.selectTime('2026-07-21 15:52:31.600', false)
    expect(controller.timeRangeLocked.value).toBe(true)
    expect(controller.selectedTimeLocked.value).toBe(false)

    controller.selectedTimeLocked.value = true
    controller.timeRangeLocked.value = false
    expect(controller.selectedTimeLocked.value).toBe(true)
    expect(controller.selectedTime.value).toBe('2026-07-21 15:52:31.600')
  })
})

describe('rail timeline nearest sample', () => {
  it('derives tolerance from normal cadence and does not cross a large data gap', () => {
    const rows = [
      { time: '2026-07-21 15:52:30.000', value: 1 },
      { time: '2026-07-21 15:52:31.000', value: 2 },
      { time: '2026-07-21 16:02:31.000', value: 3 },
    ]

    expect(railMetricToleranceMs(rows.map((row) => row.time))).toBe(1_750)
    expect(nearestRailTimelineSample(rows, '2026-07-21 15:52:31.600', (row) => row.time)?.value).toBe(2)
    expect(nearestRailTimelineSample(rows, '2026-07-21 15:57:00.000', (row) => row.time)).toBeNull()
  })
})
