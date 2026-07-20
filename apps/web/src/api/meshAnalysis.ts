import { apiRequest } from './client'
import type {
  MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshApStatistics, MeshArtifact,
  MeshActiveBuildOrder, MeshChannelBusy, MeshCounterDeltaPage, MeshLinkDetail, MeshPathChart, MeshRawSource, MeshRawTail, MeshRatePage, MeshRssi, MeshSessionDetail, MeshSwitchEvent,
  MeshTimelineItem, MeshProfile, MeshImportContextPrepare, MeshBundleImportRequest, MeshBundlePreview, Page,
} from '../types/meshAnalysis'
import type { RailTransitTask } from '../types/railTransitWeb'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

const root = '/api/rail-transit/mesh-analysis'

function qs(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== null && value !== undefined) params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const getMeshAnalysisSummary = (): Promise<MeshAnalysisSummary> => apiRequest(`${root}/summary`)
export const listMeshProfiles = (): Promise<MeshProfile[]> => apiRequest(`${root}/profiles`)
export const prepareMeshImportContext = (): Promise<MeshImportContextPrepare> => apiRequest(`${root}/import-context/prepare`, { method: 'POST' })
export const createMeshProfile = (payload: { display_name: string; linked_mr_id?: string; notes?: string }): Promise<MeshProfile> => apiRequest(`${root}/profiles`, { method: 'POST', body: JSON.stringify(payload) })
export function previewMeshBundle(file: File): Promise<MeshBundlePreview> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiRequest<MeshBundlePreview>(`${root}/bundles/preview`, { method: 'POST', body: form })
}
export function previewMeshImport(files: File[]): Promise<MeshBundlePreview> {
  const form = new FormData()
  for (const file of files) {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    form.append('files', file, relative)
  }
  return apiRequest<MeshBundlePreview>(`${root}/import-preview`, { method: 'POST', body: form })
}
export const applyMeshBundleImport = (payload: MeshBundleImportRequest): Promise<RailTransitTask> => apiRequest(`${root}/bundles/import`, { method: 'POST', body: JSON.stringify(payload) })
export const listMeshAnalysisSessions = (values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshAnalysisSession>> => apiRequest(`${root}/sessions${qs(values)}`)
export const getMeshAnalysisSession = (id: string): Promise<MeshSessionDetail> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}`)
export const rebuildMeshAnalysis = (id: string): Promise<RailTransitTask> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/rebuild`, { method: 'POST', body: JSON.stringify({ explicit_confirmation: true }) })
export const exportMeshLinkDetails = (id: string, sourceFileId: number): Promise<RailTransitTask> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/link-details/export`, { method: 'POST', body: JSON.stringify({ source_file_id: sourceFileId }) })
export const listMeshLinks = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshLinkDetail>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/links${qs(values)}`)
export const listMeshActiveBuildOrder = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshActiveBuildOrder>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/active-build-order${qs(values)}`)
export const getMeshActivePathChart = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<MeshPathChart> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/charts/active-path${qs(values)}`)
export const getMeshPeerSegmentChart = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<MeshPathChart> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/charts/peer-segment${qs(values)}`)
export const getMeshTimeline = (id: string): Promise<{ items: MeshTimelineItem[]; total: number }> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/timeline`)
export const listMeshSwitchEvents = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<Page<MeshSwitchEvent>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/switch-events${qs(values)}`)
export const getMeshRssi = (id: string): Promise<MeshRssi> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/rssi`)
export const getMeshChannelBusy = (id: string): Promise<{ items: MeshChannelBusy[]; total: number; downsampled: boolean }> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/channel-busy`)
export const getMeshRateSeries = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<MeshRatePage> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/rate-series${qs(values)}`)
export const getMeshCounterDeltas = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<MeshCounterDeltaPage> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/counter-deltas${qs(values)}`)
export const listMeshAnomalies = (id: string): Promise<Page<MeshAnomaly>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/anomalies`)
export const listMeshApStatistics = (id: string): Promise<Page<MeshApStatistics>> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/ap-statistics`)
export const listMeshArtifacts = (id: string): Promise<MeshArtifact[]> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/artifacts`)
export const listMeshRawSources = (id: string): Promise<MeshRawSource[]> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/raw-sources`)
export const getMeshRawTail = (id: string, sourceId: string): Promise<MeshRawTail> => apiRequest(`${root}/sessions/${encodeURIComponent(id)}/raw-sources/${encodeURIComponent(sourceId)}/tail`)
export const meshArtifactDownloadRequest = (
  id: string,
  artifactId: string,
  suggestedName: string,
): BackendDownloadRequest => ({
  apiPath: `${root}/sessions/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
})
