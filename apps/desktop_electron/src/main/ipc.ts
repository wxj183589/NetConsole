import { isAbsolute, resolve } from 'node:path'
import { lstat } from 'node:fs/promises'

import type { AppInfo, BackendStatus, CloseToTrayState, DesktopResolvedTheme, DesktopRuntimeConfig, NativeActionResult, RendererHostReport, RendererRecoveryState, RendererWorkloadReport, SettingsThemeColor, SiteStorageRestartRequest, TaskNotificationPayload, TaskTrayStatus, TaskWindowContext, WorkspaceWindowOpenRequest, WorkspaceWindowSnapshot, WorkspaceWindowStateResult } from '../shared/bridge'
import {
  DESKTOP_HANDLED_CHANNELS,
  DESKTOP_IPC,
  DESKTOP_SESSION_HEADER,
  SETTINGS_TOOL_DEFINITIONS,
  settingsToolNameMatches,
} from '../shared/bridge'
import {
  validateChooseSavePathOptions,
  validateClipboardText,
  validateExternalUrl,
  validateFileDesktopActionRef,
  validateMeshAnalysisSessionId,
  validateOnlineMrSessionId,
  validateRendererReadyReport,
  validateRendererWorkloadReport,
  validateSelectFileOptions,
  validateTaskWindowContext,
  validateTaskNotificationPayload,
  validateTaskTrayStatus,
  validateWorkspaceTitle,
  validateWorkspaceWindowOpenRequest,
  validateWorkspaceWindowSnapshot,
  validateBridgePath,
  validateSiteStorageRestartRequest,
  validateSettingsActionId, validateSettingsDirectoryId, validateSettingsToolId,
  validateUiPreferenceKey, validateUiPreferenceValue,
  validateExternalToolCreateRequest,
  validateExternalToolSystemReferenceCreateRequest,
  validateExternalToolUpdateRequest,
  validateExternalToolId,
  validateExternalToolName,
  validateExternalToolFavoriteRequest,
  validateExternalToolReorderRequest,
  validateExternalToolCategoryReorderRequest,
  validateExternalToolCategoryRenameRequest,
  validateExternalToolDeleteCategoryRequest,
  validateExternalToolLaunchRequest,
} from '../shared/validation'
import type { BackendRuntimeInfo } from './backend-manager'
import { BackendDownloadManager } from './backend-download'
import type { DesktopLogger } from './logger'
import { resolveDesktopBackgroundColor } from './config'
import { GrantedPathRegistry } from './path-access'
import type { UiPreferenceStoreLike } from './ui-preferences'
import type { ExternalToolServiceLike } from './external-tool-service'

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

interface ClipboardLike {
  writeText(text: string): void
}

interface FileStatusLike {
  isFile(): boolean
  isDirectory?(): boolean
  isSymbolicLink(): boolean
}

interface ExternalWindowLike {
  isDestroyed?(): boolean
  isFocused?(): boolean
  isAlwaysOnTop?(): boolean
  setAlwaysOnTop?(flag: boolean): void
  blur?(): void
  minimize?(): void
}

interface BackendLike {
  getStatus(): BackendStatus
  getRuntimeInfo(): BackendRuntimeInfo
}

export interface DesktopIpcDependencies {
  ipcMain: IpcMainLike
  dialog: DialogLike
  shell: ShellLike
  clipboard?: ClipboardLike
  window: unknown
  windowForEvent?: (event: IpcEventLike) => unknown
  openTaskWindow?: (value: TaskWindowContext) => Promise<NativeActionResult> | NativeActionResult
  showTaskNotification?: (value: TaskNotificationPayload) => Promise<NativeActionResult> | NativeActionResult
  setTaskTrayStatus?: (value: TaskTrayStatus) => void
  openWorkspaceWindow?: (value: WorkspaceWindowOpenRequest) => Promise<NativeActionResult> | NativeActionResult
  getWorkspaceWindowState?: (window: unknown) => WorkspaceWindowStateResult
  saveWorkspaceWindowState?: (window: unknown, value: WorkspaceWindowSnapshot) => void
  setWorkspaceWindowTitle?: (window: unknown, title: string) => void
  getCloseToTrayState?: () => CloseToTrayState
  setCloseToTrayEnabled?: (enabled: boolean) => Promise<CloseToTrayState> | CloseToTrayState
  restartBackend?: (value: SiteStorageRestartRequest) => Promise<void>
  refreshSiteContext?: () => Promise<void>
  setSiteSwitching?: (switching: boolean) => void
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
  externalToolService?: ExternalToolServiceLike
  artifactLstat?: (path: string) => Promise<FileStatusLike>
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
      if (!dependencies.openTaskWindow) return { success: false, error: '任务中心尚未就绪' }
      return dependencies.openTaskWindow(validateTaskWindowContext(value))
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openWorkspaceWindow,
    trusted(async (value) => {
      if (!dependencies.openWorkspaceWindow) return { success: false, error: '工作区窗口尚未就绪' }
      return dependencies.openWorkspaceWindow(validateWorkspaceWindowOpenRequest(value))
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getWorkspaceWindowState,
    trusted((_value, event) => {
      if (!dependencies.getWorkspaceWindowState) throw new Error('工作区窗口尚未就绪')
      return dependencies.getWorkspaceWindowState(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
      )
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.saveWorkspaceWindowState,
    trusted((value, event) => {
      if (!dependencies.saveWorkspaceWindowState) throw new Error('工作区窗口尚未就绪')
      dependencies.saveWorkspaceWindowState(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
        validateWorkspaceWindowSnapshot(value),
      )
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getCloseToTrayState,
    trusted(() => dependencies.getCloseToTrayState?.() ?? { enabled: false, available: false }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.setCloseToTrayEnabled,
    trusted((value) => {
      if (typeof value !== 'boolean') throw new TypeError('close-to-tray value is invalid')
      return dependencies.setCloseToTrayEnabled?.(value)
        ?? { enabled: false, available: false }
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
        properties: ['openFile'], filters: [{ name: 'NetConsole 数据包', extensions: ['ncsite', 'ncresult', 'zip'] }],
      })
      const selected = result.canceled ? undefined : result.filePaths[0]
      return { cancelled: !selected, ...(selected ? { path: validateBridgePath(selected) } : {}) }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectSiteExportDestination,
    trusted(async (value, event) => {
      const suggestedName = validateChooseSavePathOptions({ suggestedName: value }).suggestedName
      const resultPackage = suggestedName.toLocaleLowerCase().endsWith('.ncresult')
      const lightweightPackage = suggestedName.toLocaleLowerCase().endsWith('.zip')
      const filters = resultPackage
        ? [{ name: 'NetConsole 采集回传包', extensions: ['ncresult'] }]
        : lightweightPackage
          ? [{ name: 'NetConsole 轻量包', extensions: ['zip'] }]
        : [{ name: 'NetConsole 局点包', extensions: ['ncsite'] }]
      const result = await dependencies.dialog.showSaveDialog(dependencies.windowForEvent?.(event) ?? dependencies.window, {
        defaultPath: suggestedName, filters,
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
      } catch (cause) {
        return { success: false, error: backendRestartErrorMessage(cause) }
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
        ...(!result.canceled && result.filePath ? { path: await registry.grantSavePath(result.filePath) } : {}),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.showTaskNotification,
    trusted(async (value) => {
      if (!dependencies.showTaskNotification) return { success: false, error: '系统通知不可用' }
      return dependencies.showTaskNotification(validateTaskNotificationPayload(value))
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.downloadBackendResource,
    trusted((value, event) => downloadManager.download(value, dependencies.windowForEvent?.(event) ?? dependencies.window)),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.listExternalTools,
    trusted(() => requireExternalToolService(dependencies).list()),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.refreshExternalToolStatuses,
    trusted(() => requireExternalToolService(dependencies).list()),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectExternalToolExecutable,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
        {
          properties: ['openFile'],
          filters: [{ name: 'Windows 程序', extensions: ['exe'] }],
        },
      )
      if (result.canceled || !result.filePaths[0]) return { cancelled: true }
      return requireExternalToolService(dependencies).describeExecutable(result.filePaths[0])
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectExternalToolWorkingDirectory,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
        { properties: ['openDirectory'] },
      )
      return result.canceled || !result.filePaths[0]
        ? { cancelled: true }
        : { cancelled: false, path: result.filePaths[0] }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectExternalToolIcon,
    trusted(async (_value, event) => {
      const result = await dependencies.dialog.showOpenDialog(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
        {
          properties: ['openFile'],
          filters: [{ name: '图片文件', extensions: ['png', 'jpg', 'jpeg', 'ico'] }],
        },
      )
      if (result.canceled || !result.filePaths[0]) return { cancelled: true }
      return requireExternalToolService(dependencies).stageCustomIcon(result.filePaths[0])
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.createExternalTool,
    trusted((value) => requireExternalToolService(dependencies).create(
      validateExternalToolCreateRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.createExternalToolSystemReference,
    trusted((value) => requireExternalToolService(dependencies).createSystemReference(
      validateExternalToolSystemReferenceCreateRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.updateExternalTool,
    trusted((value) => requireExternalToolService(dependencies).update(
      validateExternalToolUpdateRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.deleteExternalTool,
    trusted((value) => requireExternalToolService(dependencies).delete(
      validateExternalToolId(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.setExternalToolFavorite,
    trusted((value) => {
      const request = validateExternalToolFavoriteRequest(value)
      return requireExternalToolService(dependencies).setFavorite(request.toolId, request.favorite)
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.reorderExternalTools,
    trusted((value) => requireExternalToolService(dependencies).reorderTools(
      validateExternalToolReorderRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.reorderExternalToolCategories,
    trusted((value) => requireExternalToolService(dependencies).reorderCategories(
      validateExternalToolCategoryReorderRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.createExternalToolCategory,
    trusted((value) => requireExternalToolService(dependencies).createCategory(
      validateExternalToolName(value, 'category name'),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.renameExternalToolCategory,
    trusted((value) => {
      const request = validateExternalToolCategoryRenameRequest(value)
      return requireExternalToolService(dependencies).renameCategory(request.categoryId, request.name)
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.deleteExternalToolCategory,
    trusted((value) => requireExternalToolService(dependencies).deleteCategory(
      validateExternalToolDeleteCategoryRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.launchExternalTool,
    trusted((value) => requireExternalToolService(dependencies).launch(
      validateExternalToolLaunchRequest(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.revealExternalTool,
    trusted((value) => requireExternalToolService(dependencies).reveal(
      validateExternalToolId(value),
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.executeFileDesktopAction,
    trusted((value, event) => executeFileDesktopAction(
      dependencies.backend,
      validateFileDesktopActionRef(value),
      dependencies.fetchImpl ?? fetch,
      dependencies.shell,
      dependencies.logger,
      dependencies.windowForEvent?.(event) ?? dependencies.window,
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.refreshSiteContext,
    trusted(async () => { await dependencies.refreshSiteContext?.() }),
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
    DESKTOP_IPC.openOnlineMrSessionLocation,
    trusted((value) => openOnlineMrSessionLocation(
      dependencies.backend,
      dependencies.shell,
      validateOnlineMrSessionId(value),
      dependencies.fetchImpl ?? fetch,
      dependencies.logger,
      dependencies.artifactLstat,
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openMeshAnalysisSessionLocation,
    trusted((value) => openMeshAnalysisSessionLocation(
      dependencies.backend,
      dependencies.shell,
      validateMeshAnalysisSessionId(value),
      dependencies.fetchImpl ?? fetch,
      dependencies.logger,
      dependencies.artifactLstat,
    )),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openPath,
    trusted(async (value, event) => {
      const sourceWindow = dependencies.windowForEvent?.(event) ?? dependencies.window
      const handoff = prepareExternalWindowHandoff(sourceWindow)
      try {
        const path = registry.requireCapability(value, 'artifact-download', 'open')
        const unavailable = await artifactPathUnavailable(path, dependencies.artifactLstat)
        if (unavailable) {
          restoreExternalWindowState(sourceWindow, handoff)
          return unavailable
        }
        const error = await dependencies.shell.openPath(path)
        if (error) {
          restoreExternalWindowState(sourceWindow, handoff)
          return await artifactPathUnavailable(path, dependencies.artifactLstat)
            ?? { success: false, error: '系统未能打开所选路径' }
        }
        scheduleExternalWindowHandoff(sourceWindow)
        return { success: true }
      } catch (cause) {
        restoreExternalWindowState(sourceWindow, handoff)
        return { success: false, error: safeActionError(cause) }
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.showItemInFolder,
    trusted(async (value, event) => {
      const sourceWindow = dependencies.windowForEvent?.(event) ?? dependencies.window
      const handoff = prepareExternalWindowHandoff(sourceWindow)
      try {
        const path = registry.requireCapability(value, 'artifact-download', 'reveal')
        const unavailable = await artifactPathUnavailable(path, dependencies.artifactLstat)
        if (unavailable) {
          restoreExternalWindowState(sourceWindow, handoff)
          return unavailable
        }
        dependencies.shell.showItemInFolder(path)
        scheduleExternalWindowHandoff(sourceWindow)
        return { success: true }
      } catch (cause) {
        restoreExternalWindowState(sourceWindow, handoff)
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
  dependencies.ipcMain.handle(
    DESKTOP_IPC.writeClipboardText,
    trusted((value) => {
      if (!dependencies.clipboard) {
        return { success: false, error: '系统剪贴板不可用' }
      }
      try {
        dependencies.clipboard.writeText(validateClipboardText(value))
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
  dependencies.ipcMain.on(DESKTOP_IPC.setWorkspaceWindowTitle, (event, value) => {
    if (!dependencies.isTrustedSender(event)) {
      dependencies.logger?.('ELECTRON_WORKSPACE_TITLE_UNTRUSTED')
      return
    }
    try {
      dependencies.setWorkspaceWindowTitle?.(
        dependencies.windowForEvent?.(event) ?? dependencies.window,
        validateWorkspaceTitle(value),
      )
    } catch {
      dependencies.logger?.('ELECTRON_WORKSPACE_TITLE_REJECTED')
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
  dependencies.ipcMain.on(DESKTOP_IPC.siteSwitchState, (event, value) => {
    if (!dependencies.isTrustedSender(event) || typeof value !== 'boolean') {
      dependencies.logger?.('ELECTRON_SITE_SWITCH_STATE_REJECTED')
      return
    }
    dependencies.setSiteSwitching?.(value)
  })
  dependencies.ipcMain.on(DESKTOP_IPC.setTaskTrayStatus, (event, value) => {
    if (!dependencies.isTrustedSender(event)) {
      dependencies.logger?.('ELECTRON_TASK_TRAY_STATUS_UNTRUSTED')
      return
    }
    try {
      dependencies.setTaskTrayStatus?.(validateTaskTrayStatus(value))
    } catch {
      dependencies.logger?.('ELECTRON_TASK_TRAY_STATUS_REJECTED')
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

async function artifactPathUnavailable(
  path: string,
  inspect: (path: string) => Promise<FileStatusLike> = lstat,
): Promise<NativeActionResult | null> {
  try {
    const status = await inspect(path)
    if (status.isSymbolicLink() || !status.isFile()) {
      return {
        success: false,
        availability: 'INVALID',
        error: '已保存的文件不是可打开的普通文件',
      }
    }
    return null
  } catch (cause) {
    const code = String((cause as { code?: unknown } | null)?.code || '')
    if (code === 'ENOENT' || code === 'ENOTDIR') {
      return {
        success: false,
        availability: 'MISSING',
        error: '已保存的文件不存在，请重新下载后再试',
      }
    }
    return {
      success: false,
      availability: 'INVALID',
      error: '已保存的文件当前不可访问',
    }
  }
}

function safeActionError(cause: unknown): string {
  if (cause instanceof Error && /文件授权|桌面桥接只允许/.test(cause.message)) {
    return cause.message
  }
  return '桌面操作失败'
}

function backendRestartErrorMessage(cause: unknown): string {
  if (!(cause instanceof Error)) return '本地 Backend 重启失败，请检查日志后重试。'
  const allowed = new Set([
    '隔离测试模式不允许修改正式局点或数据根',
    'Backend 重启失败，已恢复原局点。',
    'Backend 重启失败，原局点恢复失败，请重新启动应用。',
  ])
  return allowed.has(cause.message)
    ? cause.message
    : '本地 Backend 重启失败，请检查日志后重试。'
}

interface ExternalWindowHandoff {
  window: ExternalWindowLike | null
  wasAlwaysOnTop: boolean
}

function requireExternalToolService(dependencies: DesktopIpcDependencies): ExternalToolServiceLike {
  if (!dependencies.externalToolService) throw new Error('工具集服务尚未就绪')
  return dependencies.externalToolService
}

function asExternalWindow(value: unknown): ExternalWindowLike | null {
  return value && typeof value === 'object' ? value as ExternalWindowLike : null
}

function prepareExternalWindowHandoff(value: unknown): ExternalWindowHandoff {
  const window = asExternalWindow(value)
  if (!window || window.isDestroyed?.()) return { window: null, wasAlwaysOnTop: false }
  const wasAlwaysOnTop = window.isAlwaysOnTop?.() === true
  if (wasAlwaysOnTop) window.setAlwaysOnTop?.(false)
  window.blur?.()
  return { window, wasAlwaysOnTop }
}

function restoreExternalWindowState(value: unknown, handoff: ExternalWindowHandoff): void {
  const window = handoff.window ?? asExternalWindow(value)
  if (!window || window.isDestroyed?.() || !handoff.wasAlwaysOnTop) return
  window.setAlwaysOnTop?.(true)
}

function scheduleExternalWindowHandoff(value: unknown): void {
  const window = asExternalWindow(value)
  if (!window || window.isDestroyed?.()) return
  const timer = setTimeout(() => {
    if (!window.isDestroyed?.() && window.isFocused?.() === true) window.minimize?.()
  }, 350)
  timer.unref?.()
}

async function executeFileDesktopAction(
  backend: BackendLike,
  actionRef: string,
  fetchImpl: typeof fetch,
  shell: ShellLike,
  logger: DesktopLogger = () => undefined,
  sourceWindow?: unknown,
): Promise<{ success: boolean; error?: string }> {
  let handoff: ExternalWindowHandoff | null = null
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
    const body = await response.json() as { action?: unknown; success?: unknown; target_path?: unknown }
    if (body.success !== true) throw new Error('action rejected')
    if (body.action === 'open_local' || body.action === 'open_result' || body.action === 'open_result_dir') {
      if (typeof body.target_path !== 'string' || !body.target_path) throw new Error('desktop action target missing')
      handoff = prepareExternalWindowHandoff(sourceWindow)
      const error = await shell.openPath(body.target_path)
      if (error) {
        restoreExternalWindowState(sourceWindow, handoff)
        return { success: false, error: '系统未能打开所选路径' }
      }
      scheduleExternalWindowHandoff(sourceWindow)
    }
    logger('ELECTRON_FILE_DESKTOP_ACTION_COMPLETED')
    return { success: true }
  } catch {
    if (handoff) restoreExternalWindowState(sourceWindow, handoff)
    logger('ELECTRON_FILE_DESKTOP_ACTION_FAILED')
    return { success: false, error: '桌面操作失败，请检查本机设置后重试。' }
  }
}

async function openOnlineMrSessionLocation(
  backend: BackendLike,
  shell: ShellLike,
  sessionId: string,
  fetchImpl: typeof fetch,
  logger: DesktopLogger = () => undefined,
  inspect: (path: string) => Promise<FileStatusLike> = lstat,
): Promise<NativeActionResult> {
  return openManagedSessionLocation(
    backend,
    shell,
    sessionId,
    '/api/online-mr/sessions',
    'ONLINE_MR',
    fetchImpl,
    logger,
    inspect,
  )
}

async function openMeshAnalysisSessionLocation(
  backend: BackendLike,
  shell: ShellLike,
  sessionId: string,
  fetchImpl: typeof fetch,
  logger: DesktopLogger = () => undefined,
  inspect: (path: string) => Promise<FileStatusLike> = lstat,
): Promise<NativeActionResult> {
  return openManagedSessionLocation(
    backend,
    shell,
    sessionId,
    '/api/rail-transit/mesh-analysis/sessions',
    'MESH_ANALYSIS',
    fetchImpl,
    logger,
    inspect,
  )
}

async function openManagedSessionLocation(
  backend: BackendLike,
  shell: ShellLike,
  sessionId: string,
  endpointRoot: string,
  logPrefix: 'ONLINE_MR' | 'MESH_ANALYSIS',
  fetchImpl: typeof fetch,
  logger: DesktopLogger = () => undefined,
  inspect: (path: string) => Promise<FileStatusLike> = lstat,
): Promise<NativeActionResult> {
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
    const url = new URL(
      `${endpointRoot}/${encodeURIComponent(sessionId)}/desktop-location`,
      base.origin,
    )
    const response = await fetchImpl(url, {
      method: 'POST',
      headers: { [DESKTOP_SESSION_HEADER]: runtime.apiToken },
      redirect: 'error',
    })
    if (!response.ok) {
      return {
        success: false,
        availability: response.status === 404 ? 'MISSING' : 'INVALID',
        error: await safeBackendActionError(
          response,
          '当前会话没有可打开的本地目录。',
        ),
      }
    }
    const body = await response.json() as { target_type?: unknown; path?: unknown }
    if (
      (body.target_type !== 'file' && body.target_type !== 'directory')
      || typeof body.path !== 'string'
      || !isAbsolute(body.path)
      || body.path.includes('\0')
    ) {
      throw new Error('invalid managed target')
    }
    const unavailable = await managedSessionLocationUnavailable(body.path, body.target_type, inspect)
    if (unavailable) return unavailable
    if (body.target_type === 'file') {
      shell.showItemInFolder(body.path)
    } else {
      const error = await shell.openPath(body.path)
      if (error) {
        return await managedSessionLocationUnavailable(body.path, body.target_type, inspect)
          ?? { success: false, availability: 'INVALID', error: '系统未能打开该会话目录。' }
      }
    }
    logger(`ELECTRON_${logPrefix}_LOCATION_OPENED`)
    return { success: true, availability: 'AVAILABLE' }
  } catch {
    logger(`ELECTRON_${logPrefix}_LOCATION_FAILED`)
    return { success: false, availability: 'INVALID', error: '打开会话本地目录失败，请检查文件是否仍存在。' }
  }
}

async function managedSessionLocationUnavailable(
  path: string,
  targetType: 'file' | 'directory',
  inspect: (path: string) => Promise<FileStatusLike> = lstat,
): Promise<NativeActionResult | null> {
  try {
    const status = await inspect(path)
    const validType = targetType === 'file'
      ? status.isFile()
      : typeof status.isDirectory === 'function' && status.isDirectory()
    if (status.isSymbolicLink() || !validType) {
      return { success: false, availability: 'INVALID', error: '该会话的本地路径无效或不是受管普通路径。' }
    }
    return null
  } catch (cause) {
    const code = String((cause as { code?: unknown } | null)?.code || '')
    if (code === 'ENOENT' || code === 'ENOTDIR') {
      return { success: false, availability: 'MISSING', error: '该会话的本地文件已不存在。' }
    }
    return { success: false, availability: 'INVALID', error: '该会话的本地路径当前不可访问。' }
  }
}

async function safeBackendActionError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown }
    const detail = body.detail
    const message = typeof detail === 'string'
      ? detail
      : detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string'
        ? String((detail as { message: string }).message)
        : ''
    if (
      message
      && message.length <= 200
      && !/[A-Za-z]:[\\/]|\\\\/.test(message)
    ) return message
  } catch {
    // 使用稳定的安全回退文案。
  }
  return fallback
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
