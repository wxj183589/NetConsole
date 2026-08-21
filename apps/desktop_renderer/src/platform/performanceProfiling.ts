import { nextTick } from 'vue'

export interface ApiPerformanceProfile {
  path: string
  method: string
  totalMs: number
  requestId: string
  serverTiming: string
}

export function reportApiPerformance(profile: ApiPerformanceProfile): void {
  console.info('API_PERFORMANCE_PROFILE', {
    path: profile.path,
    method: profile.method,
    total_ms: Math.round(profile.totalMs * 100) / 100,
    request_id: profile.requestId,
    server_timing: profile.serverTiming,
  })
}

export async function reportTableRenderPerformance(
  tableId: string,
  rowCount: number,
  startedAt: number,
): Promise<void> {
  await nextTick()
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  console.info('UI_TABLE_PROFILE', {
    table_id: tableId,
    row_count: rowCount,
    render_ms: Math.round((performance.now() - startedAt) * 100) / 100,
  })
}
