import { apiRequest } from './client'
import type {
  MeshAnalysisSession, MeshAnalysisSummary, MeshAnomaly, MeshArtifact,
  MeshActiveBuildOrder, MeshChannelBusy, MeshCounterDeltaPage, MeshLinkDetail, MeshPathChart, MeshRawSource, MeshRawTail, MeshRatePage, MeshRssi, MeshSessionDetail, MeshSwitchEvent,
  MeshTimelineItem, MeshProfile, MeshImportContext, MeshImportContextPrepare, MeshBundleImportRequest, MeshBundlePreview, MeshAnalysisParams, MeshTracksideSignalChartData, MeshAnalysisOverview, Page,
  MeshLocalScanResult, MeshLocalScanStart, MeshApCoverageAudit,
} from '../types/meshAnalysis'
import type { RailTransitTask } from '../types/railTransitWeb'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import { meshSessionPathSegment } from '../validation/opaqueIdentifier'

const root = '/api/rail-transit/mesh-analysis'

function qs(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== '' && value !== null && value !== undefined) params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export const getMeshAnalysisSummary = (): Promise<MeshAnalysisSummary> => apiRequest(`${root}/summary`)
export const getMeshAnalysisOverview = (
  values: Record<string, string | number | boolean | null | undefined>,
  signal?: AbortSignal,
): Promise<MeshAnalysisOverview> => apiRequest(
  `${root}/overview${qs(values)}`,
  signal ? { signal } : undefined,
)
export const listMeshProfiles = (): Promise<MeshProfile[]> => apiRequest(`${root}/profiles`)
export const getMeshImportContext = (): Promise<MeshImportContext> => apiRequest(`${root}/import-context`)
export const prepareMeshImportContext = (): Promise<MeshImportContextPrepare> => apiRequest(`${root}/import-context/prepare`, { method: 'POST' })
export const createMeshProfile = (payload: { display_name: string; linked_mr_id?: string; notes?: string }): Promise<MeshProfile> => apiRequest(`${root}/profiles`, { method: 'POST', body: JSON.stringify(payload) })
export function previewMeshBundle(file: File): Promise<MeshBundlePreview> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiRequest<MeshBundlePreview>(`${root}/bundles/preview`, { method: 'POST', body: form })
}
export function previewMeshImport(files: File[], signal?: AbortSignal): Promise<MeshBundlePreview> {
  const form = new FormData()
  for (const file of files) {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    form.append('files', file, relative)
  }
  return apiRequest<MeshBundlePreview>(`${root}/import-preview`, { method: 'POST', body: form, signal })
}
export const applyMeshBundleImport = (payload: MeshBundleImportRequest): Promise<RailTransitTask> => apiRequest(`${root}/bundles/import`, { method: 'POST', body: JSON.stringify(payload) })
export const startMeshLocalScan = (): Promise<MeshLocalScanStart> => apiRequest(`${root}/local-scans`, { method: 'POST' })
export const getMeshLocalScan = (scanId: string): Promise<MeshLocalScanResult> => apiRequest(`${root}/local-scans/${encodeURIComponent(scanId)}`)
export const importMeshLocalScan = (scanId: string, mappings: Array<{ candidate_id: string; profile_id: string }>): Promise<RailTransitTask> => apiRequest(
  `${root}/local-scans/${encodeURIComponent(scanId)}/import`,
  { method: 'POST', body: JSON.stringify({ mappings, explicit_confirmation: true }) },
)
export const ignoreMeshLocalScanCandidates = (scanId: string, candidateIds: string[]): Promise<MeshLocalScanResult> => apiRequest(
  `${root}/local-scans/${encodeURIComponent(scanId)}/ignore`,
  { method: 'POST', body: JSON.stringify({ candidate_ids: candidateIds }) },
)
export const openMeshLocalScanCandidateDirectory = (scanId: string, candidateId: string): Promise<{ success: boolean; code: string; message: string }> => apiRequest(
  `${root}/local-scans/${encodeURIComponent(scanId)}/candidates/${encodeURIComponent(candidateId)}/open-directory`,
  { method: 'POST' },
)
export const listMeshAnalysisSessions = (values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshAnalysisSession>> => apiRequest(`${root}/sessions${qs(values)}`)
export const auditMeshApCoverage = (sessionIds: string[]): Promise<MeshApCoverageAudit> => apiRequest(
  `${root}/ap-coverage/audit`, { method: 'POST', body: JSON.stringify({ session_ids: sessionIds }) },
)
export const exportMeshApCoverage = (sessionIds: string[]): Promise<RailTransitTask> => apiRequest(
  `${root}/ap-coverage/export`, { method: 'POST', body: JSON.stringify({ session_ids: sessionIds }) },
)
export const getMeshAnalysisSession = (id: string, signal?: AbortSignal): Promise<MeshSessionDetail> => apiRequest(
  `${root}/sessions/${meshSessionPathSegment(id)}`,
  signal ? { signal } : undefined,
)
export const rebuildMeshAnalysis = (id: string): Promise<RailTransitTask> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/rebuild`, { method: 'POST', body: JSON.stringify({ explicit_confirmation: true }) })
export const exportMeshLinkDetails = (id: string, sourceFileId: number, analysisParamsOverride?: MeshAnalysisParams): Promise<RailTransitTask> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/link-details/export`, { method: 'POST', body: JSON.stringify({ source_file_id: sourceFileId, ...(analysisParamsOverride ? { analysis_params_override: analysisParamsOverride } : {}) }) })
export const listMeshLinks = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<Page<MeshLinkDetail>> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/links${qs(values)}`)
export const listMeshActiveBuildOrder = (
  id: string,
  values: Record<string, string | number | boolean | null | undefined>,
  signal?: AbortSignal,
): Promise<Page<MeshActiveBuildOrder>> => apiRequest(
  `${root}/sessions/${meshSessionPathSegment(id)}/active-build-order${qs(values)}`,
  signal ? { signal } : undefined,
)
export const MESH_ACTIVE_PATH_QUERY_TIMEOUT_MS = 30_000
export const MESH_TRACKSIDE_SIGNAL_QUERY_TIMEOUT_MS = 60_000
export const getMeshActivePathChart = (
  id: string,
  values: Record<string, string | number | boolean | null | undefined> = {},
  signal?: AbortSignal,
): Promise<MeshPathChart> => apiRequest(
  `${root}/sessions/${meshSessionPathSegment(id)}/charts/active-path${qs(values)}`,
  { queryTimeoutMs: MESH_ACTIVE_PATH_QUERY_TIMEOUT_MS, ...(signal ? { signal } : {}) },
)
export const getMeshTracksideSignalChart = (
  id: string,
  values: Record<string, string | number | boolean | null | undefined> = {},
  signal?: AbortSignal,
): Promise<MeshTracksideSignalChartData> => apiRequest(
  `${root}/sessions/${meshSessionPathSegment(id)}/charts/trackside-signal${qs(values)}`,
  { queryTimeoutMs: MESH_TRACKSIDE_SIGNAL_QUERY_TIMEOUT_MS, ...(signal ? { signal } : {}) },
)
export const getMeshPeerSegmentChart = (id: string, values: Record<string, string | number | boolean | null | undefined>): Promise<MeshPathChart> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/charts/peer-segment${qs(values)}`)
export const getMeshTimeline = (id: string): Promise<{ items: MeshTimelineItem[]; total: number }> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/timeline`)
export const listMeshSwitchEvents = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<Page<MeshSwitchEvent>> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/switch-events${qs(values)}`)
export const getMeshRssi = (id: string): Promise<MeshRssi> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/rssi`)
export const getMeshChannelBusy = (id: string): Promise<{ items: MeshChannelBusy[]; total: number; downsampled: boolean }> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/channel-busy`)
export const getMeshRateSeries = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<MeshRatePage> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/rate-series${qs(values)}`)
export const getMeshCounterDeltas = (id: string, values: Record<string, string | number | boolean | null | undefined> = {}): Promise<MeshCounterDeltaPage> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/counter-deltas${qs(values)}`)
export const listMeshAnomalies = (id: string): Promise<Page<MeshAnomaly>> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/anomalies`)
export const listMeshArtifacts = (id: string): Promise<MeshArtifact[]> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/artifacts`)
export const deleteMeshArtifact = (id: string, artifactId: string): Promise<{ artifact_id: string; name: string; deleted_files: number }> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/artifacts/${encodeURIComponent(artifactId)}`, { method: 'DELETE', body: JSON.stringify({ explicit_confirmation: true }) })
export const getMeshAnalysisParams = (): Promise<MeshAnalysisParams> => apiRequest(`${root}/analysis-params`)
export const getMeshAnalysisParamsTemplate = (serviceType: string): Promise<MeshAnalysisParams> => apiRequest(`${root}/analysis-params/templates/${encodeURIComponent(serviceType)}`)
export const saveMeshAnalysisParams = (params: MeshAnalysisParams): Promise<MeshAnalysisParams> => apiRequest(`${root}/analysis-params`, { method: 'PUT', body: JSON.stringify({ params }) })
export const listMeshRawSources = (id: string): Promise<MeshRawSource[]> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/raw-sources`)
export const getMeshRawTail = (id: string, sourceActionId: string): Promise<MeshRawTail> => apiRequest(`${root}/sessions/${meshSessionPathSegment(id)}/raw-sources/${encodeURIComponent(sourceActionId)}/tail`)
export const deleteMeshSource = (
  id: string,
  options: { deleteRawArchive: boolean; deleteParsedData?: boolean; deleteGeneratedReports?: boolean },
): Promise<RailTransitTask> => apiRequest(
  `${root}/sources/${meshSessionPathSegment(id)}`,
  {
    method: 'DELETE',
    body: JSON.stringify({
      delete_raw_archive: options.deleteRawArchive,
      delete_parsed_data: options.deleteParsedData !== false,
      delete_generated_reports: options.deleteGeneratedReports !== false,
      explicit_confirmation: true,
    }),
  },
)
export const meshArtifactDownloadRequest = (
  id: string,
  artifactId: string,
  suggestedName: string,
): BackendDownloadRequest => ({
    apiPath: `${root}/sessions/${meshSessionPathSegment(id)}/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
})
