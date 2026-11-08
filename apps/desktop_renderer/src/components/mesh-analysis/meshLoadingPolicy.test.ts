import { describe, expect, it } from 'vitest'
import { initialMeshResolution, meshWindowResolution } from './meshLoadingPolicy'

describe('Mesh automatic resolution policy', () => {
  it.each([[0, 'full'], [50_000, 'full'], [50_001, 'overview'], [1_000_000, 'overview'], [null, 'overview'], [undefined, 'overview']] as const)(
    'selects %s records as %s', (count, expected) => expect(initialMeshResolution(count)).toBe(expected),
  )
  it('requests high resolution for a zoomed overview while honoring explicit full', () => {
    expect(meshWindowResolution('overview', true)).toBe('overview')
    expect(meshWindowResolution('overview', false)).toBe('high')
    expect(meshWindowResolution('high', false)).toBe('high')
    expect(meshWindowResolution('full', false)).toBe('full')
  })
})
