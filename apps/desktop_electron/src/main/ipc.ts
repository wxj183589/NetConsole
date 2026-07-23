import { isAbsolute, resolve } from 'node:path'

import type { AppInfo, BackendStatus, DesktopResolvedTheme, DesktopRuntimeConfig, NativeActionResult, RendererHostReport, RendererRecoveryState, RendererWorkloadReport, SettingsThemeColor, SiteStorageRestartRequest, TaskWindowContext } from '../shared/bridge'
import {
  DESKTOP_HANDLED_CHANNELS,
  DESKTOP_IPC,
  DESKTOP_SESSION_HEADER,
  SETTINGS_TOOL_DEFINITIONS,
  settingsToolNameMatches,
} from '../shared/bridge'
import {
  validateChooseSavePathOptions,
  validateExternalUrl,
  validateFileDesktopActionRef,
  validateRendererReadyReport,
  validateRendererWorkloadReport,
  validateSelectFileOptions,
  validateTaskWindowContext,
  validateBridgePath,
  validateSiteStorageRestartRequest,
  validateSettingsActionId, validateSettingsDirectoryId, validateSettingsToolId,
  validateUiPreferenceKey, validateUiPreferenceValue,
} from '../shared/validation'
import type { BackendRuntimeInfo } from './backend-manager'
import { BackendDownloadManager } from './backend-download'
import type { DesktopLogger } from './logger'
import { resolveDesktopBackgroundColor } from './config'
import { GrantedPathRegistry } from './path-access'
import type { UiPreferenceStoreLike } from './ui-preferences'

interface IpcEventLike {
  sender: unknown
  senderFrame?: { url: string } | null
}

interface ThemeWindowLike {
  setBackgroundColor(color: string): void
}

interface IpcMainLike {
  handle(channel: string, listener: (event: IpcEventLike, value?: unknown) => unknown): void
  removeHandler(channel: string): void
  on(channel: string, listener: (event: IpcEventLike, value?: unknown) => void): void
}

interface DialogLike {
  showOpenDialog(
    window: unknown,
    options: {
      properties: Array<'openFile' | 'openDirectory' | 'multiSelections'>
      filters?: Array<{ name: string; extensions: string[] }>
    },
  ): Promise<{ canceled: boolean; filePaths: string[] }>
  showSaveDialog(
    window: unknown,
    options: {
      defaultPath: string
      filters?: Array<{ name: string; extensions: string[] }>
    },
  ): Promise<{ canceled: boolean; filePath?: string }>
  showMessageBox(window: unknown, options: { type: 'question'; title: string; message: string; buttons: string[]; cancelId: number }): Promise<{ response: number }>
}

interface ShellLike {
  openPath(path: string): Promise<string>
  showItemInFolder(path: string): void
  openExternal(url: string): Promise<void>
}

interface BackendLike {
  getStatus(): BackendStatus
  getRuntimeInfo(): BackendRuntimeInfo
}

export interface DesktopIpcDependencies {
  ipcMain: IpcMainLike
  dialog: DialogLike
  shell: ShellLike
  window: unknown
  windowForEvent?: (event: IpcEventLike) => unknown
  openTaskWindow?: (value: TaskWindowContext) => Promise<NativeActionResult> | NativeActionResult
  restartBackend?: (value: SiteStorageRestartRequest) => Promise<void>
  appInfo: AppInfo
  backend: BackendLike
  pathRegistry?: GrantedPathRegistry
  isTrustedSender: (event: IpcEventLike) => boolean
  onRendererReady?: (report: RendererHostReport, window: unknown) => void
  onRendererWorkload?: (report: RendererWorkloadReport, window: unknown) => void
  getRendererRecoveryState?: (window: unknown) => RendererRecoveryState | null
  logger?: DesktopLogger
  fetchImpl?: typeof fetch
  uiPreferenceStore?: UiPreferenceStoreLike
}

export interface DesktopIpcRegistration {
  shutdown(): Promise<void>
}

export function registerDesktopIpc(
  dependencies: DesktopIpcDependencies,
): DesktopIpcRegistration {
  const registry = dependencies.pathRegistry ?? new GrantedPathRegistry()
  const downloadManager = new BackendDownloadManager({
    backend: dependencies.backend,
    dialog: dependencies.dialog,
    window: dependencies.window,
    pathRegistry: registry,
    logger: dependencies.logger,
  })
  for (const channel of DESKTOP_HANDLED_CHANNELS) dependencies.ipcMain.removeHandler(channel)

  const trusted = <T>(handler: (value: unknown, event: IpcEventLike) => T | Promise<T>) => (
    event: IpcEventLike,
    value?: unknown,
  ): T | Promise<T> => {
    if (!dependencies.isTrustedSender(event)) throw new Error('拒绝来自未知渲染进程的桌面请求')
    return handler(value, event)
  }

  dependencies.ipcMain.handle(
    DESKTOP_IPC.openTaskWindow,
    trusted(async (value) => {
      if (!dependencies.openTaskWindow) return { success: false, error: '任务窗口尚未就绪' }
      return dependencies.openTaskWindow(validateTaskWindowContext(value))
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getAppInfo,
    trusted(() => ({ ...dependencies.appInfo })),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getBackendStatus,
    trusted(() => {
      const status = dependencies.backend.getStatus()
      return {
        state: status.state,
        ...(status.baseUrl ? { baseUrl: status.baseUrl } : {}),
        ...(status.error ? { error: '本地后端不可用' } : {}),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getRuntimeConfig,
    trusted((): DesktopRuntimeConfig => {
      const runtime = dependencies.backend.getRuntimeInfo()
      return { apiBaseUrl: runtime.baseUrl, apiToken: runtime.apiToken }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getUiPreference,
    trusted(async (value) => {
      const key = validateUiPreferenceKey(value)
      const stored = await dependencies.uiPreferenceStore?.get(key)
      return stored == null ? null : validateUiPreferenceValue(key, stored)
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.setUiPreference,
    trusted(async (value) => {
      if (!Array.isArray(value) || value.length !== 2) throw new TypeError('UI preference request is invalid')
      const key = validateUiPreferenceKey(value[0])
      const preference = validateUiPreferenceValue(key, value[1])
      await dependencies.uiPreferenceStore?.set(key, preference)
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectFile,
    trusted(async (value, event) => {
      const options = validateSelectFileOptions(value)
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        properties: ['openFile', ...(options.multiple ? ['multiSelections' as const] : [])],
        ...(options.filters ? { filters: options.filters } : {}),
      })
      return {
        cancelled: result.canceled,
        paths: result.canceled ? [] : registry.grantAll(result.filePaths),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectDirectory,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        properties: ['openDirectory'],
      })
      const selected = result.canceled ? undefined : result.filePaths[0]
      return {
        cancelled: !selected,
        ...(selected ? { path: registry.grant(selected, 'directory') } : {}),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSettingsTool,
    trusted(async (value, event) => {
      const toolId = validateSettingsToolId(value)
      const definition = SETTINGS_TOOL_DEFINITIONS[toolId]
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        properties: ['openFile'], filters: [{ name: definition.filterName, extensions: ['exe'] }],
      })
      const selected = result.canceled ? undefined : result.filePaths[0]
      if (!selected) return { cancelled: true }
      if (!isAbsolute(selected) || !settingsToolNameMatches(toolId, selected)) {
        throw new Error('settings tool selection does not match tool id')
      }
      return { cancelled: false, path: selected }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSettingsDirectory,
    trusted(async (value, event) => {
      validateSettingsDirectoryId(value)
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, { properties: ['openDirectory'] })
      const selected = result.canceled ? undefined : result.filePaths[0]
      if (selected && !isAbsolute(selected)) throw new Error('settings directory must be absolute')
      return { cancelled: !selected, ...(selected ? { path: selected } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSettingsColor,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showMessageBox(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        type: 'question', title: '选择主题色', message: '选择 NetConsole 主题强调色',
        buttons: [...SETTINGS_COLORS, '取消'], cancelId: SETTINGS_COLORS.length,
      })
      const color = SETTINGS_COLORS[result.response]
      return { cancelled: !color, ...(color ? { color } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.executeSettingsAction,
    trusted((value) => executeSettingsAction(
      dependencies.backend, validateSettingsActionId(value), dependencies.fetchImpl ?? fetch, dependencies.logger,
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectDataRootDirectory,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, { properties: ['openDirectory'] })
      const selected = result.canceled ? undefined : result.filePaths[0]
      return { cancelled: !selected, ...(selected ? { path: validateBridgePath(selected) } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSitePackage,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        properties: ['openFile'], filters: [{ name: 'NetConsole 局点包', extensions: ['ncsite'] }],
      })
      const selected = result.canceled ? undefined : result.filePaths[0]
      return { cancelled: !selected, ...(selected ? { path: validateBridgePath(selected) } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSiteExportDestination,
    trusted(async (value, event) => {
      const suggestedName = validateChooseSavePathOptions({ suggestedName: value, filters: [{ name: 'NetConsole 局点包', extensions: ['ncsite'] }] }).suggestedName
      const result = await dependencies.dialog.showSaveDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        defaultPath: suggestedName, filters: [{ name: 'NetConsole 局点包', extensions: ['ncsite'] }],
      })
      return { cancelled: result.canceled || !result.filePath, ...(!result.canceled && result.filePath ? { path: validateBridgePath(result.filePath) } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.restartBackend,
    trusted(async (value) => {
      try {
        await dependencies.restartBackend?.(validateSiteStorageRestartRequest(value))
        return { success: true }
      } catch {
        return { success: false, error: '本地 Backend 重启失败，请检查日志后重试。' }
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.chooseSavePath,
    trusted(async (value, event) => {
      const options = validateChooseSavePathOptions(value)
      const result = await dependencies.dialog.showSaveDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        defaultPath: options.directoryPath
          ? resolve(registry.requireDirectoryPath(options.directoryPath), options.suggestedName)
          : options.suggestedName,
        ...(options.filters ? { filters: options.filters } : {}),
      })
      return {
        cancelled: result.canceled || !result.filePath,
        ...(!result.canceled && result.filePath ? { path: registry.grant(result.filePath, 'save') } : {}),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.downloadBackendResource,
    trusted((value, event) => downloadManager.download(value, dependencies.windowForEvent?.(event) ?? dependencies.window)),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.executeFileDesktopAction,
    trusted((value) => executeFileDesktopAction(
      dependencies.backend,
      validateFileDesktopActionRef(value),
      dependencies.fetchImpl ?? fetch,
      dependencies.logger,
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.rendererRecoveryState,
    trusted((_value, event) => (
      dependencies.getRendererRecoveryState?.(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
      ) ?? null
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openPath,
    trusted(async (value) => {
      try {
        const path = registry.requireCapability(value, 'artifact-download', 'open')
        const error = await dependencies.shell.openPath(path)
        return error
          ? { success: false, error: '系统未能打开所选路径' }
          : { success: true }
      } catch (cause) {
        return { success: false, error: safeActionError(cause) }
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.showItemInFolder,
    trusted((value) => {
      try {
        dependencies.shell.showItemInFolder(registry.requireCapability(value, 'artifact-download', 'reveal'))
        return { success: true }
      } catch (cause) {
        return { success: false, error: safeActionError(cause) }
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openExternalUrl,
    trusted(async (value) => {
      try {
        await dependencies.shell.openExternal(validateExternalUrl(value))
        return { success: true }
      } catch (cause) {
        return { success: false, error: safeActionError(cause) }
      }
    }),
  )
  dependencies.ipcMain.on(DESKTOP_IPC.rendererReady, (event, value) => {
    if (!dependencies.isTrustedSender(event)) {
      dependencies.logger?.('ELECTRON_RENDERER_READY_UNTRUSTED')
      return
    }
    try {
      const report = validateRendererReadyReport(value)
      const window = dependencies.windowForEvent?.(event) ?? dependencies.window
      if ('resolvedTheme' in report) {
        updateWindowTheme(window, report.resolvedTheme)
      }
      dependencies.onRendererReady?.(report, window)
    } catch {
      dependencies.logger?.('ELECTRON_RENDERER_READY_REJECTED')
    }
  })
  dependencies.ipcMain.on(DESKTOP_IPC.rendererWorkload, (event, value) => {
    if (!dependencies.isTrustedSender(event)) {
      dependencies.logger?.('ELECTRON_RENDERER_WORKLOAD_UNTRUSTED')
      return
    }
    try {
      dependencies.onRendererWorkload?.(
        validateRendererWorkloadReport(value),
        dependencies.windowForEvent?.(event) ?? dependencies.window,
      )
    } catch {
      dependencies.logger?.('ELECTRON_RENDERER_WORKLOAD_REJECTED')
    }
  })
  return { shutdown: () => downloadManager.shutdown() }
}

function updateWindowTheme(window: unknown, theme: DesktopResolvedTheme): void {
  if (!hasThemeBackground(window)) throw new TypeError('managed window is unavailable')
  window.setBackgroundColor(resolveDesktopBackgroundColor(theme))
}

function hasThemeBackground(value: unknown): value is ThemeWindowLike {
  return typeof value === 'object'
    && value !== null
    && typeof (value as { setBackgroundColor?: unknown }).setBackgroundColor === 'function'
}

const SETTINGS_COLORS: readonly SettingsThemeColor[] = ['#0078D4', '#2563EB', '#0891B2', '#16A34A']

function safeActionError(cause: unknown): string {
  if (cause instanceof Error && /文件授权|桌面桥接只允许/.test(cause.message)) {
    return cause.message
  }
  return '桌面操作失败'
}

async function executeFileDesktopAction(
  backend: BackendLike,
  actionRef: string,
  fetchImpl: typeof fetch,
  logger: DesktopLogger = () => undefined,
): Promise<{ success: boolean; error?: string }> {
  try {
    const runtime = backend.getRuntimeInfo()
    const base = new URL(runtime.baseUrl)
    if (
      base.protocol !== 'http:'
      || base.hostname !== '127.0.0.1'
      || !base.port
      || base.pathname !== '/'
      || base.username
      || base.password
      || base.search
      || base.hash
    ) throw new Error('untrusted backend')
    const url = new URL(`/api/file-management/desktop-actions/${actionRef}/execute`, base.origin)
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
      redirect: 'error',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const body = await response.json() as { success?: unknown }
    if (body.success !== true) throw new Error('action rejected')
    logger('ELECTRON_FILE_DESKTOP_ACTION_COMPLETED')
    return { success: true }
  } catch {
    logger('ELECTRON_FILE_DESKTOP_ACTION_FAILED')
    return { success: false, error: '桌面操作失败，请检查本机设置后重试。' }
  }
}

async function executeSettingsAction(
  backend: BackendLike, action: string, fetchImpl: typeof fetch, logger: DesktopLogger = () => undefined,
): Promise<{ success: boolean; error?: string }> {
  try {
    const runtime = backend.getRuntimeInfo()
    const base = new URL(runtime.baseUrl)
    if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || !base.port || base.pathname !== '/') throw new Error('untrusted backend')
    const response = await fetchImpl(new URL('/api/settings/native-action', base.origin), {
      method: 'POST', headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken, 'content-type': 'application/json' },
      body: JSON.stringify({ action }), redirect: 'error',
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    logger('ELECTRON_SETTINGS_ACTION_COMPLETED')
    return { success: true }
  } catch {
    logger('ELECTRON_SETTINGS_ACTION_FAILED')
    return { success: false, error: '系统设置本机操作失败' }
  }
}
