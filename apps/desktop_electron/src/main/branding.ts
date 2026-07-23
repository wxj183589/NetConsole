import { resolve } from 'node:path'

export const NETCONSOLE_WINDOW_TITLE = 'NetConsole v1.4.1 by wxj'
export const NETCONSOLE_TASK_WINDOW_TITLE = `${NETCONSOLE_WINDOW_TITLE} - 任务中心`

export interface DesktopIconPathContext {
  isPackaged: boolean
  appPath: string
  resourcesPath: string
}

export function resolveDesktopIconPath(context: DesktopIconPathContext): string {
  if (context.isPackaged) return resolve(context.resourcesPath, 'branding', 'netconsole.ico')
  return resolve(context.appPath, '..', '..', 'resources', 'branding', 'netconsole.ico')
}
