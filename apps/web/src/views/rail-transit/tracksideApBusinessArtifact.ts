import { ElMessage } from 'element-plus'

import { tracksideApBusinessDownloadRequest } from '../../api/tracksideApBusiness'
import { downloadBackendResource } from '../../platform/runtime'
import type { BackendDownloadResult } from '../../../../desktop_electron/src/shared/bridge'

export const TRACKSIDE_AP_BUSINESS_EXPORT_ACTION = 'trackside_ap_business_export'
export const TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE = 'web_export_trackside_ap_business'

export interface TracksideApBusinessArtifactLike {
  action?: string
  type?: string
  status?: string
  available?: boolean
  artifact_id?: string
  artifact_download?: { artifact_id: string } | null
}

export function isTracksideApBusinessArtifactTask(task: TracksideApBusinessArtifactLike | null | undefined): boolean {
  return Boolean(task && (task.action === TRACKSIDE_AP_BUSINESS_EXPORT_ACTION || task.type === TRACKSIDE_AP_BUSINESS_EXPORT_TASK_TYPE))
}

export function tracksideApBusinessArtifactId(target: TracksideApBusinessArtifactLike | string | null | undefined): string {
  if (typeof target === 'string') return target.trim()
  return String(target?.artifact_id || target?.artifact_download?.artifact_id || '').trim()
}

export async function saveTracksideApBusinessArtifact(
  target: TracksideApBusinessArtifactLike | string | null | undefined,
): Promise<BackendDownloadResult> {
  const artifactId = tracksideApBusinessArtifactId(target)
  if (!artifactId) {
    const error = '轨旁 AP 业务表格 Artifact 不可用'
    ElMessage.error(error)
    return { status: 'failed', error }
  }
  try {
    const result = await downloadBackendResource(tracksideApBusinessDownloadRequest(artifactId))
    if (result.status === 'saved') ElMessage.success('轨旁 AP 业务表格已保存')
    else if (result.status === 'started') ElMessage.success('浏览器已开始下载')
    else if (result.status === 'failed') ElMessage.error(result.error || '轨旁 AP 业务表格保存失败')
    return result
  } catch (reason) {
    const error = reason instanceof Error ? reason.message : '轨旁 AP 业务表格保存失败'
    ElMessage.error(error)
    return { status: 'failed', error }
  }
}
