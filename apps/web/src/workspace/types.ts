export type WorkspaceIdentityMode = 'singleton' | 'route' | 'resource' | 'multiple'

export interface WorkspaceRoutePolicy {
  enabled?: boolean
  identity?: WorkspaceIdentityMode
  resourceParams?: string[]
  resourceQuery?: string[]
  allowDuplicate?: boolean
  allowNewWindow?: boolean
  cache?: boolean
}

export interface WorkspaceTab {
  id: string
  instanceId: string
  routeName?: string
  routeFullPath: string
  title: string
  identityKey: string
  cacheKey: string
  pinned: boolean
  openedAt: number
  lastActivatedAt: number
}

export interface WorkspaceWindowState {
  schemaVersion: 1
  windowId: string
  activeTabId: string
  tabs: WorkspaceTab[]
}

export interface CanonicalWorkspaceRoute {
  routeName?: string
  routeFullPath: string
  title: string
  identityKey: string
  policy: Required<WorkspaceRoutePolicy>
}

declare module 'vue-router' {
  interface RouteMeta {
    workspace?: WorkspaceRoutePolicy
  }
}
