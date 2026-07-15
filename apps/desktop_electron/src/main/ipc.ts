import type { AppInfo, BackendStatus, DesktopRuntimeConfig } from '../shared/bridge'
import { DESKTOP_HANDLED_CHANNELS, DESKTOP_IPC } from '../shared/bridge'
import {
  validateChooseSavePathOptions,
  validateRendererReadyReport,
  validateSelectFileOptions,
} from '../shared/validation'
import type { BackendRuntimeInfo } from './backend-manager'
import { GrantedPathRegistry } from './path-access'

interface IpcEventLike {
  sender: unknown
  senderFrame?: { url: string } | null
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
}

interface ShellLike {
  openPath(path: string): Promise<string>
  showItemInFolder(path: string): void
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
  appInfo: AppInfo
  backend: BackendLike
  pathRegistry?: GrantedPathRegistry
  isTrustedSender: (event: IpcEventLike) => boolean
  onRendererReady?: (healthOk: boolean) => void
}

export function registerDesktopIpc(dependencies: DesktopIpcDependencies): void {
  const registry = dependencies.pathRegistry ?? new GrantedPathRegistry()
  for (const channel of DESKTOP_HANDLED_CHANNELS) dependencies.ipcMain.removeHandler(channel)

  const trusted = <T>(handler: (value?: unknown) => T | Promise<T>) => (
    event: IpcEventLike,
    value?: unknown,
  ): T | Promise<T> => {
    if (!dependencies.isTrustedSender(event)) throw new Error('拒绝来自未知渲染进程的桌面请求')
    return handler(value)
  }

  dependencies.ipcMain.handle(
    DESKTOP_IPC.getAppInfo,
    trusted(() => ({ ...dependencies.appInfo })),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getBackendStatus,
    trusted(() => dependencies.backend.getStatus()),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.getRuntimeConfig,
    trusted((): DesktopRuntimeConfig => {
      const runtime = dependencies.backend.getRuntimeInfo()
      return { apiBaseUrl: runtime.baseUrl, apiToken: runtime.apiToken }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.selectFile,
    trusted(async (value) => {
      const options = validateSelectFileOptions(value)
      const result = await dependencies.dialog.showOpenDialog(dependencies.window, {
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
    trusted(async () => {
      const result = await dependencies.dialog.showOpenDialog(dependencies.window, {
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
    DESKTOP_IPC.chooseSavePath,
    trusted(async (value) => {
      const options = validateChooseSavePathOptions(value)
      const result = await dependencies.dialog.showSaveDialog(dependencies.window, {
        defaultPath: options.suggestedName,
        ...(options.filters ? { filters: options.filters } : {}),
      })
      return {
        cancelled: result.canceled || !result.filePath,
        ...(!result.canceled && result.filePath ? { path: registry.grant(result.filePath, 'save') } : {}),
      }
    }),
  )
  dependencies.ipcMain.handle(
    DESKTOP_IPC.openPath,
    trusted(async (value) => {
      try {
        const path = registry.requireOpenable(value)
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
        dependencies.shell.showItemInFolder(registry.requireGranted(value))
        return { success: true }
      } catch (cause) {
        return { success: false, error: safeActionError(cause) }
      }
    }),
  )
  dependencies.ipcMain.on(DESKTOP_IPC.rendererReady, (event, value) => {
    if (!dependencies.isTrustedSender(event)) return
    const report = validateRendererReadyReport(value)
    dependencies.onRendererReady?.(report.healthOk)
  })
}

function safeActionError(cause: unknown): string {
  if (cause instanceof Error && /未由当前桌面会话授权|路径必须是绝对路径|桌面桥接只允许/.test(cause.message)) {
    return cause.message
  }
  return '桌面操作失败'
}
