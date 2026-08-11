import type { Router, RouteLocationResolved } from 'vue-router'

import type {
  CanonicalWorkspaceRoute,
  WorkspaceRoutePolicy,
} from './types'

export const WORKSPACE_DEFAULT_ROUTE = '/'
export const WORKSPACE_MAX_ROUTE_LENGTH = 2_048
export const WORKSPACE_MAX_TITLE_LENGTH = 80

const INTERNAL_QUERY_KEYS = new Set([
  'task_window',
  'workspace_window',
  'workspace_window_id',
  'workspace_restore',
])
const SENSITIVE_QUERY_KEY_RE = /(?:token|password|secret|authorization|community|passphrase|confirm_token)/i
const CONTROL_CHARACTER_RE = /[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/
const LOCAL_PATH_RE = /^(?:[A-Za-z]:[\\/]|\\\\|file:)/i

const DEFAULT_POLICY: Required<WorkspaceRoutePolicy> = {
  enabled: true,
  identity: 'singleton',
  resourceParams: [],
  resourceQuery: [],
  allowDuplicate: false,
  allowNewWindow: true,
  cache: false,
}

export function canonicalizeWorkspaceRoute(
  router: Router,
  rawRoute: string,
): CanonicalWorkspaceRoute {
  const safeInput = sanitizeWorkspaceRouteInput(rawRoute)
  const resolved = router.resolve(safeInput)
  const policy = resolveWorkspacePolicy(resolved)
  if (!policy.enabled || resolved.matched.length === 0) {
    throw new TypeError('该页面不能加入工作区')
  }

  const routeName = typeof resolved.name === 'string' ? resolved.name : undefined
  const query = canonicalQuery(resolved)
  const routeFullPath = `${resolved.path}${query ? `?${query}` : ''}`
  if (routeFullPath.length > WORKSPACE_MAX_ROUTE_LENGTH) {
    throw new TypeError('工作区路由过长')
  }

  return {
    ...(routeName ? { routeName } : {}),
    routeFullPath,
    title: sanitizeWorkspaceTitle(String(resolved.meta.title || 'NetConsole')),
    identityKey: buildIdentityKey(resolved, routeName, routeFullPath, query, policy),
    policy,
  }
}

export function sanitizeWorkspaceTitle(value: string): string {
  const cleaned = value
    .replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!cleaned || LOCAL_PATH_RE.test(cleaned) || SENSITIVE_QUERY_KEY_RE.test(cleaned)) {
    return 'NetConsole'
  }
  return cleaned.slice(0, WORKSPACE_MAX_TITLE_LENGTH)
}

export function isSensitiveWorkspaceQueryKey(value: string): boolean {
  return SENSITIVE_QUERY_KEY_RE.test(value)
}

function sanitizeWorkspaceRouteInput(value: string): string {
  const input = String(value || '').trim()
  if (
    !input.startsWith('/')
    || input.startsWith('//')
    || input.length > WORKSPACE_MAX_ROUTE_LENGTH
    || CONTROL_CHARACTER_RE.test(input)
    || input.includes('\\')
  ) {
    throw new TypeError('工作区仅接受安全的应用内部路由')
  }
  let decoded = ''
  try {
    decoded = decodeURIComponent(input)
  } catch {
    throw new TypeError('工作区路由编码无效')
  }
  const pathname = decoded.split(/[?#]/, 1)[0]
  if (
    pathname.split('/').some((part) => part === '.' || part === '..')
    || /^\/(?:desktop\/tasks|api|ws)(?:\/|$)/.test(pathname)
    || LOCAL_PATH_RE.test(pathname)
  ) {
    throw new TypeError('工作区路由不在允许范围内')
  }
  return input
}

function resolveWorkspacePolicy(route: RouteLocationResolved): Required<WorkspaceRoutePolicy> {
  const configured = route.meta.workspace || {}
  return {
    ...DEFAULT_POLICY,
    ...configured,
    resourceParams: [...(configured.resourceParams || [])],
    resourceQuery: [...(configured.resourceQuery || [])],
  }
}

function canonicalQuery(route: RouteLocationResolved): string {
  const entries: Array<[string, string]> = []
  for (const key of Object.keys(route.query).sort()) {
    if (INTERNAL_QUERY_KEYS.has(key) || key.startsWith('__nc_') || isSensitiveWorkspaceQueryKey(key)) {
      continue
    }
    const rawValues = Array.isArray(route.query[key]) ? route.query[key] : [route.query[key]]
    for (const rawValue of rawValues) {
      if (rawValue == null) continue
      const value = String(rawValue)
      if (
        value.length > 1_000
        || CONTROL_CHARACTER_RE.test(value)
        || LOCAL_PATH_RE.test(value.trim())
      ) {
        continue
      }
      entries.push([key, value])
    }
  }
  const query = new URLSearchParams()
  for (const [key, value] of entries) query.append(key, value)
  return query.toString()
}

function buildIdentityKey(
  route: RouteLocationResolved,
  routeName: string | undefined,
  routeFullPath: string,
  canonicalQueryString: string,
  policy: Required<WorkspaceRoutePolicy>,
): string {
  const routeKey = routeName || route.path
  if (policy.identity === 'route') return `route:${routeFullPath}`
  if (policy.identity === 'multiple') return `multiple:${routeKey}`
  if (policy.identity === 'resource') {
    const canonicalQueryValues = new URLSearchParams(canonicalQueryString)
    const resources = [
      ...policy.resourceParams.map((key) => [key, normalizeParam(route.params[key])] as const),
      ...policy.resourceQuery.map((key) => [key, canonicalQueryValues.getAll(key).join(',')] as const),
    ]
    const encoded = resources
      .filter(([, value]) => Boolean(value))
      .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
      .join('&')
    return `resource:${routeKey}:${encoded || 'default'}`
  }
  return `singleton:${routeKey}`
}

function normalizeParam(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(',')
  return value == null ? '' : String(value)
}
