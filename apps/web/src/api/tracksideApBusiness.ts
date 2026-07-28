import { apiRequest } from './client'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type {
  TracksideApBusinessPage, TracksideApPlan, TracksideApPlanPreview, TracksideApPlanRow,
  TracksideApTask, TracksideApUpdateRequest, TracksideSwitchAdapterCatalog,
  TracksideSwitchSampleRequest,
} from '../types/tracksideApBusiness'
import type { TracksideAp } from '../types/railTransitBaseData'

const root = '/api/rail-transit/trackside-ap-business'
const invalidArtifactNamePattern = /[\u0000-\u001f\u007f<>:"/\\|?*]/
const tracksideBusinessArtifactNamePattern = /^.+_轨旁AP业务_\d{8}_\d{6}\.xlsx$/
const switchSampleArtifactNamePattern = /^[a-z0-9._-]+-adapter-sample-[a-z0-9._-]+-\d{8}_\d{6}\.zip$/i

export function listTracksideApBusiness(params: {
  station?: string; query?: string; optical_anomaly_only?: boolean; page?: number; page_size?: number
} = {}): Promise<TracksideApBusinessPage> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== '') query.set(key, String(value))
  return apiRequest(`${root}/rows?${query}`)
}

export function startTracksideApUpdate(payload: TracksideApUpdateRequest = {}): Promise<TracksideApTask> {
  return apiRequest(`${root}/update`, { method: 'POST', body: JSON.stringify(payload) })
}

export function startTracksideApBusinessExport(): Promise<TracksideApTask> {
  return apiRequest(`${root}/export`, { method: 'POST' })
}

export function listTracksideSwitchAdapters(): Promise<TracksideSwitchAdapterCatalog> {
  return apiRequest(`${root}/switch-adapters`)
}

export function startTracksideSwitchSample(payload: TracksideSwitchSampleRequest): Promise<TracksideApTask> {
  return apiRequest(`${root}/switch-adapters/sample`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getTracksideApTask(taskId: string): Promise<TracksideApTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}`)
}

export function cancelTracksideApTask(taskId: string): Promise<TracksideApTask> {
  return apiRequest(`${root}/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverTracksideApTasks(): Promise<TracksideApTask[]> {
  return apiRequest(`${root}/tasks/recover`, { method: 'POST' })
}

export function getTracksideApPlan(): Promise<TracksideApPlan> {
  return apiRequest(`${root}/plan`)
}

export function previewTracksideApPlan(file: File, duplicateStrategy: 'replace' | 'skip' | 'error'): Promise<TracksideApPlanPreview> {
  const form = new FormData()
  form.append('file', file)
  form.append('duplicate_strategy', duplicateStrategy)
  return apiRequest(`${root}/plan/import/preview`, { method: 'POST', body: form })
}

export function saveTracksideApPlan(rows: TracksideApPlanRow[]): Promise<TracksideApTask> {
  return apiRequest(`${root}/plan/save`, {
    method: 'POST', body: JSON.stringify({ rows, explicit_confirmation: true, audit: { source: 'electron-trackside-plan' } }),
  })
}

export function exportTracksideApPlan(template = false, rows?: TracksideApPlanRow[]): Promise<TracksideApTask> {
  return apiRequest(`${root}/plan/export`, { method: 'POST', body: JSON.stringify({ template, ...(rows ? { rows } : {}) }) })
}

export const tracksideApPlanDownloadRequest = (artifactId: string, suggestedName = '轨旁AP规划.xlsx'): BackendDownloadRequest => ({
  apiPath: `${root}/plan/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
})

export function exportTracksideApBase(template = false, rows?: TracksideAp[]): Promise<TracksideApTask> {
  return apiRequest(`${root}/base/export`, { method: 'POST', body: JSON.stringify({ template, ...(rows ? { rows } : {}) }) })
}

export function exportTracksideApRenameCommands(rows?: TracksideAp[]): Promise<TracksideApTask> {
  return apiRequest(`${root}/base/rename-commands/export`, { method: 'POST', body: JSON.stringify(rows ? { rows } : {}) })
}

export const tracksideApBaseDownloadRequest = (artifactId: string, suggestedName: string): BackendDownloadRequest => ({
  apiPath: `${root}/base/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
})

export const tracksideApRenameCommandDownloadRequest = (artifactId: string, suggestedName: string): BackendDownloadRequest => ({
  apiPath: `${root}/base/rename-commands/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
})

function normalizeTracksideApBusinessArtifactName(value: string): string {
  const suggestedName = value.trim()
  if (
    !suggestedName
    || suggestedName.length > 180
    || suggestedName === '.'
    || suggestedName === '..'
    || suggestedName.endsWith('.')
    || invalidArtifactNamePattern.test(suggestedName)
    || !tracksideBusinessArtifactNamePattern.test(suggestedName)
  ) {
    throw new TypeError('artifactName must be a safe file name')
  }
  return suggestedName
}

export const tracksideApBusinessDownloadRequest = (artifactId: string, artifactName: string): BackendDownloadRequest => ({
  apiPath: `${root}/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: normalizeTracksideApBusinessArtifactName(artifactName),
})

export const tracksideSwitchSampleDownloadRequest = (
  artifactId: string,
  artifactName: string,
): BackendDownloadRequest => {
  const suggestedName = artifactName.trim()
  if (
    !suggestedName
    || suggestedName.length > 180
    || invalidArtifactNamePattern.test(suggestedName)
    || !switchSampleArtifactNamePattern.test(suggestedName)
  ) {
    throw new TypeError('artifactName must be a safe switch sample file name')
  }
  return {
    apiPath: `${root}/switch-adapters/artifacts/${encodeURIComponent(artifactId)}/download`,
    suggestedName,
  }
}
