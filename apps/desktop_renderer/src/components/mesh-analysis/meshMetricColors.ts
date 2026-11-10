export const MESH_SIDE_COLORS = Object.freeze({
  local: '#22c55e',
  peer: '#f97316',
})

export function meshSideColor(side: 'local' | 'peer'): string {
  return MESH_SIDE_COLORS[side]
}
