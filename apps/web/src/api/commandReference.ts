import type { BackendDownloadRequest } from '../../../desktop_electron/src/shared/bridge'
import type { CommandReferenceExportTask, CommandReferencePage, CommandReferenceQuery } from '../types/commandReference'
import { apiRequest } from './client'

const root = '/api/command-reference'
export const commandReferenceArtifactName = 'NetConsole_软件使用命令清单.md'

function queryString(values: CommandReferenceQuery): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function listCommandReferences(query: CommandReferenceQuery = {}): Promise<CommandReferencePage> {
  return apiRequest<CommandReferencePage>(`${root}${queryString(query)}`)
}

export function startCommandReferenceExport(selectedIds: string[]): Promise<CommandReferenceExportTask> {
  return apiRequest<CommandReferenceExportTask>(`${root}/exports`, {
    method: 'POST',
    body: JSON.stringify({ selected_ids: selectedIds }),
  })
}

export function getCommandReferenceExport(taskId: string): Promise<CommandReferenceExportTask> {
  return apiRequest<CommandReferenceExportTask>(`${root}/exports/${encodeURIComponent(taskId)}`)
}

export function cancelCommandReferenceExport(taskId: string): Promise<{ id: string; status: string; message: string }> {
  return apiRequest(`${root}/exports/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function commandReferenceArtifactDownloadRequest(artifactId: string): BackendDownloadRequest {
  return {
    apiPath: `${root}/artifacts/${encodeURIComponent(artifactId)}/download`,
    suggestedName: commandReferenceArtifactName,
  }
}
