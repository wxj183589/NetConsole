import { apiRequest } from './client'
import type {
  AcActionAudit, AcActionPlan, AcExtensionPage, AcExtensionPreview,
  AcExternalTerminalAction, AcExternalTerminalOptions,
  AcOmniPeekConfig, AcOmniPeekPreferences, AcOmniPeekPreview, AcTerminalType, AcWebTask,
} from '../types/acWebParity'
import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'

const root = '/api/ac-management'

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value))
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function listAcExtensions(page = 1, pageSize = 50, search = ''): Promise<AcExtensionPage> {
  return apiRequest<AcExtensionPage>(`${root}/extensions${query({ page, page_size: pageSize, search })}`)
}

export function previewAcExtension(file: File): Promise<AcExtensionPreview> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<AcExtensionPreview>(`${root}/extensions/import-preview`, { method: 'POST', body: form })
}

export function applyAcExtension(preview: AcExtensionPreview, explicitConfirmation = true): Promise<{
  audit_id: string
  status: string
  preview_id: string
}> {
  return apiRequest(`${root}/extensions/import-apply`, {
    method: 'POST',
    body: JSON.stringify({ preview_id: preview.preview_id, preview_digest: preview.preview_digest, explicit_confirmation: explicitConfirmation }),
  })
}

export function rollbackAcExtension(auditId: string): Promise<{ audit_id: string; status: string; restored_rows: number }> {
  return apiRequest(`${root}/extensions/audits/${encodeURIComponent(auditId)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ explicit_confirmation: true }),
  })
}

export function startAcLocalRebuild(kind: 'ac' | 'fit-ap' | 'optical' | 'trackside-business', acId = ''): Promise<AcWebTask> {
  const path = kind === 'trackside-business' ? `${root}/trackside-business/local-rebuild` : `${root}/local-rebuild/${kind}`
  return apiRequest<AcWebTask>(path, { method: 'POST', body: JSON.stringify({ ac_id: acId }) })
}

export function startAcResourceRefresh(kind: 'ac' | 'fit-ap' | 'ap-detail' | 'optical', acId: string, apId = ''): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/refresh/${kind}`, {
    method: 'POST',
    body: JSON.stringify({ ac_id: acId, ap_id: apId }),
  })
}

export function deleteAcFitAps(acId: string, apIds: string[]): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/fit-aps/delete`, {
    method: 'POST',
    body: JSON.stringify({ ac_id: acId, ap_ids: apIds, explicit_confirmation: true }),
  })
}

export function importAcFitApMetadata(file: File): Promise<AcWebTask> {
  const form = new FormData()
  form.append('file', file)
  return apiRequest<AcWebTask>(`${root}/fit-aps/metadata/import`, { method: 'POST', body: form })
}

export function saveAcFitApMetadata(
  acId: string,
  apId: string,
  metadata: { site_name: string; mileage: string; location_note: string; direction: string },
): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/aps/${encodeURIComponent(apId)}/metadata`, {
    method: 'POST',
    body: JSON.stringify({ ac_id: acId, ...metadata }),
  })
}

export function exportAcExtensions(search = '', acId = ''): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/extensions/export${query({ search, ac_id: acId })}`, { method: 'POST' })
}

export function getAcWebTask(taskId: string): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/web-tasks/${encodeURIComponent(taskId)}`)
}

export function cancelAcWebTask(taskId: string): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/web-tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function recoverAcWebTasks(): Promise<AcWebTask[]> {
  return apiRequest<AcWebTask[]>(`${root}/web-tasks/recover`, { method: 'POST' })
}

export const acExtensionArtifactDownloadRequest = (artifactId: string): BackendDownloadRequest => ({
  apiPath: `${root}/extensions/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName: 'AP扩展信息.xlsx',
})

export function createAcActionPlan(targetId: string, actionId: string): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans`, { method: 'POST', body: JSON.stringify({ target_id: targetId, action_id: actionId }) })
}

export function confirmAcActionPlan(plan: AcActionPlan): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans/${encodeURIComponent(plan.plan_id)}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ plan_digest: plan.plan_digest, confirm_token: plan.confirm_token }),
  })
}

export function executeAcActionPlan(planId: string): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans/${encodeURIComponent(planId)}/execute`, { method: 'POST' })
}

export function getAcActionPlan(planId: string): Promise<AcActionPlan> {
  return apiRequest<AcActionPlan>(`${root}/actions/plans/${encodeURIComponent(planId)}`)
}

export function getAcActionAudit(planId: string): Promise<AcActionAudit> {
  return apiRequest<AcActionAudit>(`${root}/actions/plans/${encodeURIComponent(planId)}/audit`)
}

export function startAcOmniPeekPreview(acId: string, apIds: string[], config: AcOmniPeekConfig): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/fit-aps/omnipeek/preview`, {
    method: 'POST', body: JSON.stringify({ ac_id: acId, ap_ids: apIds, ...config }),
  })
}

export function getAcOmniPeekPreview(
  taskId: string,
  options: { page?: number; page_size?: number; status_filter?: string; search?: string } = {},
): Promise<AcOmniPeekPreview> {
  return apiRequest<AcOmniPeekPreview>(`${root}/fit-aps/omnipeek/preview/${encodeURIComponent(taskId)}${query(options)}`)
}

export function startAcOmniPeekExport(
  acId: string,
  apIds: string[],
  config: AcOmniPeekConfig & { selected_item_keys: string[]; excluded_item_keys: string[]; force_export_keys: string[] },
): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/fit-aps/omnipeek/export`, {
    method: 'POST', body: JSON.stringify({ ac_id: acId, ap_ids: apIds, ...config }),
  })
}

export function getAcOmniPeekPreferences(): Promise<AcOmniPeekPreferences> {
  return apiRequest<AcOmniPeekPreferences>(`${root}/fit-aps/omnipeek/preferences`)
}

export function saveAcOmniPeekPreferences(colors: Record<string, string>): Promise<AcOmniPeekPreferences> {
  return apiRequest<AcOmniPeekPreferences>(`${root}/fit-aps/omnipeek/preferences`, {
    method: 'PUT', body: JSON.stringify({ colors }),
  })
}

export const acOmniPeekArtifactDownloadRequest = (artifactId: string, suggestedName: string, destinationPath = ''): BackendDownloadRequest => ({
  apiPath: `${root}/fit-aps/omnipeek/artifacts/${encodeURIComponent(artifactId)}/download`,
  suggestedName,
  filters: [{ name: 'OmniPeek 名称表', extensions: ['nam'] }],
  ...(destinationPath ? { destinationPath } : {}),
})

export type AcFitApResourceExportScope = 'filtered' | 'selected' | 'all'

export interface AcFitApResourceExportFilters {
  query?: string
  status?: string
  optical_status?: string
  station?: string
  section?: string
  model?: string
  switch?: string
}

export function startAcFitApResourceExport(
  acId: string,
  scope: AcFitApResourceExportScope,
  selectedApIds: string[],
  filters: AcFitApResourceExportFilters,
): Promise<AcWebTask> {
  return apiRequest<AcWebTask>(`${root}/fit-aps/export`, {
    method: 'POST',
    body: JSON.stringify({
      ac_id: acId,
      scope,
      selected_ap_ids: selectedApIds,
      filters,
      format: 'xlsx',
    }),
  })
}

export const acFitApResourceArtifactDownloadRequest = (
  task: Pick<AcWebTask, 'artifact_id' | 'artifact_name' | 'size_bytes' | 'sha256'>,
): BackendDownloadRequest => ({
  apiPath: `${root}/fit-aps/artifacts/${encodeURIComponent(task.artifact_id)}/download`,
  suggestedName: task.artifact_name || 'FIT-AP资源.xlsx',
  filters: [{ name: 'Excel 工作簿', extensions: ['xlsx'] }],
  ...(task.size_bytes > 0 && task.sha256
    ? { expectedSizeBytes: task.size_bytes, expectedSha256: task.sha256 }
    : {}),
})

export function getAcExternalTerminalOptions(): Promise<AcExternalTerminalOptions> {
  return apiRequest<AcExternalTerminalOptions>(`${root}/fit-aps/external-terminal/options`)
}

export function openAcFitApExternalTerminal(apId: string, acId: string, terminalType: AcTerminalType): Promise<AcExternalTerminalAction> {
  return apiRequest<AcExternalTerminalAction>(`${root}/fit-aps/${encodeURIComponent(apId)}/external-terminal`, {
    method: 'POST', body: JSON.stringify({ ac_id: acId, terminal_type: terminalType }),
  })
}
