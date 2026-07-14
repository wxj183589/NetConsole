import { apiRequest } from './client'
import type {
  MeshAlignment, MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshApStatistics, MeshArtifact,
  MeshChannelBusy, MeshLinkDetail, MeshRawSource, MeshRawTail, MeshRssi, MeshSessionDetail, MeshSwitchEvent,
  MeshTimelineItem, Page,
} from '../types/meshAnalysis'

const root = '/api/rail-transit/mesh-analysis'

function qs(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== null && value !== undefined) params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const getMeshAnalysisSummary = (): Promise<MeshAnalysisSummary> => apiRequest(`${root}/summary`)
export const listMeshAnalysisSessions = (values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshAnalysisSession>> => apiRequest(`${root}/sessions${qs(values)}`)
export const getMeshAnalysisSession = (id: string): Promise<MeshSessionDetail> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}`)
export const listMeshLinks = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshLinkDetail>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/links${qs(values)}`)
export const getMeshTimeline = (id: string): Promise<{ items: MeshTimelineItem[]; total: number }> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/timeline`)
export const listMeshSwitchEvents = (id: string): Promise<Page<MeshSwitchEvent>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/switch-events`)
export const getMeshRssi = (id: string): Promise<MeshRssi> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/rssi`)
export const getMeshChannelBusy = (id: string): Promise<{ items: MeshChannelBusy[]; total: number; downsampled: boolean }> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/channel-busy`)
export const listMeshAnomalies = (id: string): Promise<Page<MeshAnomaly>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/anomalies`)
export const listMeshApStatistics = (id: string): Promise<Page<MeshApStatistics>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/ap-statistics`)
export const getMeshAlignment = (id: string): Promise<MeshAlignment> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/alignment`)
export const listMeshArtifacts = (id: string): Promise<MeshArtifact[]> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/artifacts`)
export const listMeshRawSources = (id: string): Promise<MeshRawSource[]> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/raw-sources`)
export const getMeshRawTail = (id: string, sourceId: string): Promise<MeshRawTail> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/raw-sources/${encodeURIComponent(sourceId)}/tail`)
export const meshArtifactDownloadUrl = (id: string, artifactId: string): string => `${root}/sessions/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}/download`
