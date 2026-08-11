import { describe, expect, it } from 'vitest'

import { MAX_MESH_SWITCH_OVERLAY_ITEMS, sampleMeshSwitchOverlayItems } from './switchOverlayBudget'

describe('sampleMeshSwitchOverlayItems', () => {
  it('keeps all events below the visual budget', () => {
    expect(sampleMeshSwitchOverlayItems([1, 2, 3])).toEqual([1, 2, 3])
  })

  it('keeps the first and last event while spreading a large overlay', () => {
    const items = Array.from({ length: 8_490 }, (_, index) => index)
    const result = sampleMeshSwitchOverlayItems(items)

    expect(result).toHaveLength(MAX_MESH_SWITCH_OVERLAY_ITEMS)
    expect(result[0]).toBe(0)
    expect(result.at(-1)).toBe(items.at(-1))
    expect(new Set(result).size).toBe(result.length)
  })
})
