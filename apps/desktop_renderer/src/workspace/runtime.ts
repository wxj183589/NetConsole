import type { NativeActionResult } from '../../../desktop_electron/src/shared/bridge'

import { sanitizeWorkspaceTitle } from './route-identity'

export const WORKSPACE_TITLE_EVENT = 'netconsole:workspace-title'

export async function openWorkspaceWindow(
  routeFullPath: string,
  title: string,
): Promise<NativeActionResult> {
  if (window.netconsoleDesktop?.openWorkspaceWindow) {
    return window.netconsoleDesktop.openWorkspaceWindow({
      routeFullPath,
      title: sanitizeWorkspaceTitle(title),
    })
  }
  const opened = window.open(routeFullPath, '_blank', 'noopener,noreferrer')
  return opened
    ? { success: true }
    : { success: false, error: '浏览器阻止了新窗口，请允许本站打开弹窗。' }
}

export function updateDesktopWorkspaceTitle(title: string): void {
  window.netconsoleDesktop?.setWorkspaceWindowTitle?.(sanitizeWorkspaceTitle(title))
}

export function requestWorkspaceTabTitle(title: string): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_TITLE_EVENT, {
    detail: sanitizeWorkspaceTitle(title),
  }))
}
