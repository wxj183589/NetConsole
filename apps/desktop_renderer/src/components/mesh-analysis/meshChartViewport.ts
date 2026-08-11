import { MIN_TIME_CHART_VIEWPORT_SPAN_MS } from '../charts/multiSeriesTimeChart'

export type MeshChartViewportSource = 'user_zoom' | 'programmatic' | 'initial'
export type MeshRssiChartSource = 'active-rssi' | 'trackside-rssi' | 'timeline-metric' | 'programmatic'
export type MeshViewportBoundaryMode = 'sample' | 'absolute'
export const MIN_MESH_VIEWPORT_SPAN_MS = MIN_TIME_CHART_VIEWPORT_SPAN_MS

export interface MeshSharedTimeDomain {
  full_start_time: string
  full_end_time: string
}

export interface MeshSharedPointerChange {
  time: string | null
  source_chart: Exclude<MeshRssiChartSource, 'programmatic'>
}

export interface MeshChartViewport {
  start_time: string
  end_time: string
  start_percent: number
  end_percent: number
  full_start_time: string
  full_end_time: string
  source: MeshChartViewportSource
  source_chart?: MeshRssiChartSource
  revision?: number
}

export interface MeshChartHandle {
  getViewport: () => MeshChartViewport | null
  applyViewport: (viewport: MeshChartViewport) => void
  resetViewport: () => void
  resize: () => void
  getVisibleTimeRange: () => MeshChartViewport | null
}

interface DataZoomValues {
  start?: number
  end?: number
  startValue?: string | number
  endValue?: string | number
}

export interface MeshViewportNormalizationOptions {
  boundaryMode?: MeshViewportBoundaryMode
  fullDomain?: MeshSharedTimeDomain | null
  sourceChart?: MeshRssiChartSource
  revision?: number
}

export function meshTimestampMillis(value: string | number | null | undefined): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const text = String(value || '').trim()
  if (!text) return null
  const parsed = Date.parse(/^\d{4}-\d{2}-\d{2} /.test(text) ? text.replace(' ', 'T') : text)
  return Number.isFinite(parsed) ? parsed : null
}

function orderedTimestamps(values: string[]): Array<{ value: string; millis: number }> {
  const unique = new Map<string, number>()
  for (const value of values) {
    const millis = meshTimestampMillis(value)
    if (millis !== null) unique.set(value, millis)
  }
  return [...unique.entries()]
    .map(([value, millis]) => ({ value, millis }))
    .sort((left, right) => left.millis - right.millis || left.value.localeCompare(right.value))
}

function percent(value: number, start: number, end: number): number {
  if (end <= start) return value <= start ? 0 : 100
  return Math.min(100, Math.max(0, ((value - start) / (end - start)) * 100))
}

export function formatMeshViewportTimestamp(value: number): string {
  const date = new Date(value)
  const pad = (number: number, size = 2): string => String(number).padStart(size, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`
}

export function enforceMinimumMeshViewport(
  viewport: MeshChartViewport,
  domain: MeshSharedTimeDomain = viewport,
  minimumSpanMs = MIN_MESH_VIEWPORT_SPAN_MS,
): MeshChartViewport | null {
  const fullStart = meshTimestampMillis(domain.full_start_time)
  const fullEnd = meshTimestampMillis(domain.full_end_time)
  const requestedStart = meshTimestampMillis(viewport.start_time)
  const requestedEnd = meshTimestampMillis(viewport.end_time)
  if (
    fullStart === null
    || fullEnd === null
    || requestedStart === null
    || requestedEnd === null
    || fullStart >= fullEnd
    || requestedStart > requestedEnd
  ) return null

  const boundedMinimum = Math.max(0, minimumSpanMs)
  const fullSpan = fullEnd - fullStart
  let start = Math.min(fullEnd, Math.max(fullStart, requestedStart))
  let end = Math.min(fullEnd, Math.max(fullStart, requestedEnd))
  if (fullSpan <= boundedMinimum) {
    start = fullStart
    end = fullEnd
  } else if (end - start < boundedMinimum) {
    const center = (start + end) / 2
    start = center - boundedMinimum / 2
    end = center + boundedMinimum / 2
    if (start < fullStart) {
      end += fullStart - start
      start = fullStart
    }
    if (end > fullEnd) {
      start -= end - fullEnd
      end = fullEnd
    }
  }
  if (start >= end) return null

  return {
    ...viewport,
    start_time: start === requestedStart ? viewport.start_time : formatMeshViewportTimestamp(start),
    end_time: end === requestedEnd ? viewport.end_time : formatMeshViewportTimestamp(end),
    start_percent: percent(start, fullStart, fullEnd),
    end_percent: percent(end, fullStart, fullEnd),
    full_start_time: domain.full_start_time,
    full_end_time: domain.full_end_time,
  }
}

function boundaryFromValue(
  value: string | number | undefined,
  points: Array<{ value: string; millis: number }>,
  side: 'start' | 'end',
): string | null {
  if (value === undefined || value === null || !points.length) return null
  const target = meshTimestampMillis(value)
  if (target === null) return null
  if (side === 'start') return (points.find((point) => point.millis >= target) || points.at(-1))?.value || null
  return ([...points].reverse().find((point) => point.millis <= target) || points[0])?.value || null
}

function boundaryFromPercent(
  value: number | undefined,
  points: Array<{ value: string; millis: number }>,
  side: 'start' | 'end',
): string | null {
  if (value === undefined || !Number.isFinite(value) || !points.length) return null
  const first = points[0].millis
  const last = points.at(-1)!.millis
  const target = first + (last - first) * Math.min(100, Math.max(0, value)) / 100
  return boundaryFromValue(target, points, side)
}

function dataZoomValues(raw: unknown): DataZoomValues {
  const event = (raw || {}) as DataZoomValues & { batch?: DataZoomValues[] }
  return event.batch?.[0] || event
}

export function meshDataZoomRequiresCorrection(
  raw: unknown,
  viewport: MeshChartViewport,
): boolean {
  const values = dataZoomValues(raw)
  const fullStart = meshTimestampMillis(viewport.full_start_time)
  const fullEnd = meshTimestampMillis(viewport.full_end_time)
  const boundary = (
    direct: string | number | undefined,
    percentage: number | undefined,
  ): number | null => {
    const parsed = meshTimestampMillis(direct)
    if (parsed !== null) return parsed
    if (
      percentage === undefined
      || !Number.isFinite(percentage)
      || fullStart === null
      || fullEnd === null
    ) return null
    return fullStart + (fullEnd - fullStart) * Math.min(100, Math.max(0, percentage)) / 100
  }
  const start = boundary(values.startValue, values.start)
  const end = boundary(values.endValue, values.end)
  const normalizedStart = meshTimestampMillis(viewport.start_time)
  const normalizedEnd = meshTimestampMillis(viewport.end_time)
  return Boolean(
    start !== null
    && end !== null
    && normalizedStart !== null
    && normalizedEnd !== null
    && (Math.abs(start - normalizedStart) >= 0.5 || Math.abs(end - normalizedEnd) >= 0.5),
  )
}

export function createFullMeshViewport(
  timestamps: string[],
  source: MeshChartViewportSource = 'initial',
): MeshChartViewport | null {
  const points = orderedTimestamps(timestamps)
  if (!points.length) return null
  return {
    start_time: points[0].value,
    end_time: points.at(-1)!.value,
    start_percent: 0,
    end_percent: 100,
    full_start_time: points[0].value,
    full_end_time: points.at(-1)!.value,
    source,
  }
}

export function createFullMeshViewportFromDomain(
  domain: MeshSharedTimeDomain,
  source: MeshChartViewportSource = 'initial',
  sourceChart: MeshRssiChartSource = 'programmatic',
  revision = 0,
): MeshChartViewport | null {
  const fullStart = meshTimestampMillis(domain.full_start_time)
  const fullEnd = meshTimestampMillis(domain.full_end_time)
  if (fullStart === null || fullEnd === null || fullStart >= fullEnd) return null
  return {
    start_time: domain.full_start_time,
    end_time: domain.full_end_time,
    start_percent: 0,
    end_percent: 100,
    full_start_time: domain.full_start_time,
    full_end_time: domain.full_end_time,
    source,
    source_chart: sourceChart,
    revision,
  }
}

export function resolveMeshSharedTimeDomain(
  preferredStart: string | null | undefined,
  preferredEnd: string | null | undefined,
  fallbackTimestamps: string[] = [],
): MeshSharedTimeDomain | null {
  const start = meshTimestampMillis(preferredStart)
  const end = meshTimestampMillis(preferredEnd)
  if (start !== null && end !== null && start < end) {
    return {
      full_start_time: String(preferredStart),
      full_end_time: String(preferredEnd),
    }
  }
  const points = orderedTimestamps(fallbackTimestamps)
  if (points.length < 2 || points[0].millis >= points.at(-1)!.millis) return null
  return {
    full_start_time: points[0].value,
    full_end_time: points.at(-1)!.value,
  }
}

export function meshViewportRangeEquals(
  left: MeshChartViewport | null | undefined,
  right: MeshChartViewport | null | undefined,
): boolean {
  return Boolean(
    left
    && right
    && left.start_time === right.start_time
    && left.end_time === right.end_time
    && left.full_start_time === right.full_start_time
    && left.full_end_time === right.full_end_time,
  )
}

export function acceptMeshSharedViewport(
  current: MeshChartViewport | null,
  incoming: MeshChartViewport,
  domain: MeshSharedTimeDomain,
  revision: number,
): MeshChartViewport | null {
  const normalized = normalizeMeshViewport(incoming, [], incoming.source, {
    boundaryMode: 'absolute',
    fullDomain: domain,
    sourceChart: incoming.source_chart || 'programmatic',
    revision,
  })
  if (!normalized) return current
  if (meshViewportRangeEquals(current, normalized)) return current
  return {
    ...normalized,
    source_chart: incoming.source_chart || 'programmatic',
    revision,
  }
}

export function normalizeMeshViewport(
  viewport: MeshChartViewport,
  timestamps: string[],
  source: MeshChartViewportSource = viewport.source,
  options: MeshViewportNormalizationOptions = {},
): MeshChartViewport | null {
  const requestedStart = meshTimestampMillis(viewport.start_time)
  const requestedEnd = meshTimestampMillis(viewport.end_time)
  if (requestedStart === null || requestedEnd === null || requestedStart > requestedEnd) return null
  if (options.boundaryMode === 'absolute') {
    const domain = options.fullDomain || {
      full_start_time: viewport.full_start_time,
      full_end_time: viewport.full_end_time,
    }
    const fullStart = meshTimestampMillis(domain.full_start_time)
    const fullEnd = meshTimestampMillis(domain.full_end_time)
    if (fullStart === null || fullEnd === null || fullStart >= fullEnd) return null
    const startMillis = Math.min(fullEnd, Math.max(requestedStart, fullStart))
    const endMillis = Math.max(fullStart, Math.min(requestedEnd, fullEnd))
    return enforceMinimumMeshViewport({
      start_time: startMillis === requestedStart ? viewport.start_time : formatMeshViewportTimestamp(startMillis),
      end_time: endMillis === requestedEnd ? viewport.end_time : formatMeshViewportTimestamp(endMillis),
      start_percent: percent(startMillis, fullStart, fullEnd),
      end_percent: percent(endMillis, fullStart, fullEnd),
      full_start_time: domain.full_start_time,
      full_end_time: domain.full_end_time,
      source,
      source_chart: options.sourceChart ?? viewport.source_chart,
      revision: options.revision ?? viewport.revision,
    }, domain)
  }
  const points = orderedTimestamps(timestamps)
  if (!points.length) return enforceMinimumMeshViewport({ ...viewport, source })

  const fullStart = points[0].millis
  const fullEnd = points.at(-1)!.millis
  const startTime = boundaryFromValue(Math.max(requestedStart, fullStart), points, 'start')
  const endTime = boundaryFromValue(Math.min(requestedEnd, fullEnd), points, 'end')
  if (!startTime || !endTime) return null
  let startMillis = meshTimestampMillis(startTime)!
  let endMillis = meshTimestampMillis(endTime)!
  let resolvedStart = startTime
  let resolvedEnd = endTime
  if (startMillis >= endMillis) {
    const index = points.findIndex((point) => point.value === startTime)
    const left = points[Math.max(0, index - 1)]
    const right = points[Math.min(points.length - 1, index + 1)]
    if (left.millis >= right.millis) return null
    resolvedStart = left.value
    resolvedEnd = right.value
    startMillis = left.millis
    endMillis = right.millis
  }
  return enforceMinimumMeshViewport({
    start_time: resolvedStart,
    end_time: resolvedEnd,
    start_percent: percent(startMillis, fullStart, fullEnd),
    end_percent: percent(endMillis, fullStart, fullEnd),
    full_start_time: points[0].value,
    full_end_time: points.at(-1)!.value,
    source,
  })
}

export function viewportFromDataZoom(raw: unknown, timestamps: string[]): MeshChartViewport | null {
  return viewportFromDataZoomWithOptions(raw, timestamps)
}

export function viewportFromDataZoomWithOptions(
  raw: unknown,
  timestamps: string[],
  options: MeshViewportNormalizationOptions = {},
): MeshChartViewport | null {
  if (options.boundaryMode === 'absolute' && options.fullDomain) {
    const full = createFullMeshViewportFromDomain(
      options.fullDomain,
      'user_zoom',
      options.sourceChart,
      options.revision,
    )
    if (!full) return null
    const values = dataZoomValues(raw)
    const fullStart = meshTimestampMillis(full.full_start_time)!
    const fullEnd = meshTimestampMillis(full.full_end_time)!
    const valueFromZoom = (
      direct: string | number | undefined,
      percentage: number | undefined,
      fallback: string,
    ): string => {
      if (direct !== undefined) {
        if (typeof direct === 'string') return direct
        if (meshTimestampMillis(direct) !== null) return formatMeshViewportTimestamp(direct)
      }
      if (percentage !== undefined && Number.isFinite(percentage)) {
        const bounded = Math.min(100, Math.max(0, percentage))
        return formatMeshViewportTimestamp(fullStart + (fullEnd - fullStart) * bounded / 100)
      }
      return fallback
    }
    return normalizeMeshViewport({
      ...full,
      start_time: valueFromZoom(values.startValue, values.start, full.start_time),
      end_time: valueFromZoom(values.endValue, values.end, full.end_time),
      source: 'user_zoom',
    }, [], 'user_zoom', options)
  }
  const points = orderedTimestamps(timestamps)
  if (points.length < 2) return createFullMeshViewport(timestamps, 'user_zoom')
  const values = dataZoomValues(raw)
  const startTime = boundaryFromValue(values.startValue, points, 'start')
    || boundaryFromPercent(values.start, points, 'start')
    || points[0].value
  const endTime = boundaryFromValue(values.endValue, points, 'end')
    || boundaryFromPercent(values.end, points, 'end')
    || points.at(-1)!.value
  return normalizeMeshViewport({
    start_time: startTime,
    end_time: endTime,
    start_percent: values.start ?? 0,
    end_percent: values.end ?? 100,
    full_start_time: points[0].value,
    full_end_time: points.at(-1)!.value,
    source: 'user_zoom',
  }, timestamps, 'user_zoom')
}

export function visibleMeshSamples<T extends { timestamp: string }>(items: T[], viewport: MeshChartViewport): T[] {
  const start = meshTimestampMillis(viewport.start_time)
  const end = meshTimestampMillis(viewport.end_time)
  if (start === null || end === null) return []
  return items.filter((item) => {
    const value = meshTimestampMillis(item.timestamp)
    return value !== null && value >= start && value <= end
  })
}
