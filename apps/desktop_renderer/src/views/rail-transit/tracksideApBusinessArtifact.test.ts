import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  isTracksideApBusinessArtifactTask,
  saveTracksideApBusinessArtifact,
  TRACKSIDE_AP_BUSINESS_EXPORT_ACTION,
  TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE,
  tracksideApBusinessArtifactId,
} from './tracksideApBusinessArtifact'

const platformMocks = vi.hoisted(() => ({
  download: vi.fn(),
}))
const messageMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}))

vi.mock('../../platform/runtime', () => ({
  downloadBackendResource: platformMocks.download,
}))

vi.mock('element-plus', () => ({
  ElMessage: messageMocks,
}))

describe('trackside AP business artifact helper', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('recognizes page tasks and job-center tasks and resolves the artifact id', () => {
    expect(isTracksideApBusinessArtifactTask({ action: TRACKSIDE_AP_BUSINESS_EXPORT_ACTION })).toBe(true)
    expect(isTracksideApBusinessArtifactTask({ type: TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE })).toBe(true)
    expect(isTracksideApBusinessArtifactTask({ action: 'trackside_ap_optical_update' })).toBe(false)
    expect(tracksideApBusinessArtifactId({ artifact_download: { artifact_id: 'artifact-1' } })).toBe('artifact-1')
  })

  it('uses the business download endpoint and reports saved or browser-started states', async () => {
    platformMocks.download.mockResolvedValueOnce({ status: 'saved', capabilityId: 'cap-1' })
    const saved = await saveTracksideApBusinessArtifact({
      artifact_id: 'artifact / 1',
      artifact_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })

    expect(platformMocks.download).toHaveBeenCalledWith({
      apiPath: '/api/rail-transit/trackside-ap-business/artifacts/artifact%20%2F%201/download',
      suggestedName: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(saved).toEqual({ status: 'saved', capabilityId: 'cap-1' })
    expect(messageMocks.success).toHaveBeenCalledWith('轨旁 AP 业务表格已保存')

    platformMocks.download.mockResolvedValueOnce({ status: 'started' })
    await saveTracksideApBusinessArtifact({
      artifact_id: 'artifact-2',
      artifact_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(messageMocks.success).toHaveBeenCalledWith('浏览器已开始下载')
  })

  it('does not report cancellation and surfaces failed or thrown errors', async () => {
    platformMocks.download.mockResolvedValueOnce({ status: 'cancelled' })
    await saveTracksideApBusinessArtifact({
      artifact_id: 'artifact-3',
      artifact_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(messageMocks.error).not.toHaveBeenCalled()

    platformMocks.download.mockResolvedValueOnce({ status: 'failed', error: '磁盘空间不足' })
    await saveTracksideApBusinessArtifact({
      artifact_id: 'artifact-4',
      artifact_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(messageMocks.error).toHaveBeenCalledWith('磁盘空间不足')

    platformMocks.download.mockRejectedValueOnce(new Error('下载桥不可用'))
    const thrown = await saveTracksideApBusinessArtifact({
      artifact_id: 'artifact-5',
      artifact_name: '宁波地铁12号线_轨旁AP业务_20260721_234501.xlsx',
    })
    expect(thrown).toEqual({ status: 'failed', error: '下载桥不可用' })
    expect(messageMocks.error).toHaveBeenCalledWith('下载桥不可用')
  })
})
