import { resolve } from 'node:path'

export const NETCONSOLE_WINDOW_TITLE = 'NetConsole'

export interface DesktopIconPathContext {
  isPackaged: boolean
  appPath: string
  resourcesPath: string
}

export function resolveDesktopIconPath(context: DesktopIconPathContext): string {
  if (context.isPackaged) return resolve(context.resourcesPath, 'branding', 'netconsole.ico')
  return resolve(context.appPath, '..', '..', 'resources', 'branding', 'netconsole.ico')
}

export function resolveTrayIconPath(context: DesktopIconPathContext): string {
  return resolveDesktopIconPath(context)
}
