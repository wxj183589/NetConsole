import { createHash, randomUUID } from 'node:crypto'
import { open, rename, rm, stat } from 'node:fs/promises'
import { basename, dirname, resolve } from 'node:path'

import {
  DESKTOP_SESSION_HEADER,
  type BackendDownloadErrorCode,
  type BackendDownloadRequest,
  type BackendDownloadResult,
} from '../shared/bridge'
import {
  buildBackendRequestPath,
  isOpenableArtifactFileName,
  validateArtifactFileName,
  validateBackendDownloadRequest,
} from '../shared/validation'
import type { BackendRuntimeInfo } from './backend-manager'
import type { DesktopLogger } from './logger'
import { GrantedPathRegistry, normalizeAbsolutePath } from './path-access'

interface DownloadDialog {
  showSaveDialog(
    window: unknown,
    options: {
      defaultPath: string
      filters?: Array<{ name: string; extensions: string[] }>
    },
  ): Promise<{ canceled: boolean; filePath?: string }>
}

interface DownloadBackend {
  getRuntimeInfo(): BackendRuntimeInfo
}

export interface BackendDownloadManagerOptions {
  backend: DownloadBackend
  dialog: DownloadDialog
  window: unknown
  pathRegistry: GrantedPathRegistry
  fetchImpl?: typeof fetch
  createTempId?: () => string
  statImpl?: (path: string) => Promise<{ isFile(): boolean; size: number }>
  logger?: DesktopLogger
}

export class BackendDownloadManager {
  private readonly fetchImpl: typeof fetch
  private readonly createTempId: () => string
  private readonly logger: DesktopLogger
  private readonly activeControllers = new Set<AbortController>()
  private readonly activeDownloads = new Set<Promise<BackendDownloadResult>>()
  private readonly activeFinalPaths = new Set<string>()
  private shuttingDown = false

  constructor(private readonly options: BackendDownloadManagerOptions) {
    this.fetchImpl = options.fetchImpl ?? fetch
    this.createTempId = options.createTempId ?? randomUUID
    this.logger = options.logger ?? (() => undefined)
  }

  async download(value: unknown, window = this.options.window): Promise<BackendDownloadResult> {
    if (this.shuttingDown) {
      return failedResult('DESKTOP_SHUTTING_DOWN', '桌面正在退出，无法开始下载。')
    }
    const request = validateBackendDownloadRequest(value)
    const route = downloadRouteCategory(request.apiPath)
    const selection = request.destinationPath
      ? { canceled: false, filePath: this.options.pathRegistry.requireSavePath(request.destinationPath) }
      : await this.showSaveDialog(request, window, route)
    if (selection.canceled || !selection.filePath) {
      this.logger('ARTIFACT_SAVE_DIALOG_CANCELLED', `route=${route}`)
      return { status: 'cancelled' }
    }
    this.logger(
      'ARTIFACT_SAVE_TARGET_SELECTED',
      `route=${route} file=${basename(selection.filePath)}`,
    )
    if (this.shuttingDown) {
      return failedResult('DESKTOP_SHUTTING_DOWN', '桌面正在退出，无法开始下载。')
    }

    const finalPath = normalizeAbsolutePath(selection.filePath)
    try {
      if (validateArtifactFileName(basename(finalPath)) !== validateArtifactFileName(request.suggestedName)) {
        return failedResult('FILE_TYPE_MISMATCH', '保存文件类型与 Artifact 不一致。')
      }
    } catch {
      return failedResult('FILE_TYPE_MISMATCH', '保存文件类型与 Artifact 不一致。')
    }
    const finalPathKey = targetPathKey(finalPath)
    if (this.activeFinalPaths.has(finalPathKey)) {
      return failedResult('DOWNLOAD_IN_PROGRESS', '该目标文件已有下载正在进行。')
    }
    this.activeFinalPaths.add(finalPathKey)
    const tempPath = resolve(
      dirname(finalPath),
      `.${basename(finalPath)}.${this.createTempId()}.part`,
    )
    const controller = new AbortController()
    const operation = this.performDownload(request, finalPath, tempPath, controller)
    this.activeControllers.add(controller)
    this.activeDownloads.add(operation)
    try {
      return await operation
    } finally {
      this.activeControllers.delete(controller)
      this.activeDownloads.delete(operation)
      this.activeFinalPaths.delete(finalPathKey)
    }
  }

  private async showSaveDialog(
    request: BackendDownloadRequest,
    requestedWindow: unknown,
    route: string,
  ): Promise<{ canceled: boolean; filePath?: string }> {
    const window = prepareDialogWindow(requestedWindow, this.options.window)
    const state = windowStateLabel(window)
    this.logger('ARTIFACT_SAVE_DIALOG_PARENT', `route=${route} ${state}`)
    this.logger('ARTIFACT_SAVE_DIALOG_OPENED', `route=${route} file=${request.suggestedName}`)
    return this.options.dialog.showSaveDialog(window, {
      defaultPath: request.suggestedName,
      ...(request.filters ? { filters: request.filters } : {}),
    })
  }

  async shutdown(): Promise<void> {
    this.shuttingDown = true
    for (const controller of this.activeControllers) controller.abort()
    await Promise.allSettled([...this.activeDownloads])
  }

  private async performDownload(
    request: BackendDownloadRequest,
    finalPath: string,
    tempPath: string,
    controller: AbortController,
  ): Promise<BackendDownloadResult> {
    const route = downloadRouteCategory(request.apiPath)
    let finalPathCommitted = false
    try {
      const runtime = this.options.backend.getRuntimeInfo()
      const url = managedBackendUrl(runtime, request)
      const response = await this.fetchImpl(url, {
        headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
        redirect: 'error',
        signal: controller.signal,
      })
      if (response.status === 404) {
        throw new DownloadFailure('ARTIFACT_NOT_FOUND', '导出文件已失效，请重新导出。')
      }
      if (!response.ok) {
        throw new DownloadFailure(
          'BACKEND_DOWNLOAD_FAILED',
          `下载服务返回 HTTP ${response.status}，请稍后重试。`,
        )
      }
      if (!response.body) {
        throw new DownloadFailure('BACKEND_DOWNLOAD_FAILED', '下载服务未返回文件内容。')
      }
      validateContentLength(response, request.expectedSizeBytes)
      this.logger('ARTIFACT_DOWNLOAD_STARTED', `route=${route} file=${basename(finalPath)}`)
      const downloaded = await streamResponseToFile(response.body, tempPath)
      validateDownloadedFile(downloaded, request)
      this.logger('ARTIFACT_DOWNLOAD_VERIFIED', `route=${route} file=${basename(finalPath)} size=${downloaded.sizeBytes}`)
      await rename(tempPath, finalPath)
      finalPathCommitted = true
      await verifyCommittedFile(finalPath, downloaded, this.options.statImpl ?? stat)
      const capabilityId = isOpenableArtifactFileName(basename(finalPath))
        ? this.options.pathRegistry.grantCapability(finalPath)
        : undefined
      this.logger('ARTIFACT_LOCAL_FILE_COMMITTED', `route=${route} file=${basename(finalPath)} size=${downloaded.sizeBytes}`)
      this.logger('ELECTRON_BACKEND_DOWNLOAD_SAVED', `route=${route}`)
      return {
        status: 'saved',
        ...(capabilityId ? { capabilityId } : {}),
        fileName: basename(finalPath),
        directoryLabel: '用户选择的目录',
        sizeBytes: downloaded.sizeBytes,
        sha256: downloaded.sha256,
      }
    } catch (cause) {
      await rm(tempPath, { force: true }).catch(() => undefined)
      if (finalPathCommitted) await rm(finalPath, { force: true }).catch(() => undefined)
      this.logger(
        'ARTIFACT_SAVE_FAILED',
        `route=${route} file=${basename(finalPath)} error_code=${downloadErrorCode(cause)}`,
      )
      this.logger(
        'ELECTRON_BACKEND_DOWNLOAD_FAILED',
        `route=${route} error=${downloadErrorCode(cause)}`,
      )
      return downloadFailureResult(cause)
    }
  }
}

function managedBackendUrl(
  runtime: BackendRuntimeInfo,
  request: BackendDownloadRequest,
): string {
  let base: URL
  try {
    base = new URL(runtime.baseUrl)
  } catch {
    throw new Error('invalid backend URL')
  }
  if (
    base.protocol !== 'http:'
    || base.hostname !== '127.0.0.1'
    || !base.port
    || base.username
    || base.password
    || base.pathname !== '/'
    || base.search
    || base.hash
  ) {
    throw new Error('untrusted backend URL')
  }
  if (
    runtime.apiToken
    && (
      containsSecret(request.apiPath, runtime.apiToken)
      || Object.values(request.query ?? {}).some((value) => containsSecret(value, runtime.apiToken))
    )
  ) {
    throw new Error('runtime token is not allowed in URL')
  }
  const url = new URL(buildBackendRequestPath(request), `${base.origin}/`)
  if (url.origin !== base.origin) throw new Error('backend URL origin mismatch')
  return url.toString()
}

interface DownloadedFileIntegrity {
  sizeBytes: number
  sha256: string
}

interface DialogParentWindow {
  id?: unknown
  isDestroyed?: () => boolean
  isMinimized?: () => boolean
  isVisible?: () => boolean
  isFocused?: () => boolean
  restore?: () => void
  show?: () => void
  focus?: () => void
}

function prepareDialogWindow(requestedWindow: unknown, fallbackWindow: unknown): unknown {
  const candidate = isUsableDialogWindow(requestedWindow)
    ? requestedWindow as DialogParentWindow
    : isUsableDialogWindow(fallbackWindow)
      ? fallbackWindow as DialogParentWindow
      : requestedWindow
  if (!isUsableDialogWindow(candidate)) return candidate
  if (candidate.isMinimized?.()) candidate.restore?.()
  if (!candidate.isVisible?.()) candidate.show?.()
  candidate.focus?.()
  return candidate
}

function isUsableDialogWindow(value: unknown): value is DialogParentWindow {
  return Boolean(value)
    && typeof value === 'object'
    && !(value as DialogParentWindow).isDestroyed?.()
}

function windowStateLabel(value: unknown): string {
  if (!isUsableDialogWindow(value)) return 'window_id=unknown visible=unknown focused=unknown minimized=unknown'
  const window = value as DialogParentWindow
  const id = typeof window.id === 'number' || typeof window.id === 'string' ? window.id : 'unknown'
  return [
    `window_id=${id}`,
    `visible=${Boolean(window.isVisible?.())}`,
    `focused=${Boolean(window.isFocused?.())}`,
    `minimized=${Boolean(window.isMinimized?.())}`,
  ].join(' ')
}

async function streamResponseToFile(
  body: ReadableStream<Uint8Array>,
  tempPath: string,
): Promise<DownloadedFileIntegrity> {
  const handle = await open(tempPath, 'wx')
  const reader = body.getReader()
  const digest = createHash('sha256')
  let sizeBytes = 0
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      if (chunk.value.byteLength) {
        await handle.writeFile(chunk.value)
        digest.update(chunk.value)
        sizeBytes += chunk.value.byteLength
      }
    }
    await handle.sync()
    return { sizeBytes, sha256: digest.digest('hex') }
  } catch (cause) {
    await reader.cancel().catch(() => undefined)
    throw cause
  } finally {
    reader.releaseLock()
    await handle.close()
  }
}

async function verifyCommittedFile(
  finalPath: string,
  downloaded: DownloadedFileIntegrity,
  statImpl: (path: string) => Promise<{ isFile(): boolean; size: number }>,
): Promise<void> {
  const committed = await statImpl(finalPath)
  if (!committed.isFile() || committed.size !== downloaded.sizeBytes) {
    throw new DownloadFailure('FILE_INTEGRITY_MISMATCH', '文件完整性校验失败，请重新下载。')
  }
}

function validateContentLength(response: Response, expectedSizeBytes?: number): void {
  if (expectedSizeBytes === undefined) return
  const header = response.headers.get('content-length')
  if (header === null) return
  const contentLength = Number(header)
  if (!Number.isSafeInteger(contentLength) || contentLength < 0 || contentLength !== expectedSizeBytes) {
    throw new DownloadFailure('FILE_INTEGRITY_MISMATCH', '文件完整性校验失败，请重新下载。')
  }
}

function validateDownloadedFile(
  downloaded: DownloadedFileIntegrity,
  request: BackendDownloadRequest,
): void {
  if (request.expectedSizeBytes === undefined || request.expectedSha256 === undefined) return
  if (
    downloaded.sizeBytes !== request.expectedSizeBytes
    || downloaded.sha256 !== request.expectedSha256
  ) {
    throw new DownloadFailure('FILE_INTEGRITY_MISMATCH', '文件完整性校验失败，请重新下载。')
  }
}

class DownloadFailure extends Error {
  constructor(
    readonly code: BackendDownloadErrorCode,
    message: string,
  ) {
    super(message)
    this.name = 'DownloadFailure'
  }
}

function failedResult(
  errorCode: BackendDownloadErrorCode,
  error: string,
): BackendDownloadResult {
  return { status: 'failed', errorCode, error }
}

function downloadFailureResult(cause: unknown): BackendDownloadResult {
  if (cause instanceof DownloadFailure) return failedResult(cause.code, cause.message)
  const code = nodeErrorCode(cause)
  if (code === 'ENOSPC') return failedResult('DISK_FULL', '磁盘空间不足，无法保存导出文件。')
  if (code === 'EACCES' || code === 'EPERM' || code === 'EROFS') {
    return failedResult('PATH_NOT_WRITABLE', '无法写入所选目录，请选择其他目录。')
  }
  return failedResult('BACKEND_DOWNLOAD_FAILED', '文件下载失败，请重试。')
}

function nodeErrorCode(cause: unknown): string {
  return cause instanceof Error && 'code' in cause
    ? String((cause as Error & { code?: unknown }).code || '')
    : ''
}

function downloadErrorCode(cause: unknown): string {
  if (cause instanceof DownloadFailure) return cause.code
  const code = nodeErrorCode(cause)
  if (code) return code
  if (cause instanceof Error) {
    if (cause.name === 'AbortError') return 'ABORTED'
    if (/^HTTP \d{3}$/.test(cause.message)) return cause.message.replace(' ', '_')
    if (/backend URL|backend is not ready/i.test(cause.message)) return 'BACKEND_UNAVAILABLE'
  }
  return 'STREAM_OR_FILE_ERROR'
}

function downloadRouteCategory(apiPath: string): string {
  if (apiPath.startsWith('/api/device-management/')) return 'device_management'
  if (apiPath.startsWith('/api/file-management/')) return 'file_management'
  if (apiPath.startsWith('/api/config-collection/')) return 'config_collection'
  if (apiPath.startsWith('/api/rail-transit/mesh-analysis/')) return 'mesh_analysis'
  return 'api'
}

function containsSecret(value: string, secret: string): boolean {
  if (value.includes(secret)) return true
  try {
    return decodeURIComponent(value).includes(secret)
  } catch {
    return false
  }
}

function targetPathKey(value: string): string {
  return process.platform === 'win32' ? value.toLowerCase() : value
}
