export const MESH_FULL_RECORD_LIMIT = 50_000

export function initialMeshResolution(recordCount: number | null | undefined): 'full' | 'overview' {
  return recordCount != null && recordCount <= MESH_FULL_RECORD_LIMIT ? 'full' : 'overview'
}

export function meshWindowResolution(mode: 'full' | 'high' | 'overview', isFullRange: boolean): 'full' | 'high' | 'overview' {
  return isFullRange ? mode : mode === 'full' ? 'full' : 'high'
}
