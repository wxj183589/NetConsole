import { randomUUID } from 'node:crypto'
import { open, rename, rm } from 'node:fs/promises'
import { basename, dirname, resolve } from 'node:path'

import {
  DESKTOP_SESSION_HEADER,
  type BackendDownloadRequest,
  type BackendDownloadResult,
} from '../shared/bridge'
import {
  buildBackendRequestPath,
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
    if (this.shuttingDown) return { status: 'failed', error: '桌面正在退出，无法开始下载。' }
    const request = validateBackendDownloadRequest(value)
    const selection = await this.options.dialog.showSaveDialog(window, {
      defaultPath: request.suggestedName,
      ...(request.filters ? { filters: request.filters } : {}),
    })
    if (selection.canceled || !selection.filePath) return { status: 'cancelled' }
    if (this.shuttingDown) return { status: 'failed', error: '桌面正在退出，无法开始下载。' }

    const finalPath = normalizeAbsolutePath(selection.filePath)
    const finalPathKey = targetPathKey(finalPath)
    if (this.activeFinalPaths.has(finalPathKey)) {
      return { status: 'failed', error: '该目标文件已有下载正在进行。' }
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
    try {
      const runtime = this.options.backend.getRuntimeInfo()
      const url = managedBackendUrl(runtime, request)
      const response = await this.fetchImpl(url, {
        headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
        redirect: 'error',
        signal: controller.signal,
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      if (!response.body) throw new Error('empty response body')
      await streamResponseToFile(response.body, tempPath)
      await rename(tempPath, finalPath)
      const capabilityId = this.options.pathRegistry.grantCapability(finalPath)
      this.logger('ELECTRON_BACKEND_DOWNLOAD_SAVED', `route=${route}`)
      return { status: 'saved', capabilityId }
    } catch (cause) {
      await rm(tempPath, { force: true }).catch(() => undefined)
      this.logger(
        'ELECTRON_BACKEND_DOWNLOAD_FAILED',
        `route=${route} error=${downloadErrorCode(cause)}`,
      )
      return { status: 'failed', error: '文件下载失败，请重试。' }
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

async function streamResponseToFile(
  body: ReadableStream<Uint8Array>,
  tempPath: string,
): Promise<void> {
  const handle = await open(tempPath, 'wx')
  const reader = body.getReader()
  try {
    while (true) {
      const chunk = await reader.read()
      if (chunk.done) break
      if (chunk.value.byteLength) await handle.writeFile(chunk.value)
    }
    await handle.sync()
  } catch (cause) {
    await reader.cancel().catch(() => undefined)
    throw cause
  } finally {
    reader.releaseLock()
    await handle.close()
  }
}

function downloadErrorCode(cause: unknown): string {
  if (cause instanceof Error) {
    if (cause.name === 'AbortError') return 'ABORTED'
    if (/^HTTP \d{3}$/.test(cause.message)) return cause.message.replace(' ', '_')
    if (/backend URL|backend is not ready/i.test(cause.message)) return 'BACKEND_UNAVAILABLE'
  }
  return 'STREAM_OR_FILE_ERROR'
}

function downloadRouteCategory(apiPath: string): string {
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
