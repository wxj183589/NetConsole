import { describe, expect, it } from 'vitest'

import {
  createInitialMeshLoadingState,
  meshChartLabel,
  meshLoadingMessage,
  meshLoadingPhaseLabel,
  meshLoadingStateFromRenderComplete,
  meshLoadingStateFromRenderError,
  toMeshChartError,
} from './meshLoadingState'

describe('Mesh loading state helpers', () => {
  it('creates a stable initial state and phase labels', () => {
    const state = createInitialMeshLoadingState('rssi', 'QUERYING')
    expect(state).toMatchObject({ chart: 'rssi', phase: 'QUERYING', message: '正在查询数据库' })
    expect(state.updated_at).toMatch(/T/)
    expect(meshChartLabel('busy')).toBe('空口负载')
    expect(meshLoadingPhaseLabel('COMPLETED')).toBe('加载完成')
    expect(meshLoadingMessage('rssi', 'RENDERING')).toBe('主链 RSSI正在绘制图表')
    expect(meshLoadingMessage('rssi', 'ERROR', new Error('timeout'))).toBe('timeout')
  })

  it('converts render events into view state without losing errors', () => {
    const complete = meshLoadingStateFromRenderComplete({
      chart: 'trackside', phase: 'COMPLETED', point_count: 2, rendered_at: '2026-11-09T00:00:00.000Z',
    })
    expect(complete).toMatchObject({ chart: 'trackside', phase: 'COMPLETED', updated_at: '2026-11-09T00:00:00.000Z' })
    const error = meshLoadingStateFromRenderError({
      chart: 'trackside', phase: 'ERROR', error: 'timeout', failed_at: '2026-11-09T00:00:01.000Z',
    })
    expect(error).toMatchObject({ phase: 'ERROR', message: 'timeout', error: 'timeout' })
    expect(toMeshChartError(new Error('boom'))).toBe('boom')
    expect(toMeshChartError(null, 'fallback')).toBe('fallback')
  })
})
