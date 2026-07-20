export type MeshChartViewportSource = 'user_zoom' | 'programmatic' | 'initial'

export interface MeshChartViewport {
  start_time: string
  end_time: string
  start_percent: number
  end_percent: number
  full_start_time: string
  full_end_time: string
  source: MeshChartViewportSource
}

export interface MeshChartHandle {
  getViewport: () => MeshChartViewport | null
  applyViewport: (viewport: MeshChartViewport) => void
  resetViewport: () => void
  getVisibleTimeRange: () => MeshChartViewport | null
}

interface DataZoomValues {
  start?: number
  end?: number
  startValue?: string | number
  endValue?: string | number
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

export function normalizeMeshViewport(
  viewport: MeshChartViewport,
  timestamps: string[],
  source: MeshChartViewportSource = viewport.source,
): MeshChartViewport | null {
  const points = orderedTimestamps(timestamps)
  const requestedStart = meshTimestampMillis(viewport.start_time)
  const requestedEnd = meshTimestampMillis(viewport.end_time)
  if (requestedStart === null || requestedEnd === null || requestedStart >= requestedEnd) return null
  if (!points.length) return { ...viewport, source }

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
  return {
    start_time: resolvedStart,
    end_time: resolvedEnd,
    start_percent: percent(startMillis, fullStart, fullEnd),
    end_percent: percent(endMillis, fullStart, fullEnd),
    full_start_time: points[0].value,
    full_end_time: points.at(-1)!.value,
    source,
  }
}

export function viewportFromDataZoom(raw: unknown, timestamps: string[]): MeshChartViewport | null {
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
