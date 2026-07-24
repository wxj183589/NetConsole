import { afterEach, describe, expect, it } from 'vitest'

import {
  meshAnalysisRuntimeSnapshot,
  registerMeshAnalysisInstance,
  reserveTracksideCache,
  setMeshDetailRequestActive,
  setTracksideCacheActive,
  setTracksideChartActive,
  unregisterMeshAnalysisInstance,
} from './meshAnalysisRuntime'

const tokens: symbol[] = []

afterEach(() => {
  for (const token of tokens.splice(0)) unregisterMeshAnalysisInstance(token)
})

describe('MESH analysis runtime budget', () => {
  it('limits a renderer to two reserved or live trackside caches', () => {
    const first = registerMeshAnalysisInstance()
    const second = registerMeshAnalysisInstance()
    const third = registerMeshAnalysisInstance()
    tokens.push(first, second, third)

    expect(reserveTracksideCache(first, 2)).toBe(true)
    setTracksideCacheActive(first, true)
    expect(reserveTracksideCache(second, 2)).toBe(true)
    expect(reserveTracksideCache(third, 2)).toBe(false)

    setTracksideCacheActive(second, true)
    setTracksideChartActive(first, true)
    setMeshDetailRequestActive(third, true)
    expect(meshAnalysisRuntimeSnapshot()).toMatchObject({
      activeDetailRequests: 1,
      meshInstanceCount: 3,
      tracksideCacheCount: 2,
      tracksideChartCount: 1,
    })

    setTracksideCacheActive(first, false)
    expect(reserveTracksideCache(third, 2)).toBe(true)
  })
})
