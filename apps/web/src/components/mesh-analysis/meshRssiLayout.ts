export const MESH_RSSI_LAYOUT_MODES = [
  'compare',
  'active-focus',
  'trackside-focus',
] as const

export type MeshRssiLayoutMode = typeof MESH_RSSI_LAYOUT_MODES[number]

export const DEFAULT_MESH_RSSI_LAYOUT_MODE: MeshRssiLayoutMode = 'compare'
export const DEFAULT_MESH_RSSI_SPLIT_RATIO = 0.5
export const MIN_MESH_RSSI_SPLIT_RATIO = 0.35
export const MAX_MESH_RSSI_SPLIT_RATIO = 0.65
export const MESH_RSSI_SPLITTER_SIZE = 8
export const MIN_MESH_RSSI_PANE_HEIGHT = 320
export const MIN_LARGE_MESH_RSSI_PANE_HEIGHT = 400
export const LARGE_MESH_RSSI_WORKSPACE_HEIGHT = (
  MIN_LARGE_MESH_RSSI_PANE_HEIGHT * 2 + MESH_RSSI_SPLITTER_SIZE
)

export interface MeshRssiCompareLayout {
  workspaceHeight: number
  innerHeight: number
  activePaneHeight: number
  tracksidePaneHeight: number
  minimumPaneHeight: number
  minimumRatio: number
  maximumRatio: number
  splitRatio: number
  scrollable: boolean
}

export function normalizeMeshRssiLayoutMode(value: unknown): MeshRssiLayoutMode {
  return MESH_RSSI_LAYOUT_MODES.includes(value as MeshRssiLayoutMode)
    ? value as MeshRssiLayoutMode
    : DEFAULT_MESH_RSSI_LAYOUT_MODE
}

export function normalizeMeshRssiSplitRatio(value: unknown): number {
  return typeof value === 'number'
    && Number.isFinite(value)
    && value >= MIN_MESH_RSSI_SPLIT_RATIO
    && value <= MAX_MESH_RSSI_SPLIT_RATIO
    ? value
    : DEFAULT_MESH_RSSI_SPLIT_RATIO
}

export function resolveMeshRssiCompareLayout(
  workspaceHeight: number,
  requestedRatio: unknown,
): MeshRssiCompareLayout {
  const height = Number.isFinite(workspaceHeight)
    ? Math.max(0, Math.floor(workspaceHeight))
    : 0
  const minimumPaneHeight = height >= LARGE_MESH_RSSI_WORKSPACE_HEIGHT
    ? MIN_LARGE_MESH_RSSI_PANE_HEIGHT
    : MIN_MESH_RSSI_PANE_HEIGHT
  const minimumInnerHeight = minimumPaneHeight * 2 + MESH_RSSI_SPLITTER_SIZE
  const innerHeight = Math.max(height, minimumInnerHeight)
  const paneSpace = innerHeight - MESH_RSSI_SPLITTER_SIZE
  const minimumRatio = Math.max(
    MIN_MESH_RSSI_SPLIT_RATIO,
    minimumPaneHeight / paneSpace,
  )
  const maximumRatio = Math.min(
    MAX_MESH_RSSI_SPLIT_RATIO,
    1 - minimumPaneHeight / paneSpace,
  )
  const splitRatio = Math.min(
    maximumRatio,
    Math.max(minimumRatio, normalizeMeshRssiSplitRatio(requestedRatio)),
  )
  const activePaneHeight = Math.round(paneSpace * splitRatio)

  return {
    workspaceHeight: height,
    innerHeight,
    activePaneHeight,
    tracksidePaneHeight: paneSpace - activePaneHeight,
    minimumPaneHeight,
    minimumRatio,
    maximumRatio,
    splitRatio,
    scrollable: innerHeight > height,
  }
}
