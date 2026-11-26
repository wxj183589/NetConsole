import { apiRequest } from './client'
import { resolveApiUrl } from '../platform/runtime'

export type TerminalProtocol = 'AUTO' | 'SSH' | 'TELNET'
export type TerminalState =
  | 'CREATED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RUNNING'
  | 'DISCONNECTED'
  | 'RECONNECTING'
  | 'CLOSING'
  | 'CLOSED'
  | 'FAILED'
  | 'CANCELLED'

export interface TerminalSession {
  session_name?: string
  detached_window?: boolean
  recording_log_name?: string
  recording_zip_name?: string
  recording_error?: string
  session_id: string
  device_uuid: string
  device_name: string
  site_id: string
  site_name: string
  protocol: Exclude<TerminalProtocol, 'AUTO'>
  encoding: string
  mode: 'INTERACTIVE'
  state: TerminalState
  address: string
  port: number
  username?: string
  backup_address?: string
  backup_port?: number
  created_at_ms: number
  updated_at_ms: number
  connected_at_ms: number | null
  ended_at_ms: number | null
  disconnect_reason: string
  error_code: string
  error_message?: string
  command_count: number
  output_bytes: number
  recording_status: 'RECORDING' | 'FINALIZING' | 'COMPRESSING' | 'COMPLETED' | 'COMPLETE' | 'FAILED' | 'INCOMPLETE'
  recording_sha256: string
  recording_dropped_events: number
  manual_log_status: 'STOPPED' | 'RECORDING' | 'PAUSED' | 'COMPLETE' | 'INCOMPLETE'
  manual_log_id: string
  manual_log_format: '' | 'txt' | 'jsonl'
  manual_log_filename: string
  manual_log_dropped_events: number
  automation_write_active: boolean
  automation_write_task_id: string
  automation_write_task_name: string
}

export interface TerminalSessionConnection {
  session: TerminalSession
  ticket: string
  ticket_expires_at_ms: number
}

export interface TerminalProfileFolder {
  folder_id: string
  name: string
}

export interface TerminalProfile {
  profile_id: string
  name: string
  host: string
  backup_host: string
  backup_port: number
  port: number
  protocol: Exclude<TerminalProtocol, 'AUTO'>
  username: string
  encoding: string
  vendor: string
  device_type: string
  folder_id: string
  favorite: boolean
  notes: string
  tags: string[]
  password_configured: boolean
  created_at_ms: number
  updated_at_ms: number
}

export interface TerminalProfileValues {
  name: string
  host: string
  backup_host?: string
  backup_port?: number | null
  port: number
  protocol: Exclude<TerminalProtocol, 'AUTO'>
  username: string
  encoding: string
  vendor: string
  device_type: string
  folder_id: string
  favorite: boolean
  notes?: string
  tags?: string[]
}

export interface TerminalProfileDocument {
  schema_version: number
  folders: TerminalProfileFolder[]
  profiles: TerminalProfile[]
}

export interface TerminalRecordingEvent {
  at_ms: number
  event_type: string
  data?: string
  state?: string
  reason?: string
  error_code?: string
}

export interface TerminalSettings {
  schema_version: number
  font_family: string
  font_size: number
  foreground: string
  background: string
  cursor_color: string
  encoding: string
  automatic_recording: boolean
  automatic_log_retention_days: number
  automatic_log_max_bytes: number
  manual_log_recent_directory: string
  dangerous_command_warning: boolean
}

export interface TerminalHighlightRule {
  id: string
  pattern: string
  match_type: 'TEXT' | 'REGEX'
  color: string
  enabled: boolean
  source_row: number
}

export interface TerminalDangerousRule {
  id: string
  pattern: string
  match_type: 'TEXT' | 'REGEX'
  device_type: string
  vendor: string
  enabled: boolean
  source_row: number
}

export interface TerminalRuleDocument<T> {
  schema_version: number
  source_file?: string
  sheet_name?: string
  actual_rule_count: number
  documented_rule_count?: number
  rules: T[]
}

export interface TerminalSftpSession {
  workspace_id?: string
  session_id: string
  device_uuid: string
  device_name: string
  site_id: string
  site_name: string
  root_path: string
  current_path: string
  state: 'CONNECTED' | 'CLOSED' | 'FAILED'
  created_at_ms: number
  error_code: string
}

export interface TerminalSftpEntry {
  name: string
  remote_path: string
  size: number | null
  modified_time: string | null
  category: string
  is_dir: boolean
  file_type: string
  permissions: string
}

export interface TerminalSftpTransfer {
  device_uuid?: string
  workspace_id?: string
  task_id: string
  session_id: string
  kind: 'UPLOAD' | 'DOWNLOAD' | 'COPY'
  source: string
  target: string
  status: 'WAITING' | 'QUEUED' | 'RUNNING' | 'PAUSED' | 'READY' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'SKIPPED'
  transferred_bytes: number
  total_bytes: number
  bytes_per_second: number
  created_at_ms: number
  started_at_ms: number | null
  ended_at_ms: number | null
  error_code: string
  error_message: string
  result_name: string
  result_size: number
  result_sha256: string
  save_status: string
  remaining_seconds: number | null
  resumable: boolean
  files_completed: number
  files_total: number
}

export function createTerminalSession(
  deviceUuid: string,
  protocol: TerminalProtocol = 'AUTO',
  cols = 120,
  rows = 32,
  addressRole?: 'primary' | 'backup',
): Promise<TerminalSessionConnection> {
  return apiRequest('/api/terminal/sessions', {
    method: 'POST',
    body: JSON.stringify({ device_uuid: deviceUuid, protocol, cols, rows, address_role: addressRole }),
  })
}

export function quickConnectTerminalSession(
  values: TerminalProfileValues & {
    password: string
    save_profile: boolean
    remember_password: boolean
    cols?: number
    rows?: number
  },
): Promise<TerminalSessionConnection & { profile: TerminalProfile | null }> {
  return apiRequest('/api/terminal/sessions/quick-connect', {
    method: 'POST',
    body: JSON.stringify(values),
  })
}

export function listTerminalProfiles(): Promise<TerminalProfileDocument> {
  return apiRequest('/api/terminal/profiles')
}

export function importTerminalProfiles(document: TerminalProfileDocument): Promise<TerminalProfileDocument> {
  return apiRequest('/api/terminal/profiles/import', {
    method: 'POST',
    body: JSON.stringify({ document }),
  })
}

export function saveTerminalProfile(
  values: TerminalProfileValues & {
    password?: string
    remember_password?: boolean | null
  },
  profileId = '',
): Promise<TerminalProfile> {
  return apiRequest(`/api/terminal/profiles${profileId ? `/${encodeURIComponent(profileId)}` : ''}`, {
    method: profileId ? 'PUT' : 'POST',
    body: JSON.stringify(values),
  })
}

export function deleteTerminalProfile(profileId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/api/terminal/profiles/${encodeURIComponent(profileId)}`, { method: 'DELETE' })
}

export function connectTerminalProfile(
  profileId: string,
  password = '',
  addressRole: 'primary' | 'backup' = 'primary',
): Promise<TerminalSessionConnection> {
  return apiRequest(`/api/terminal/profiles/${encodeURIComponent(profileId)}/connect`, {
    method: 'POST',
    body: JSON.stringify({ password, address_role: addressRole }),
  })
}

export function createTerminalProfileFolder(name: string): Promise<TerminalProfileFolder> {
  return apiRequest('/api/terminal/profile-folders', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function renameTerminalProfileFolder(folderId: string, name: string): Promise<TerminalProfileFolder> {
  return apiRequest(`/api/terminal/profile-folders/${encodeURIComponent(folderId)}`, {
    method: 'PUT',
    body: JSON.stringify({ name }),
  })
}

export function deleteTerminalProfileFolder(folderId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/api/terminal/profile-folders/${encodeURIComponent(folderId)}`, { method: 'DELETE' })
}

export function listTerminalSessions(): Promise<{ items: TerminalSession[]; total: number }> {
  return apiRequest('/api/terminal/sessions')
}

export function listTerminalHistory(keyword = '', limit = 100): Promise<{ items: TerminalSession[]; total: number }> {
  const params = new URLSearchParams({ keyword, limit: String(limit) })
  return apiRequest(`/api/terminal/history?${params}`)
}

export function getTerminalHistoryEvents(
  sessionId: string,
  offset = 0,
  limit = 1000,
): Promise<{ items: TerminalRecordingEvent[]; has_more: boolean }> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
  return apiRequest(`/api/terminal/history/${encodeURIComponent(sessionId)}/events?${params}`)
}

export function reconnectTerminalSession(sessionId: string): Promise<TerminalSessionConnection> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/reconnect`, { method: 'POST' })
}

export function cloneTerminalSession(sessionId: string): Promise<TerminalSessionConnection> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/clone`, { method: 'POST' })
}
export function renameTerminalSession(sessionId: string, name: string): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}`, { method: 'PATCH', body: JSON.stringify({ name }) })
}
export function deleteTerminalRecording(sessionId: string): Promise<{ deleted: boolean }> {
  return apiRequest(`/api/terminal/history/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export function issueTerminalTicket(sessionId: string): Promise<{
  ticket: string
  session_id: string
  ticket_expires_at_ms: number
}> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/ticket`, { method: 'POST' })
}

export function closeTerminalSession(sessionId: string): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export function terminalWebSocketUrl(sessionId: string, ticket: string): string {
  const url = new URL(resolveApiUrl(`/ws/terminal/${encodeURIComponent(sessionId)}`))
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('ticket', ticket)
  return url.toString()
}

export function terminalExportDownloadRequest(sessionId: string, format: 'txt' | 'jsonl' | 'log' | 'zip', name?: string): {
  apiPath: string
  suggestedName: string
} {
  const safeSessionId = sessionId.replace(/[^a-zA-Z0-9_-]+/g, '-')
  return {
    apiPath: `/api/terminal/history/${encodeURIComponent(sessionId)}/export/${format}`,
    suggestedName: name || `terminal-${safeSessionId}.${format}`,
  }
}

export function getTerminalSettings(): Promise<TerminalSettings> {
  return apiRequest('/api/terminal/settings')
}

export function updateTerminalSettings(values: Partial<TerminalSettings>): Promise<TerminalSettings> {
  return apiRequest('/api/terminal/settings', {
    method: 'PUT',
    body: JSON.stringify({ values }),
  })
}

export function getTerminalHighlightRules(): Promise<TerminalRuleDocument<TerminalHighlightRule>> {
  return apiRequest('/api/terminal/rules/highlight')
}

export function getTerminalDangerousRules(): Promise<TerminalRuleDocument<TerminalDangerousRule>> {
  return apiRequest('/api/terminal/rules/dangerous')
}

export function replaceTerminalHighlightRules(
  rules: TerminalHighlightRule[],
  repairInvalid = false,
): Promise<TerminalRuleDocument<TerminalHighlightRule>> {
  return apiRequest('/api/terminal/rules/highlight', {
    method: 'PUT',
    body: JSON.stringify(repairInvalid ? { rules, repair_invalid: true } : { rules }),
  })
}

export function replaceTerminalDangerousRules(
  rules: TerminalDangerousRule[],
  repairInvalid = false,
): Promise<TerminalRuleDocument<TerminalDangerousRule>> {
  return apiRequest('/api/terminal/rules/dangerous', {
    method: 'PUT',
    body: JSON.stringify(repairInvalid ? { rules, repair_invalid: true } : { rules }),
  })
}

export function previewTerminalRulesImport(
  kind: 'highlight' | 'dangerous', file: File,
): Promise<TerminalRuleDocument<TerminalHighlightRule | TerminalDangerousRule>> {
  const body = new FormData()
  body.set('kind', kind)
  body.set('file', file, file.name)
  return apiRequest('/api/terminal/rules/import', { method: 'POST', body })
}

export function startTerminalManualLog(
  sessionId: string,
  filename: string,
  format: 'txt' | 'jsonl',
): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/manual-log/start`, {
    method: 'POST',
    body: JSON.stringify({ filename, format }),
  })
}

export function pauseTerminalManualLog(sessionId: string): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/manual-log/pause`, { method: 'POST' })
}

export function resumeTerminalManualLog(sessionId: string): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/manual-log/resume`, { method: 'POST' })
}

export function stopTerminalManualLog(sessionId: string): Promise<TerminalSession> {
  return apiRequest(`/api/terminal/sessions/${encodeURIComponent(sessionId)}/manual-log/stop`, { method: 'POST' })
}

export function terminalManualLogDownloadRequest(
  sessionId: string,
  logId: string,
  suggestedName: string,
): { apiPath: string; suggestedName: string; destinationPath?: string } {
  return {
    apiPath: `/api/terminal/sessions/${encodeURIComponent(sessionId)}/manual-log/${encodeURIComponent(logId)}/export`,
    suggestedName,
  }
}

export function createTerminalSftpSession(deviceUuid: string, workspaceId = ''): Promise<TerminalSftpSession> {
  return apiRequest('/api/terminal/sftp/sessions', {
    method: 'POST',
    body: JSON.stringify({ device_uuid: deviceUuid, workspace_id: workspaceId }),
  })
}

export function closeTerminalSftpSession(sessionId: string): Promise<TerminalSftpSession> {
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export function listTerminalSftpSessions(): Promise<{ items: TerminalSftpSession[] }> {
  return apiRequest('/api/terminal/sftp/sessions', { coalesce: false })
}

export function listTerminalSftpEntries(
  sessionId: string,
  path = '',
): Promise<{ session: TerminalSftpSession; path: string; items: TerminalSftpEntry[] }> {
  const params = new URLSearchParams()
  if (path) params.set('path', path)
  const query = params.toString()
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}/entries${query ? `?${query}` : ''}`)
}

function terminalSftpPathAction<T>(sessionId: string, action: string, body: object): Promise<T> {
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}/${action}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function createTerminalSftpDirectory(sessionId: string, path: string): Promise<{ path: string }> {
  return terminalSftpPathAction(sessionId, 'directories', { path })
}

export function renameTerminalSftpEntry(sessionId: string, source: string, target: string, overwrite = false): Promise<{ path: string }> {
  return terminalSftpPathAction(sessionId, 'rename', { source, target, overwrite })
}

export function moveTerminalSftpEntry(sessionId: string, source: string, target: string, overwrite = false): Promise<{ path: string }> {
  return terminalSftpPathAction(sessionId, 'move', { source, target, overwrite })
}

export function deleteTerminalSftpEntries(sessionId: string, paths: string[], recursive = false): Promise<{ deleted: string[]; count: number }> {
  return terminalSftpPathAction(sessionId, 'delete', { paths, recursive })
}

export function copyTerminalSftpEntry(sessionId: string, source: string, target: string, overwrite = false): Promise<TerminalSftpTransfer> {
  return terminalSftpPathAction(sessionId, 'copy', { source, target, overwrite })
}

export function startTerminalSftpDownload(sessionId: string, path: string): Promise<TerminalSftpTransfer> {
  return terminalSftpPathAction(sessionId, 'download', { path })
}

export function startManagedSftpDownload(sessionId: string, path: string, directoryId: string): Promise<TerminalSftpTransfer> {
  return terminalSftpPathAction(sessionId, 'download-managed', { path, directory_id: directoryId })
}

export type SftpSyncDirection = 'upload' | 'download' | 'both'
export type SftpSyncComparison = 'size' | 'modified' | 'sha256'
interface SftpSyncEntry { size: number | null; modified: string | null }
export interface SftpSyncPreview {
  revision: string
  rows: Array<{
    name: string
    action: 'upload' | 'download' | 'conflict' | 'same' | 'excluded' | 'ignored'
    local: SftpSyncEntry | null
    remote: SftpSyncEntry | null
  }>
  can_apply: boolean
  transfer_count: number
  queued: TerminalSftpTransfer[]
  error?: string
}

export function synchronizeSftpDirectory(
  sessionId: string, path: string, directoryId: string,
  direction: SftpSyncDirection, comparison: SftpSyncComparison, revision = '',
): Promise<SftpSyncPreview> {
  return terminalSftpPathAction(sessionId, 'sync', {
    path, directory_id: directoryId, direction, comparison, expected_revision: revision,
  })
}

export interface SftpTextFile {
  path: string
  text: string
  revision: string
  original: { text: string; digest: string; mode: number; uid: number; gid: number; newline: '\n' | '\r\n'; bom: boolean }
}

export function readSftpTextFile(sessionId: string, path: string): Promise<SftpTextFile> {
  const params = new URLSearchParams({ path })
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}/text?${params}`)
}

export function writeSftpTextFile(
  sessionId: string, path: string, revision: string, text: string, original: SftpTextFile['original'],
): Promise<{ path: string; revision: string }> {
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}/text`, {
    method: 'PUT', body: JSON.stringify({ path, revision, text, original }),
  })
}

export function uploadTerminalSftpFile(
  sessionId: string,
  remoteDirectory: string,
  file: File,
  overwrite = false,
  relativePath = '',
  conflict = 'error',
): Promise<TerminalSftpTransfer> {
  const body = new FormData()
  body.set('remote_directory', remoteDirectory)
  body.set('overwrite', String(overwrite))
  body.set('relative_path', relativePath)
  body.set('conflict', conflict)
  body.set('file', file, file.name)
  return apiRequest(`/api/terminal/sftp/sessions/${encodeURIComponent(sessionId)}/upload`, {
    method: 'POST',
    body,
  })
}

export function listTerminalSftpTransfers(sessionId = ''): Promise<{ items: TerminalSftpTransfer[]; total: number }> {
  const params = new URLSearchParams()
  if (sessionId) params.set('session_id', sessionId)
  const query = params.toString()
  return apiRequest(`/api/terminal/sftp/transfers${query ? `?${query}` : ''}`, { coalesce: false })
}

export function uploadManagedSftpFile(
  sessionId: string,
  remoteDirectory: string,
  entryId: string,
  conflict: 'error' | 'skip' | 'rename' | 'overwrite',
): Promise<TerminalSftpTransfer> {
  return terminalSftpPathAction(sessionId, 'upload-managed', {
    entry_id: entryId,
    remote_directory: remoteDirectory,
    conflict,
  })
}

export function cancelTerminalSftpTransfer(taskId: string): Promise<TerminalSftpTransfer> {
  return apiRequest(`/api/terminal/sftp/transfers/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' })
}

export function pauseTerminalSftpTransfer(taskId: string): Promise<TerminalSftpTransfer> {
  return apiRequest(`/api/terminal/sftp/transfers/${encodeURIComponent(taskId)}/pause`, { method: 'POST' })
}

export function retryTerminalSftpTransfer(taskId: string): Promise<TerminalSftpTransfer> {
  return apiRequest(`/api/terminal/sftp/transfers/${encodeURIComponent(taskId)}/retry`, { method: 'POST' })
}

export function terminalSftpDownloadRequest(taskId: string, suggestedName: string, expectedSizeBytes?: number, expectedSha256?: string): {
  apiPath: string
  suggestedName: string
  expectedSizeBytes?: number
  expectedSha256?: string
} {
  return {
    apiPath: `/api/terminal/sftp/transfers/${encodeURIComponent(taskId)}/file`,
    suggestedName,
    expectedSizeBytes,
    expectedSha256,
  }
}

export function recordTerminalSftpSave(task: TerminalSftpTransfer, saved: boolean): Promise<TerminalSftpTransfer> {
  return apiRequest(`/api/terminal/sftp/transfers/${encodeURIComponent(task.task_id)}/save-result`, {
    method: 'POST', body: JSON.stringify({ saved, size: task.result_size, sha256: task.result_sha256 }),
  })
}

export function clearTerminalSftpTransfers(deviceUuid = '', workspaceId = ''): Promise<{ cleared: number }> {
  const params = new URLSearchParams()
  if (deviceUuid) params.set('device_uuid', deviceUuid)
  if (workspaceId) params.set('workspace_id', workspaceId)
  const query = params.toString()
  return apiRequest(`/api/terminal/sftp/transfers${query ? `?${query}` : ''}`, { method: 'DELETE' })
}
