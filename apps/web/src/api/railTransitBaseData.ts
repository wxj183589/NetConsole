import { apiRequest } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  BaseDataChange,
  BaseDataClearPreview,
  BaseDataClearResult,
  BaseDataEditSession,
  BaseDataEditSnapshot,
  BaseDataSaveResult,
  BaseDataValidationResult,
  DataQualityIssue,
  DataQualityEntityGroupPage,
  ImportApplyResult,
  ImportChange,
  ImportOperation,
  ImportPolicyStatus,
  ImportPreviewResult,
  MergeFieldDecision,
  Page,
  PageQuery,
  RailTransitSummary,
  Relation,
  Section,
  SectionGenerationPreview,
  Station,
  StationConflictPreview,
  StationDeletePreflight,
  StationSourcePreview,
  StationTemplatePreview,
  TracksideAp,
  Train,
  VehicleMr,
} from '../types/railTransitBaseData'

const root = '/api/rail-transit/base-data'

function queryString(values: PageQuery = {}): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

export const getRailTransitSummary = (): Promise<RailTransitSummary> => apiRequest(`${root}/summary`)
export const getRailTransitBaseDataEditSession = (): Promise<BaseDataEditSession> => apiRequest(`${root}/revision`)
export const getRailTransitBaseDataEditSnapshot = (): Promise<BaseDataEditSnapshot> => apiRequest(`${root}/edit-snapshot`)
export const getRailTransitBaseDataClearPreview = (): Promise<BaseDataClearPreview> => apiRequest(`${root}/clear-preview`)
export const clearRailTransitBaseData = (payload: { site_id: string; base_revision: string; explicit_confirmation: boolean }): Promise<BaseDataClearResult> => apiRequest(`${root}/clear-all`, { method: 'POST', body: JSON.stringify(payload) })
export const validateRailTransitBaseDataChanges = (payload: { site_id: string; base_revision: string; changes: BaseDataChange[] }): Promise<BaseDataValidationResult> => apiRequest(`${root}/validate`, { method: 'POST', body: JSON.stringify(payload) })
export const saveRailTransitBaseDataChanges = (payload: { site_id: string; base_revision: string; changes: BaseDataChange[]; explicit_confirmation: boolean }): Promise<BaseDataSaveResult> => apiRequest(`${root}/changes`, { method: 'POST', body: JSON.stringify(payload) })
export const listStations = (values: PageQuery = {}): Promise<Page<Station>> => apiRequest(`${root}/stations${queryString(values)}`)
export const getStationSourcePreview = (): Promise<StationSourcePreview> => apiRequest(`${root}/station-source-preview`)
export const preflightStationDeletion = (payload: { site_id: string; base_revision: string; station_ids: string[] }): Promise<StationDeletePreflight> => apiRequest(`${root}/stations/delete-preflight`, { method: 'POST', body: JSON.stringify(payload) })
export const getStationConflictPreview = (baseRevision: string): Promise<StationConflictPreview> => apiRequest(`${root}/stations/conflicts${queryString({ base_revision: baseRevision })}`)
export const listSections = (values: PageQuery = {}): Promise<Page<Section>> => apiRequest(`${root}/sections${queryString(values)}`)
export const listTracksideAps = (values: PageQuery = {}): Promise<Page<TracksideAp>> => apiRequest(`${root}/aps${queryString(values)}`)
export const listTrains = (values: PageQuery = {}): Promise<Page<Train>> => apiRequest(`${root}/trains${queryString(values)}`)
export const listVehicleMrs = (values: PageQuery = {}): Promise<Page<VehicleMr>> => apiRequest(`${root}/mrs${queryString(values)}`)
export const listDataQualityIssues = (values: PageQuery = {}): Promise<Page<DataQualityIssue>> => apiRequest(`${root}/issues${queryString(values)}`)
export const listDataQualityIssueGroups = (values: PageQuery = {}): Promise<DataQualityEntityGroupPage> => apiRequest(`${root}/issues/groups${queryString(values)}`)
export const listRelations = (values: PageQuery = {}): Promise<Page<Relation>> => apiRequest(`${root}/relations${queryString(values)}`)

export function previewRailTransitImport(file: File): Promise<ImportPreviewResult> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiRequest(`${root}/import-preview`, { method: 'POST', body: form })
}

export function previewStationTemplate(file: File): Promise<StationTemplatePreview> {
  const form = new FormData()
  form.append('file', file, file.name)
  return apiRequest(`${root}/station-template-preview`, { method: 'POST', body: form })
}

export const stationTemplateDownloadRequest = (): BackendDownloadRequest => ({
  apiPath: `${root}/station-template`,
  suggestedName: '线路站点与区间基础资料模板.xlsx',
})

export const stationTemplateExportDownloadRequest = (): BackendDownloadRequest => ({
  apiPath: `${root}/station-template-export`,
  suggestedName: '线路站点与区间基础资料.xlsx',
})

export function previewSectionGeneration(payload: {
  site_id: string
  base_revision: string
  line_metadata: {
    main_path_code: string
    increasing_direction_name: string
    decreasing_direction_name: string
    increasing_direction_line_side: string
    decreasing_direction_line_side: string
  }
  stations: Station[]
  current_sections: Section[]
}): Promise<SectionGenerationPreview> {
  return apiRequest(`${root}/section-generation-preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export const getRailTransitImportPolicies = (): Promise<ImportPolicyStatus> => apiRequest(`${root}/import-policies`)

export function applyRailTransitImport(payload: {
  preview_id: string
  site_id: string
  explicit_confirmation: boolean
  decisions: MergeFieldDecision[]
  expected_database_sha256: string
}): Promise<ImportApplyResult> {
  return apiRequest(`${root}/import-apply`, { method: 'POST', body: JSON.stringify(payload) })
}

export async function listRailTransitImportOperations(): Promise<ImportOperation[]> {
  const page = await apiRequest<Page<ImportOperation>>(`${root}/import-operations`)
  return page.items
}

export async function listRailTransitImportChanges(operationId: string): Promise<ImportChange[]> {
  const page = await apiRequest<Page<ImportChange>>(`${root}/import-operations/${encodeURIComponent(operationId)}/changes`)
  return page.items
}

export function rollbackRailTransitImport(operationId: string): Promise<{ operation_id: string; status: string; rolled_back_at: string }> {
  return apiRequest(`${root}/import-operations/${encodeURIComponent(operationId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ explicit_confirmation: true }),
  })
}
