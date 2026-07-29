import type { WorkspaceWindowState } from './types'
import {
  canonicalizeWorkspaceRoute,
  sanitizeWorkspaceTitle,
} from './route-identity'
import type { Router } from 'vue-router'

export const WORKSPACE_SCHEMA_VERSION = 1
export const WORKSPACE_MAX_TABS = 40
const BROWSER_STORAGE_KEY = 'netconsole.workspace.v1'
const LEGACY_OPEN_PAGE_TABS_STORAGE_KEY = 'netconsole.web.open-page-tabs'

export interface RestoredWorkspace {
  windowId: string
  snapshot: WorkspaceWindowState | null
}

export async function loadWorkspace(
  router: Router,
): Promise<RestoredWorkspace> {
  clearLegacyWorkspacePersistence()
  if (window.netconsoleDesktop?.getWorkspaceWindowState) {
    try {
      const value = await window.netconsoleDesktop.getWorkspaceWindowState()
      return {
        windowId: sanitizeWindowId(value.windowId),
        snapshot: validateWorkspaceSnapshot(router, value.snapshot),
      }
    } catch {
      return { windowId: 'main', snapshot: null }
    }
  }
  return { windowId: 'browser-main', snapshot: null }
}

export async function saveWorkspace(snapshot: WorkspaceWindowState): Promise<void> {
  if (window.netconsoleDesktop?.saveWorkspaceWindowState) {
    await window.netconsoleDesktop.saveWorkspaceWindowState(snapshot)
  }
}

function clearLegacyWorkspacePersistence(): void {
  try {
    localStorage.removeItem(BROWSER_STORAGE_KEY)
  } catch {
    // 浏览器禁用存储时仍以当前 Renderer 内存状态启动。
  }
  try {
    sessionStorage.removeItem(LEGACY_OPEN_PAGE_TABS_STORAGE_KEY)
  } catch {
    // 同上；标签状态不是业务数据。
  }
}

export function validateWorkspaceSnapshot(
  router: Router,
  value: unknown,
): WorkspaceWindowState | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  if (
    record.schemaVersion !== WORKSPACE_SCHEMA_VERSION
    || typeof record.windowId !== 'string'
    || typeof record.activeTabId !== 'string'
    || !Array.isArray(record.tabs)
    || record.tabs.length === 0
    || record.tabs.length > WORKSPACE_MAX_TABS
  ) {
    return null
  }

  const tabs = record.tabs.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const tab = item as Record<string, unknown>
    if (
      typeof tab.id !== 'string'
      || typeof tab.instanceId !== 'string'
      || typeof tab.cacheKey !== 'string'
      || typeof tab.routeFullPath !== 'string'
      || typeof tab.pinned !== 'boolean'
      || typeof tab.openedAt !== 'number'
      || typeof tab.lastActivatedAt !== 'number'
    ) {
      return []
    }
    try {
      const canonical = canonicalizeWorkspaceRoute(router, tab.routeFullPath)
      return [{
        id: tab.id.slice(0, 100),
        instanceId: tab.instanceId.slice(0, 100),
        ...(canonical.routeName ? { routeName: canonical.routeName } : {}),
        routeFullPath: canonical.routeFullPath,
        title: sanitizeWorkspaceTitle(typeof tab.title === 'string' ? tab.title : canonical.title),
        identityKey: canonical.identityKey,
        cacheKey: tab.cacheKey.slice(0, 160),
        pinned: tab.pinned,
        openedAt: tab.openedAt,
        lastActivatedAt: tab.lastActivatedAt,
      }]
    } catch {
      return []
    }
  })
  if (tabs.length === 0) return null
  const activeTabId = tabs.some((tab) => tab.id === record.activeTabId)
    ? record.activeTabId
    : tabs[0].id
  return {
    schemaVersion: WORKSPACE_SCHEMA_VERSION,
    windowId: sanitizeWindowId(record.windowId),
    activeTabId,
    tabs,
  }
}

function sanitizeWindowId(value: string): string {
  return /^[A-Za-z0-9_-]{1,80}$/.test(value) ? value : 'main'
}
