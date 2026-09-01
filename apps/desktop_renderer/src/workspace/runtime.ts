import type { NativeActionResult } from '../../../desktop_electron/src/shared/bridge'

import { sanitizeWorkspaceTitle } from './route-identity'

export const WORKSPACE_TITLE_EVENT = 'netconsole:workspace-title'
const MAX_NATIVE_WORKSPACE_TITLE_LENGTH = 80

export interface WorkspaceWindowTitleContext {
  dataRoot: string
  runtimeMode: string
}

let titleContext: WorkspaceWindowTitleContext = { dataRoot: '', runtimeMode: '' }
let currentPageTitle = 'NetConsole'

export async function openWorkspaceWindow(
  routeFullPath: string,
  title: string,
): Promise<NativeActionResult> {
  if (window.netconsoleDesktop?.openWorkspaceWindow) {
    return window.netconsoleDesktop.openWorkspaceWindow({
      routeFullPath,
      title: composeWorkspaceWindowTitle(title),
    })
  }
  const opened = window.open(routeFullPath, '_blank', 'noopener,noreferrer')
  return opened
    ? { success: true }
    : { success: false, error: '浏览器阻止了新窗口，请允许本站打开弹窗。' }
}

export function updateDesktopWorkspaceTitle(title: string): void {
  currentPageTitle = sanitizeWorkspaceTitle(title)
  window.netconsoleDesktop?.setWorkspaceWindowTitle?.(composeWorkspaceWindowTitle(currentPageTitle))
}

export function setWorkspaceWindowTitleContext(dataRoot: string, runtimeMode: string): void {
  titleContext = {
    dataRoot: String(dataRoot || '').trim(),
    runtimeMode: String(runtimeMode || '').trim(),
  }
  updateDesktopWorkspaceTitle(currentPageTitle)
}

export function composeWorkspaceWindowTitle(
  pageTitle: string,
  context: WorkspaceWindowTitleContext = titleContext,
): string {
  const base = sanitizeWorkspaceTitle(pageTitle) || 'NetConsole'
  const brandedPageTitle = base === 'Dashboard'
    ? 'NetConsole'
    : base.endsWith(' - NetConsole') ? base : `${base} - NetConsole`
  const dataRoot = String(context.dataRoot || '').trim()
  const runtimeMode = String(context.runtimeMode || '').trim()
  if (!dataRoot || !runtimeMode) return brandedPageTitle
  const contextSuffix = ` | 当前数据根：${dataRoot} | 运行模式：${runtimeMode}`
  return `${brandedPageTitle}${contextSuffix}`.slice(0, MAX_NATIVE_WORKSPACE_TITLE_LENGTH)
}

export function requestWorkspaceTabTitle(title: string): void {
  window.dispatchEvent(new CustomEvent(WORKSPACE_TITLE_EVENT, {
    detail: sanitizeWorkspaceTitle(title),
  }))
}
