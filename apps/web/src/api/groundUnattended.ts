import { apiRequest } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  GroundActionResponse, GroundArchive, GroundDeepCollection, GroundPage, GroundPingTarget,
  GroundProfile, GroundStatus, GroundTimelineEvent, GroundTrain,
} from '../types/groundUnattended'

const root = '/api/rail-transit/ground-unattended'

export const getGroundStatus = (): Promise<GroundStatus> => apiRequest(`${root}/status`)
export const getGroundProfile = (): Promise<GroundProfile> => apiRequest(`${root}/profile`)
export const saveGroundProfile = (value: GroundProfile): Promise<GroundProfile> => apiRequest(`${root}/profile`, { method: 'PUT', body: JSON.stringify(value) })
export const startGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/start`, { method: 'POST' })
export const pauseGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/pause`, { method: 'POST' })
export const resumeGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/resume`, { method: 'POST' })
export const stopGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop`, { method: 'POST' })
export const stopAndArchiveGroundRun = (): Promise<GroundActionResponse> => apiRequest(`${root}/stop-and-archive`, { method: 'POST' })
export const listGroundTrains = (): Promise<GroundPage<GroundTrain>> => apiRequest(`${root}/trains`)
export const getGroundTrain = (trainId: string): Promise<GroundTrain> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}`)
export const setGroundTrainPriority = (trainId: string, priority: boolean): Promise<GroundTrain> => apiRequest(`${root}/trains/${encodeURIComponent(trainId)}/priority`, { method: 'PUT', body: JSON.stringify({ priority }) })
export const listGroundPingTargets = (): Promise<GroundPage<GroundPingTarget>> => apiRequest(`${root}/ping-targets`)
export const listGroundDeepCollections = (): Promise<GroundPage<GroundDeepCollection>> => apiRequest(`${root}/deep-collections`)
export function listGroundTimeline(trainId = '', eventType = ''): Promise<GroundPage<GroundTimelineEvent>> {
  const params = new URLSearchParams()
  if (trainId) params.set('train_id', trainId)
  if (eventType) params.set('event_type', eventType)
  return apiRequest(`${root}/timeline?${params}`)
}
export const listGroundArchives = (): Promise<GroundPage<GroundArchive>> => apiRequest(`${root}/archives`)
export const getGroundArchive = (archiveId: string): Promise<GroundArchive> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`)
export const deleteGroundArchive = (archiveId: string): Promise<GroundActionResponse> => apiRequest(`${root}/archives/${encodeURIComponent(archiveId)}`, { method: 'DELETE', body: JSON.stringify({ explicit_confirmation: true }) })
export const openGroundArchiveDirectory = (): Promise<{ success: boolean; code: string; message: string }> => apiRequest(`${root}/archives/open-directory`, { method: 'POST' })
export const groundArchiveSummaryDownloadRequest = (row: GroundArchive): BackendDownloadRequest => ({
  apiPath: `${root}/archives/${encodeURIComponent(row.archive_id)}/summary-download`,
  suggestedName: `${row.run_date}_ground_unattended_summary.json`,
})
