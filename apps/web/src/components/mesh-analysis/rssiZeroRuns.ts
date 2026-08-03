import type { MeshRssiZeroRun } from '../../types/meshAnalysis'

export interface RssiDisplaySource<T> {
  timestamp: string
  value: number | null
  meta: T
  zeroRun?: MeshRssiZeroRun | null
  breakBefore?: boolean
}

export interface RssiDisplayPoint<T> {
  timestamp: string
  value: number | null
  meta: T
  zeroRun: MeshRssiZeroRun | null
  breakBefore: boolean
  syntheticEnd: boolean
}

export function buildRssiDisplayPoints<T>(
  source: readonly RssiDisplaySource<T>[],
): RssiDisplayPoint<T>[] {
  const result: RssiDisplayPoint<T>[] = []
  let pendingBreak = false

  for (const point of source) {
    pendingBreak ||= Boolean(point.breakBefore)
    const zeroRun = point.zeroRun ?? null
    if (zeroRun?.state === 'suppressed') continue
    if (zeroRun?.state === 'sustained' && zeroRun.boundary === 'middle') continue

    if (zeroRun?.state === 'sustained' && zeroRun.boundary === 'end') {
      result.push({
        timestamp: zeroRun.end_time,
        value: 0,
        meta: point.meta,
        zeroRun,
        breakBefore: pendingBreak,
        syntheticEnd: zeroRun.end_time !== point.timestamp,
      })
      pendingBreak = false
      continue
    }

    result.push({
      timestamp: point.timestamp,
      value: point.value,
      meta: point.meta,
      zeroRun,
      breakBefore: pendingBreak,
      syntheticEnd: false,
    })
    pendingBreak = false

    if (
      zeroRun?.state === 'sustained'
      && zeroRun.boundary === 'single'
      && zeroRun.end_time !== point.timestamp
    ) {
      result.push({
        timestamp: zeroRun.end_time,
        value: 0,
        meta: point.meta,
        zeroRun,
        breakBefore: false,
        syntheticEnd: true,
      })
    }
  }

  return result
}
