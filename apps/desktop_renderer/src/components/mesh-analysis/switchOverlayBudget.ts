export const MAX_MESH_SWITCH_OVERLAY_ITEMS = 64

/** Keep the chart overlay readable while the table/API retains every event. */
export function sampleMeshSwitchOverlayItems<T>(
  items: readonly T[],
  limit = MAX_MESH_SWITCH_OVERLAY_ITEMS,
): T[] {
  if (limit <= 0 || !items.length) return []
  if (items.length <= limit) return [...items]
  if (limit === 1) return [items[0]]

  const selected: T[] = []
  const seen = new Set<number>()
  for (let index = 0; index < limit; index += 1) {
    const sourceIndex = Math.round((index * (items.length - 1)) / (limit - 1))
    if (seen.has(sourceIndex)) continue
    seen.add(sourceIndex)
    selected.push(items[sourceIndex])
  }
  return selected
}
