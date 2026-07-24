interface MeshAnalysisInstanceState {
  chartActive: boolean
  conflictEdgeCount: number
  detailRequestActive: boolean
  tracksideCacheActive: boolean
  tracksideReserved: boolean
}

export interface MeshAnalysisRuntimeSnapshot {
  activeDetailRequests: number
  chartDisposeCount: number
  chartInitCount: number
  conflictEdgeCount: number
  meshInstanceCount: number
  tracksideCacheBuildCount: number
  tracksideCacheCount: number
  tracksideCacheDisposeCount: number
  tracksideChartCount: number
}

const instances = new Map<symbol, MeshAnalysisInstanceState>()
let tracksideCacheBuildCount = 0
let tracksideCacheDisposeCount = 0
let chartInitCount = 0
let chartDisposeCount = 0

export function registerMeshAnalysisInstance(): symbol {
  const token = Symbol('mesh-analysis-instance')
  instances.set(token, {
    chartActive: false,
    conflictEdgeCount: 0,
    detailRequestActive: false,
    tracksideCacheActive: false,
    tracksideReserved: false,
  })
  return token
}

export function unregisterMeshAnalysisInstance(token: symbol): void {
  instances.delete(token)
}

export function reserveTracksideCache(token: symbol, limit: number): boolean {
  const state = instances.get(token)
  if (!state) return false
  if (state.tracksideCacheActive || state.tracksideReserved) return true
  const allocated = [...instances.values()].filter((item) => (
    item.tracksideCacheActive || item.tracksideReserved
  )).length
  if (allocated >= limit) return false
  state.tracksideReserved = true
  return true
}

export function setMeshDetailRequestActive(token: symbol, active: boolean): void {
  const state = instances.get(token)
  if (state) state.detailRequestActive = active
}

export function setTracksideCacheActive(token: symbol, active: boolean): void {
  const state = instances.get(token)
  if (!state) return
  if (active && !state.tracksideCacheActive) tracksideCacheBuildCount += 1
  if (!active && state.tracksideCacheActive) tracksideCacheDisposeCount += 1
  state.tracksideCacheActive = active
  state.tracksideReserved = false
  if (!active) state.conflictEdgeCount = 0
}

export function releaseTracksideReservation(token: symbol): void {
  const state = instances.get(token)
  if (state) state.tracksideReserved = false
}

export function setTracksideChartActive(token: symbol, active: boolean): void {
  const state = instances.get(token)
  if (!state || state.chartActive === active) return
  state.chartActive = active
  if (active) chartInitCount += 1
  else chartDisposeCount += 1
}

export function setTracksideConflictEdgeCount(token: symbol, count: number): void {
  const state = instances.get(token)
  if (state) state.conflictEdgeCount = Math.max(0, Math.trunc(count))
}

export function meshAnalysisRuntimeSnapshot(): MeshAnalysisRuntimeSnapshot {
  const states = [...instances.values()]
  return {
    activeDetailRequests: states.filter((state) => state.detailRequestActive).length,
    chartDisposeCount,
    chartInitCount,
    conflictEdgeCount: states.reduce((total, state) => total + state.conflictEdgeCount, 0),
    meshInstanceCount: states.length,
    tracksideCacheBuildCount,
    tracksideCacheCount: states.filter((state) => state.tracksideCacheActive).length,
    tracksideCacheDisposeCount,
    tracksideChartCount: states.filter((state) => state.chartActive).length,
  }
}
