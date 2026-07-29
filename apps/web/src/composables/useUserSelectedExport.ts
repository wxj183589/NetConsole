import { computed, reactive, readonly } from 'vue'
import { ElMessage } from 'element-plus'

import { getTask } from '../api/tasks'
import { downloadBackendResource, getPlatformAdapter } from '../platform/runtime'
import {
  exportDefinition,
  isUserSelectedExportAction,
  type UserSelectedExportAction,
} from '../platform/exportActionRegistry'
import type { TaskItem } from '../types/task'

const STORAGE_KEY = 'netconsole.user-selected-exports.v1'
const TASK_ID_RE = /^[A-Za-z0-9_-]{1,200}$/
const SHA256_RE = /^[0-9a-f]{64}$/i
const RECONCILE_INTERVAL_MS = 1_000

export type UserSelectedExportState =
  | 'task_running'
  | 'artifact_ready'
  | 'saving'
  | 'saved'
  | 'save_failed'
  | 'browser_started'
  | 'task_failed'
  | 'task_cancelled'

export interface UserSelectedExportDestination {
  mode: 'electron' | 'browser'
  path: string
  fileName: string
  directoryLabel: string
}

export interface PendingUserSelectedExport {
  taskId: string
  action: UserSelectedExportAction
  module: string
  destinationMode: UserSelectedExportDestination['mode']
  destinationPath: string
  suggestedName: string
  fileName: string
  directoryLabel: string
  state: UserSelectedExportState
  context: Record<string, string | number | boolean>
  artifact?: NonNullable<TaskItem['artifact_download']>
  capabilityId?: string
  error?: string
}

export interface SubmitUserSelectedExportOptions<T> {
  action: UserSelectedExportAction
  suggestedName: string
  directoryPath?: string
  context?: Record<string, string | number | boolean>
  submit: () => Promise<T>
  taskId?: (task: T) => string
}

export type SubmitUserSelectedExportResult<T> =
  | { status: 'cancelled' }
  | {
      status: 'submitted'
      task: T
      binding: PendingUserSelectedExport
    }

const bindings = reactive<Record<string, PendingUserSelectedExport>>({})
const reconciling = new Set<string>()
let restored = false
let coordinatorConsumers = 0
let reconcileTimer: number | null = null

export function useUserSelectedExport() {
  const pending = computed(() => Object.values(bindings))

  return {
    bindings: readonly(bindings),
    pending,
    prepareExportDestination,
    submitExportAfterDestinationSelected,
    bindExportTaskDestination,
    saveReadyArtifact,
    retryArtifactSave,
    hasActiveExportAction,
    startExportSaveCoordinator,
    stopExportSaveCoordinator,
    bindingForTask,
  }
}

export async function prepareExportDestination(
  action: UserSelectedExportAction,
  suggestedName: string,
  directoryPath?: string,
): Promise<UserSelectedExportDestination | null> {
  const definition = exportDefinition(action)
  const safeSuggestedName = validateSuggestedName(suggestedName, definition.artifactExtensions)
  const adapter = getPlatformAdapter()
  if (adapter.hostType === 'browser') {
    return {
      mode: 'browser',
      path: '',
      fileName: safeSuggestedName,
      directoryLabel: '浏览器下载',
    }
  }
  const result = await adapter.chooseSavePath({
    suggestedName: safeSuggestedName,
    filters: definition.filters.map((item) => ({
      name: item.name,
      extensions: [...item.extensions],
    })),
    ...(directoryPath ? { directoryPath } : {}),
  })
  if (result.cancelled || !result.path) return null
  return {
    mode: 'electron',
    path: result.path,
    fileName: selectedFileName(result.path) || safeSuggestedName,
    directoryLabel: selectedDirectoryLabel(result.path),
  }
}

export async function submitExportAfterDestinationSelected<T>(
  options: SubmitUserSelectedExportOptions<T>,
): Promise<SubmitUserSelectedExportResult<T>> {
  const destination = await prepareExportDestination(
    options.action,
    options.suggestedName,
    options.directoryPath,
  )
  if (!destination) return { status: 'cancelled' }
  const task = await options.submit()
  const taskId = (options.taskId ?? taskIdFrom)(task)
  const binding = bindExportTaskDestination(taskId, options.action, destination, options.context)
  return { status: 'submitted', task, binding }
}

export function bindExportTaskDestination(
  taskId: string,
  action: UserSelectedExportAction,
  destination: UserSelectedExportDestination,
  context: Record<string, string | number | boolean> = {},
): PendingUserSelectedExport {
  if (!TASK_ID_RE.test(taskId)) throw new TypeError('导出任务标识无效')
  const definition = exportDefinition(action)
  if (destination.mode === 'electron' && !destination.path) {
    throw new TypeError('Electron 导出缺少已授权的另存为路径')
  }
  const binding: PendingUserSelectedExport = {
    taskId,
    action,
    module: definition.module,
    destinationMode: destination.mode,
    destinationPath: destination.path,
    suggestedName: destination.fileName,
    fileName: destination.fileName,
    directoryLabel: destination.directoryLabel,
    state: 'task_running',
    context: sanitizeContext(context),
  }
  bindings[taskId] = binding
  persistBindings()
  return binding
}

export async function saveReadyArtifact(
  taskId: string,
  artifact: NonNullable<TaskItem['artifact_download']>,
): Promise<void> {
  const binding = bindings[taskId]
  if (!binding || binding.state === 'saving' || binding.state === 'saved' || binding.state === 'browser_started') return
  const definition = exportDefinition(binding.action)
  const validationError = artifactValidationError(artifact, definition)
  binding.artifact = { ...artifact, query: { ...artifact.query } }
  if (validationError) {
    markSaveFailed(binding, validationError)
    return
  }
  binding.state = 'saving'
  binding.error = ''
  persistBindings()
  let result
  try {
    result = await downloadBackendResource({
      apiPath: artifact.api_path,
      query: { ...artifact.query },
      suggestedName: binding.suggestedName,
      ...(binding.destinationMode === 'electron'
        ? { destinationPath: binding.destinationPath }
        : {}),
      expectedSizeBytes: artifact.size_bytes,
      expectedSha256: artifact.sha256!,
    })
  } catch (cause) {
    markSaveFailed(binding, errorMessage(cause, '本地保存组件不可用，请重新选择保存位置。'))
    return
  }
  if (result.status === 'saved') {
    binding.state = 'saved'
    binding.fileName = result.fileName || binding.fileName
    binding.directoryLabel = result.directoryLabel || binding.directoryLabel || '用户选择的目录'
    binding.capabilityId = result.capabilityId || ''
    binding.error = ''
    persistBindings()
    ElMessage.success(`${definition.label}已保存：${binding.fileName}（用户选择的目录）`)
    return
  }
  if (result.status === 'started' && binding.destinationMode === 'browser') {
    binding.state = 'browser_started'
    binding.error = ''
    persistBindings()
    ElMessage.info(`${definition.label}已交由浏览器下载；开发模式无法验证具体本地落盘位置。`)
    return
  }
  markSaveFailed(
    binding,
    result.status === 'failed'
      ? result.error || '无法写入用户选择的目录。'
      : '桌面保存未返回已落盘结果，请重新选择保存位置。',
  )
}

export async function retryArtifactSave(taskId: string): Promise<boolean> {
  const binding = bindings[taskId]
  if (!binding) return false
  let artifact = binding.artifact
  if (!artifact) {
    const task = await getTask(taskId)
    artifact = task.artifact_download || undefined
  }
  if (!artifact) {
    ElMessage.error('Artifact 尚未就绪，请在任务中心查看。')
    return false
  }
  if (binding.destinationMode === 'electron') {
    const destination = await prepareExportDestination(binding.action, binding.fileName || binding.suggestedName)
    if (!destination) return false
    binding.destinationPath = destination.path
    binding.fileName = destination.fileName
    binding.suggestedName = destination.fileName
    binding.directoryLabel = destination.directoryLabel
  }
  binding.state = 'artifact_ready'
  binding.error = ''
  persistBindings()
  await saveReadyArtifact(taskId, artifact)
  const finalState = bindings[taskId]?.state as UserSelectedExportState | undefined
  return finalState === 'saved' || finalState === 'browser_started'
}

export function hasActiveExportAction(action: UserSelectedExportAction): boolean {
  return Object.values(bindings).some((binding) => (
    binding.action === action
    && ['task_running', 'artifact_ready', 'saving'].includes(binding.state)
  ))
}

export function bindingForTask(taskId: string): PendingUserSelectedExport | null {
  return bindings[taskId] || null
}

export function resetUserSelectedExportForTests(): void {
  if (import.meta.env.MODE !== 'test') {
    throw new Error('导出协调器重置仅允许在测试环境使用')
  }
  if (reconcileTimer !== null && typeof window !== 'undefined') window.clearInterval(reconcileTimer)
  reconcileTimer = null
  coordinatorConsumers = 0
  restored = false
  reconciling.clear()
  for (const taskId of Object.keys(bindings)) delete bindings[taskId]
  if (typeof window !== 'undefined') window.sessionStorage.removeItem(STORAGE_KEY)
}

export function startExportSaveCoordinator(): void {
  coordinatorConsumers += 1
  if (coordinatorConsumers !== 1) return
  restoreBindings()
  void reconcileAll()
  reconcileTimer = window.setInterval(() => void reconcileAll(), RECONCILE_INTERVAL_MS)
}

export function stopExportSaveCoordinator(): void {
  coordinatorConsumers = Math.max(0, coordinatorConsumers - 1)
  if (coordinatorConsumers || reconcileTimer === null) return
  window.clearInterval(reconcileTimer)
  reconcileTimer = null
}

async function reconcileAll(): Promise<void> {
  const taskIds = Object.values(bindings)
    .filter((binding) => ['task_running', 'artifact_ready'].includes(binding.state))
    .map((binding) => binding.taskId)
  await Promise.all(taskIds.map(reconcileTask))
}

async function reconcileTask(taskId: string): Promise<void> {
  const binding = bindings[taskId]
  if (!binding || reconciling.has(taskId)) return
  reconciling.add(taskId)
  try {
    const task = await getTask(taskId)
    if (task.status === 'FAILED') {
      binding.state = 'task_failed'
      binding.error = task.error_summary || task.message || '导出任务失败'
      persistBindings()
      return
    }
    if (task.status === 'CANCELLED') {
      binding.state = 'task_cancelled'
      binding.error = ''
      persistBindings()
      return
    }
    if (task.status !== 'COMPLETED' || !task.artifact_download) return
    binding.state = 'artifact_ready'
    binding.artifact = {
      ...task.artifact_download,
      query: { ...task.artifact_download.query },
    }
    persistBindings()
    await saveReadyArtifact(taskId, binding.artifact)
  } catch {
    // REST/Backend 短暂不可用时保留绑定，由下一轮统一重试。
  } finally {
    reconciling.delete(taskId)
  }
}

function restoreBindings(): void {
  if (restored || typeof window === 'undefined') return
  restored = true
  const raw = window.sessionStorage.getItem(STORAGE_KEY)
  if (!raw) return
  try {
    const values = JSON.parse(raw)
    if (!Array.isArray(values)) throw new Error('invalid export bindings')
    for (const value of values) {
      const binding = restoreBinding(value)
      if (binding) bindings[binding.taskId] = binding
    }
  } catch {
    window.sessionStorage.removeItem(STORAGE_KEY)
  }
}

function restoreBinding(value: unknown): PendingUserSelectedExport | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (
    !TASK_ID_RE.test(String(record.taskId || ''))
    || !isUserSelectedExportAction(record.action)
    || !['electron', 'browser'].includes(String(record.destinationMode))
    || typeof record.destinationPath !== 'string'
    || (record.destinationMode === 'electron' && !record.destinationPath)
    || typeof record.suggestedName !== 'string'
    || typeof record.fileName !== 'string'
    || typeof record.directoryLabel !== 'string'
    || ![
      'task_running',
      'artifact_ready',
      'saving',
      'save_failed',
      'task_failed',
      'task_cancelled',
    ].includes(String(record.state))
  ) return null
  const definition = exportDefinition(record.action)
  const context = record.context && typeof record.context === 'object'
    ? sanitizeContext(record.context as Record<string, unknown>)
    : {}
  const artifact = restoreArtifact(record.artifact)
  return {
    taskId: String(record.taskId),
    action: record.action,
    module: definition.module,
    destinationMode: record.destinationMode as UserSelectedExportDestination['mode'],
    destinationPath: record.destinationPath,
    suggestedName: record.suggestedName,
    fileName: record.fileName,
    directoryLabel: record.directoryLabel,
    state: record.state === 'saving' ? 'task_running' : record.state as UserSelectedExportState,
    context,
    ...(artifact ? { artifact } : {}),
    ...(typeof record.error === 'string' ? { error: record.error } : {}),
  }
}

function restoreArtifact(value: unknown): NonNullable<TaskItem['artifact_download']> | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  if (
    typeof record.artifact_id !== 'string'
    || typeof record.display_name !== 'string'
    || typeof record.size_bytes !== 'number'
    || typeof record.media_type !== 'string'
    || typeof record.api_path !== 'string'
    || !record.query
    || typeof record.query !== 'object'
  ) return undefined
  const query = Object.fromEntries(Object.entries(record.query).filter((entry): entry is [string, string] => (
    typeof entry[1] === 'string'
  )))
  return {
    artifact_id: record.artifact_id,
    display_name: record.display_name,
    size_bytes: record.size_bytes,
    ...(typeof record.sha256 === 'string' ? { sha256: record.sha256 } : {}),
    media_type: record.media_type,
    api_path: record.api_path,
    query,
  }
}

function persistBindings(): void {
  if (typeof window === 'undefined') return
  const pending = Object.values(bindings).filter((binding) => (
    !['saved', 'browser_started'].includes(binding.state)
  ))
  if (pending.length) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending))
  else window.sessionStorage.removeItem(STORAGE_KEY)
}

function markSaveFailed(binding: PendingUserSelectedExport, message: string): void {
  binding.state = 'save_failed'
  binding.error = message
  persistBindings()
  ElMessage.error(`${message} Artifact 已保留，可在任务中心重新选择保存位置。`)
}

function artifactValidationError(
  artifact: NonNullable<TaskItem['artifact_download']>,
  definition: ReturnType<typeof exportDefinition>,
): string {
  const extension = selectedFileName(artifact.display_name).split('.').pop()?.toLocaleLowerCase() || ''
  const mediaType = artifact.media_type.split(';', 1)[0].trim().toLocaleLowerCase()
  if (!definition.artifactExtensions.includes(extension)) return 'Artifact 文件类型与导出动作不匹配。'
  if (!definition.artifactMediaTypes.includes(mediaType)) return 'Artifact 媒体类型与导出动作不匹配。'
  if (!Number.isSafeInteger(artifact.size_bytes) || artifact.size_bytes < 0) {
    return 'Artifact 大小信息缺失。'
  }
  if (!SHA256_RE.test(artifact.sha256 || '')) return 'Artifact SHA-256 信息缺失。'
  return ''
}

function taskIdFrom(value: unknown): string {
  if (!value || typeof value !== 'object') throw new TypeError('导出 API 未返回任务')
  const record = value as Record<string, unknown>
  const taskId = String(record.task_id || record.id || '')
  if (!TASK_ID_RE.test(taskId)) throw new TypeError('导出 API 未返回有效任务标识')
  return taskId
}

function sanitizeContext(
  value: Record<string, unknown>,
): Record<string, string | number | boolean> {
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, string | number | boolean] => {
    const item = entry[1]
    return typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
  }))
}

function validateSuggestedName(value: string, extensions: string[]): string {
  const name = selectedFileName(value.trim())
  if (
    !name
    || name.length > 180
    || /[\u0000-\u001f<>:"/\\|?*]/.test(name)
    || !extensions.some((extension) => name.toLocaleLowerCase().endsWith(`.${extension}`))
  ) {
    throw new TypeError('导出建议文件名无效')
  }
  return name
}

function selectedFileName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || ''
}

function selectedDirectoryLabel(path: string): string {
  const normalized = path.replace(/[\\/]+$/, '')
  const separator = Math.max(normalized.lastIndexOf('\\'), normalized.lastIndexOf('/'))
  return separator > 0 ? normalized.slice(0, separator) : '用户选择的目录'
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback
}
