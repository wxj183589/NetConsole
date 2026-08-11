import { ref, type Ref } from 'vue'

import type {
  MeshChartViewport,
  MeshRssiChartSource,
  MeshSharedPointerChange,
  MeshSharedTimeDomain,
} from '../mesh-analysis/meshChartViewport'
import { createFullMeshViewportFromDomain, formatMeshViewportTimestamp, meshTimestampMillis } from '../mesh-analysis/meshChartViewport'

export interface RailTimelineSnapshot {
  viewport: MeshChartViewport | null
  cursorTime: string | null
  cursorSource: MeshRssiChartSource | null
  selectedTime: string | null
  timeRangeLocked: boolean
  selectedTimeLocked: boolean
}

export interface RailTimelineController {
  viewport: Ref<MeshChartViewport | null>
  cursorTime: Ref<string | null>
  cursorSource: Ref<MeshRssiChartSource | null>
  selectedTime: Ref<string | null>
  timeRangeLocked: Ref<boolean>
  selectedTimeLocked: Ref<boolean>
  setViewport: (value: MeshChartViewport | null) => void
  setCursor: (value: MeshSharedPointerChange | null) => void
  selectTime: (value: string | null, locked?: boolean) => void
  focusTime: (value: string, domain: MeshSharedTimeDomain | null, windowMs?: number) => void
  restore: (value: Partial<RailTimelineSnapshot>) => void
  snapshot: () => RailTimelineSnapshot
  reset: () => void
}

export function useRailTimelineController(
  initial: Partial<RailTimelineSnapshot> = {},
): RailTimelineController {
  const viewport = ref<MeshChartViewport | null>(initial.viewport || null)
  const cursorTime = ref<string | null>(initial.cursorTime || null)
  const cursorSource = ref<MeshRssiChartSource | null>(initial.cursorSource || null)
  const selectedTime = ref<string | null>(initial.selectedTime || null)
  const timeRangeLocked = ref(Boolean(initial.timeRangeLocked))
  const selectedTimeLocked = ref(Boolean(initial.selectedTimeLocked))

  function setViewport(value: MeshChartViewport | null): void {
    viewport.value = value ? { ...value } : null
  }

  function setCursor(value: MeshSharedPointerChange | null): void {
    cursorTime.value = value?.time || null
    cursorSource.value = value?.time ? value.source_chart : null
  }

  function selectTime(value: string | null, locked = true): void {
    selectedTime.value = value
    selectedTimeLocked.value = Boolean(value && locked)
  }

  function focusTime(value: string, domain: MeshSharedTimeDomain | null, windowMs = 30_000): void {
    selectTime(value, true)
    cursorTime.value = value
    cursorSource.value = 'programmatic'
    if (timeRangeLocked.value || !domain) return
    const full = createFullMeshViewportFromDomain(domain, 'programmatic', 'programmatic')
    const selected = meshTimestampMillis(value)
    const start = meshTimestampMillis(domain.full_start_time)
    const end = meshTimestampMillis(domain.full_end_time)
    if (!full || selected === null || start === null || end === null || start >= end) return
    const requestedStart = Math.max(start, selected - windowMs)
    const requestedEnd = Math.min(end, selected + windowMs)
    const span = end - start
    const boundedStart = requestedEnd - requestedStart < Math.min(windowMs * 2, span)
      ? Math.max(start, Math.min(selected - windowMs, end - Math.min(windowMs * 2, span)))
      : requestedStart
    const boundedEnd = requestedEnd - requestedStart < Math.min(windowMs * 2, span)
      ? Math.min(end, boundedStart + Math.min(windowMs * 2, span))
      : requestedEnd
    setViewport({
      ...full,
      start_time: formatMeshViewportTimestamp(boundedStart),
      end_time: formatMeshViewportTimestamp(boundedEnd),
      start_percent: ((boundedStart - start) / span) * 100,
      end_percent: ((boundedEnd - start) / span) * 100,
    })
  }

  function restore(value: Partial<RailTimelineSnapshot>): void {
    if ('viewport' in value) setViewport(value.viewport || null)
    if ('cursorTime' in value) cursorTime.value = value.cursorTime || null
    if ('cursorSource' in value) cursorSource.value = value.cursorSource || null
    if ('selectedTime' in value) selectedTime.value = value.selectedTime || null
    if ('timeRangeLocked' in value) timeRangeLocked.value = Boolean(value.timeRangeLocked)
    if ('selectedTimeLocked' in value) selectedTimeLocked.value = Boolean(value.selectedTimeLocked)
  }

  function snapshot(): RailTimelineSnapshot {
    return {
      viewport: viewport.value ? { ...viewport.value } : null,
      cursorTime: cursorTime.value,
      cursorSource: cursorSource.value,
      selectedTime: selectedTime.value,
      timeRangeLocked: timeRangeLocked.value,
      selectedTimeLocked: selectedTimeLocked.value,
    }
  }

  function reset(): void {
    restore({
      viewport: null,
      cursorTime: null,
      cursorSource: null,
      selectedTime: null,
      timeRangeLocked: false,
      selectedTimeLocked: false,
    })
  }

  return {
    viewport,
    cursorTime,
    cursorSource,
    selectedTime,
    timeRangeLocked,
    selectedTimeLocked,
    setViewport,
    setCursor,
    selectTime,
    focusTime,
    restore,
    snapshot,
    reset,
  }
}

export function railTimestampMillis(value: string | null | undefined): number | null {
  const normalized = String(value || '').trim()
  if (!normalized) return null
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2} /.test(normalized) ? normalized.replace(' ', 'T') : normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function railMetricToleranceMs(timestamps: Array<string | null | undefined>): number {
  const ordered = timestamps
    .map(railTimestampMillis)
    .filter((value): value is number => value !== null)
    .sort((left, right) => left - right)
  const deltas = ordered.slice(1)
    .map((value, index) => value - ordered[index])
    .filter((value) => value > 0 && value <= 60_000)
    .sort((left, right) => left - right)
  const middle = deltas.length ? deltas[Math.floor(deltas.length / 2)] : 1_000
  return Math.min(15_000, Math.max(1_500, middle * 1.75))
}

export function nearestRailTimelineSample<T>(
  rows: T[],
  selectedTime: string | null | undefined,
  timestamp: (row: T) => string | null | undefined,
  toleranceMs = railMetricToleranceMs(rows.map(timestamp)),
): T | null {
  const selected = railTimestampMillis(selectedTime)
  if (selected === null) return null
  let nearest: T | null = null
  let nearestDistance = Number.POSITIVE_INFINITY
  for (const row of rows) {
    const candidate = railTimestampMillis(timestamp(row))
    if (candidate === null) continue
    const distance = Math.abs(candidate - selected)
    if (distance < nearestDistance) {
      nearest = row
      nearestDistance = distance
    }
  }
  return nearestDistance <= toleranceMs ? nearest : null
}
