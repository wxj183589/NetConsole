import type { TracksideSeriesCache } from './tracksideSeriesCache'

export interface TracksideSeriesColorAssignment {
  colorBySeriesId: ReadonlyMap<string, string>
  colorIndexBySeriesId: ReadonlyMap<string, number>
  conflictsBySeriesId: ReadonlyMap<string, ReadonlySet<string>>
  conflictEdgeCount: number
  adjacencyWindowMs: number
  usedColorCount: number
  palette: readonly string[]
  conflictGraphBuildMs: number
  colorAssignmentMs: number
  totalMs: number
}

export function disposeTracksideSeriesColorAssignment(
  assignment: TracksideSeriesColorAssignment | null | undefined,
): void {
  if (!assignment) return
  for (const conflicts of assignment.conflictsBySeriesId.values()) {
    if (conflicts instanceof Set) conflicts.clear()
  }
  if (assignment.colorBySeriesId instanceof Map) assignment.colorBySeriesId.clear()
  if (assignment.colorIndexBySeriesId instanceof Map) assignment.colorIndexBySeriesId.clear()
  if (assignment.conflictsBySeriesId instanceof Map) assignment.conflictsBySeriesId.clear()
  assignment.conflictEdgeCount = 0
  assignment.usedColorCount = 0
  assignment.conflictGraphBuildMs = 0
  assignment.colorAssignmentMs = 0
  assignment.totalMs = 0
}

const TRACKSIDE_BASE_PALETTE = [
  '#2f80ed', '#27ae60', '#9b51e0', '#00a3a3',
  '#d16ba5', '#5b8ff9', '#5ad8a6', '#7b61ff',
  '#2d9cdb', '#6fcf97', '#bb6bd9', '#12b8b0',
  '#6c8ae4', '#4cb963', '#a78bfa', '#18a0ae',
  '#63b3ed', '#8fd14f', '#c084fc', '#3cc7a3',
  '#4f6fdc', '#76c442', '#b074d6', '#00b8a9',
  '#74a7f7', '#34c38f', '#8f7aea', '#45b7b0',
  '#4c9be8', '#68c987', '#ad7bd9', '#35c4c8',
] as const

interface TracksideRunInterval {
  seriesId: string
  startMillis: number
  endMillis: number
}

function compareStableText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0
}

function generatedTracksideColor(index: number): string {
  const hue = ((index + 1) * 137.508) % 360
  const saturation = [72, 84, 66, 78][Math.floor(index / 360) % 4]
  const lightness = [58, 68, 52, 72][Math.floor(index / 90) % 4]
  return `hsl(${hue.toFixed(3)}deg ${saturation}% ${lightness}%)`
}

export function createTracksideSeriesPalette(
  preferredColors: readonly string[] = [],
  excludedColors: readonly string[] = [],
  minimumSize: number = TRACKSIDE_BASE_PALETTE.length,
): string[] {
  const excluded = new Set(excludedColors.map((color) => color.trim().toLowerCase()).filter(Boolean))
  const result: string[] = []
  const seen = new Set<string>()
  const append = (color: string) => {
    const normalized = color.trim().toLowerCase()
    if (!normalized || excluded.has(normalized) || seen.has(normalized)) return
    seen.add(normalized)
    result.push(color.trim())
  }
  preferredColors.forEach(append)
  TRACKSIDE_BASE_PALETTE.forEach(append)
  let generatedIndex = 0
  while (result.length < Math.max(TRACKSIDE_BASE_PALETTE.length, minimumSize)) {
    append(generatedTracksideColor(generatedIndex))
    generatedIndex += 1
  }
  return result
}

function uniqueFrameSeriesIds(cache: TracksideSeriesCache, timestampMillis: number): string[] {
  const ids = new Set<string>()
  for (const metaId of cache.frameMetaIds.get(timestampMillis) ?? []) {
    const seriesId = cache.pointMetaById.get(metaId)?.seriesId
    if (seriesId) ids.add(seriesId)
  }
  return [...ids].sort(compareStableText)
}

function tracksideRunIntervals(cache: TracksideSeriesCache): TracksideRunInterval[] {
  return cache.series.flatMap((series) => {
    const intervals = new Map<string, TracksideRunInterval>()
    let fallbackSegment = 0
    for (const point of series.data) {
      if (point[2] < 0) {
        fallbackSegment += 1
        continue
      }
      const meta = cache.pointMetaById.get(point[2])
      if (!meta) continue
      const key = meta.runId ? `run:${meta.runId}` : `segment:${fallbackSegment}`
      const current = intervals.get(key)
      if (current) {
        current.startMillis = Math.min(current.startMillis, meta.timestampMillis)
        current.endMillis = Math.max(current.endMillis, meta.timestampMillis)
      } else {
        intervals.set(key, {
          seriesId: series.id,
          startMillis: meta.timestampMillis,
          endMillis: meta.timestampMillis,
        })
      }
    }
    return [...intervals.values()]
  }).sort((left, right) => (
    left.startMillis - right.startMillis
    || left.endMillis - right.endMillis
    || compareStableText(left.seriesId, right.seriesId)
  ))
}

function pushMinHeap(
  heap: Array<{ untilMillis: number; seriesId: string }>,
  item: { untilMillis: number; seriesId: string },
): void {
  heap.push(item)
  let index = heap.length - 1
  while (index > 0) {
    const parent = (index - 1) >>> 1
    if (heap[parent].untilMillis <= item.untilMillis) break
    heap[index] = heap[parent]
    index = parent
  }
  heap[index] = item
}

function popMinHeap(
  heap: Array<{ untilMillis: number; seriesId: string }>,
): { untilMillis: number; seriesId: string } | undefined {
  const first = heap[0]
  const last = heap.pop()
  if (!first || !last || !heap.length) return first
  let index = 0
  while (true) {
    const left = index * 2 + 1
    if (left >= heap.length) break
    const right = left + 1
    const child = right < heap.length && heap[right].untilMillis < heap[left].untilMillis ? right : left
    if (heap[child].untilMillis >= last.untilMillis) break
    heap[index] = heap[child]
    index = child
  }
  heap[index] = last
  return first
}

export function assignTracksideSeriesColors(
  cache: TracksideSeriesCache,
  palette: readonly string[],
): TracksideSeriesColorAssignment {
  const totalStarted = performance.now()
  const seriesIds = [...new Set(cache.series.map((series) => series.id))].sort(compareStableText)
  const conflicts = new Map(seriesIds.map((seriesId) => [seriesId, new Set<string>()]))
  let conflictEdgeCount = 0
  const addConflict = (left: string, right: string) => {
    if (left === right) return
    const leftConflicts = conflicts.get(left)
    const rightConflicts = conflicts.get(right)
    if (!leftConflicts || !rightConflicts || leftConflicts.has(right)) return
    leftConflicts.add(right)
    rightConflicts.add(left)
    conflictEdgeCount += 1
  }
  const addClique = (ids: readonly string[]) => {
    for (let left = 0; left < ids.length; left += 1) {
      if ((conflicts.get(ids[left])?.size ?? 0) >= seriesIds.length - 1) continue
      for (let right = left + 1; right < ids.length; right += 1) addConflict(ids[left], ids[right])
    }
  }

  const adjacencyWindowMs = Math.max(
    1_000,
    Math.min(5_000, (cache.medianFrameIntervalMs || 500) * 2),
  )
  let previousTimestamp: number | null = null
  let previousSeriesIds: string[] = []
  for (const timestamp of cache.frameTimestamps) {
    const currentSeriesIds = uniqueFrameSeriesIds(cache, timestamp)
    addClique(currentSeriesIds)
    if (previousTimestamp !== null && timestamp - previousTimestamp <= adjacencyWindowMs) {
      addClique([...new Set([...previousSeriesIds, ...currentSeriesIds])].sort(compareStableText))
    }
    previousTimestamp = timestamp
    previousSeriesIds = currentSeriesIds
  }

  const activeUntilBySeries = new Map<string, number>()
  const activeHeap: Array<{ untilMillis: number; seriesId: string }> = []
  for (const interval of tracksideRunIntervals(cache)) {
    while (activeHeap[0]?.untilMillis < interval.startMillis) {
      const expired = popMinHeap(activeHeap)
      if (expired && activeUntilBySeries.get(expired.seriesId) === expired.untilMillis) {
        activeUntilBySeries.delete(expired.seriesId)
      }
    }
    if ((conflicts.get(interval.seriesId)?.size ?? 0) < seriesIds.length - 1) {
      for (const activeSeriesId of activeUntilBySeries.keys()) {
        addConflict(interval.seriesId, activeSeriesId)
        if ((conflicts.get(interval.seriesId)?.size ?? 0) >= seriesIds.length - 1) break
      }
    }
    const untilMillis = Math.max(
      activeUntilBySeries.get(interval.seriesId) ?? Number.NEGATIVE_INFINITY,
      interval.endMillis + adjacencyWindowMs,
    )
    activeUntilBySeries.set(interval.seriesId, untilMillis)
    pushMinHeap(activeHeap, { untilMillis, seriesId: interval.seriesId })
  }

  const conflictGraphBuildMs = performance.now() - totalStarted
  const colorAssignmentStarted = performance.now()
  const firstTimestampBySeriesId = new Map(cache.series.map((series) => [
    series.id,
    series.firstTimestampMillis ?? Number.POSITIVE_INFINITY,
  ]))
  const orderedSeriesIds = [...seriesIds].sort((left, right) => (
    (conflicts.get(right)?.size ?? 0) - (conflicts.get(left)?.size ?? 0)
    || (firstTimestampBySeriesId.get(left) ?? Number.POSITIVE_INFINITY)
      - (firstTimestampBySeriesId.get(right) ?? Number.POSITIVE_INFINITY)
    || compareStableText(left, right)
  ))
  const resolvedPalette = createTracksideSeriesPalette(
    palette,
    [],
    Math.max(seriesIds.length, TRACKSIDE_BASE_PALETTE.length),
  )
  const colorIndexBySeriesId = new Map<string, number>()
  for (const seriesId of orderedSeriesIds) {
    const unavailable = new Set<number>()
    for (const neighbor of conflicts.get(seriesId) ?? []) {
      const colorIndex = colorIndexBySeriesId.get(neighbor)
      if (colorIndex !== undefined) unavailable.add(colorIndex)
    }
    let colorIndex = 0
    while (unavailable.has(colorIndex)) colorIndex += 1
    colorIndexBySeriesId.set(seriesId, colorIndex)
  }
  const colorBySeriesId = new Map(
    [...colorIndexBySeriesId].map(([seriesId, colorIndex]) => [seriesId, resolvedPalette[colorIndex]]),
  )
  const colorAssignmentMs = performance.now() - colorAssignmentStarted
  return {
    colorBySeriesId,
    colorIndexBySeriesId,
    conflictsBySeriesId: conflicts,
    conflictEdgeCount,
    adjacencyWindowMs,
    usedColorCount: new Set(colorIndexBySeriesId.values()).size,
    palette: resolvedPalette,
    conflictGraphBuildMs,
    colorAssignmentMs,
    totalMs: performance.now() - totalStarted,
  }
}
