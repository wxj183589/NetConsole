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

  for (const point of source) {
    const zeroRun = point.zeroRun ?? null
    result.push({
      timestamp: point.timestamp,
      // 0 在 MESH RSSI 口径中表示无有效采样。保留该链路点作为
      // Tooltip 上下文，但以 null 形成真实缺口；不得在恢复时刻
      // 合成第二个 0 点，避免与真实恢复样本重复归属。
      value: zeroRun ? null : point.value,
      meta: point.meta,
      zeroRun,
      breakBefore: Boolean(point.breakBefore),
      syntheticEnd: false,
    })
  }

  return result
}
