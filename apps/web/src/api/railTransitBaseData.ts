import { apiRequest } from './client'
import type {
  DataQualityIssue,
  DataQualityEntityGroupPage,
  ImportPreviewResult,
  Page,
  PageQuery,
  RailTransitSummary,
  Relation,
  Section,
  Station,
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
export const listStations = (values: PageQuery = {}): Promise<Page<Station>> => apiRequest(`${root}/stations${queryString(values)}`)
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
