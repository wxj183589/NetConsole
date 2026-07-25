import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import {
  canonicalizeWorkspaceRoute,
  sanitizeWorkspaceTitle,
} from './route-identity'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: {}, meta: { title: 'Dashboard' } },
      { path: '/devices/:deviceId', name: 'device-detail', component: {}, meta: {
        title: '设备详情',
        workspace: { identity: 'resource', resourceParams: ['deviceId'] },
      } },
      { path: '/mesh', name: 'mesh', component: {}, meta: {
        title: 'MESH',
        workspace: { identity: 'resource', resourceQuery: ['session_id'] },
      } },
      { path: '/desktop/tasks', component: {}, meta: { workspace: { enabled: false } } },
    ],
  })
}

describe('workspace route identity', () => {
  it('normalizes query ordering and strips internal or sensitive fields', () => {
    const router = createTestRouter()
    const left = canonicalizeWorkspaceRoute(
      router,
      '/mesh?z=2&session_id=session-1&token=secret&a=1&workspace_window=1',
    )
    const right = canonicalizeWorkspaceRoute(
      router,
      '/mesh?a=1&session_id=session-1&z=2',
    )

    expect(left.routeFullPath).toBe('/mesh?a=1&session_id=session-1&z=2')
    expect(left.identityKey).toBe(right.identityKey)
    expect(left.routeFullPath).not.toContain('secret')
  })

  it('separates resource routes and rejects non-workspace targets', () => {
    const router = createTestRouter()
    expect(canonicalizeWorkspaceRoute(router, '/devices/device-a').identityKey)
      .not.toBe(canonicalizeWorkspaceRoute(router, '/devices/device-b').identityKey)
    expect(() => canonicalizeWorkspaceRoute(router, 'https://example.com')).toThrow()
    expect(() => canonicalizeWorkspaceRoute(router, '/desktop/tasks')).toThrow()
    expect(() => canonicalizeWorkspaceRoute(router, '/mesh?source=C:%5Cprivate%5Craw.log')).not.toThrow()
    expect(canonicalizeWorkspaceRoute(router, '/mesh?source=C:%5Cprivate%5Craw.log').routeFullPath)
      .toBe('/mesh')
  })

  it('sanitizes titles without exposing paths or control characters', () => {
    expect(sanitizeWorkspaceTitle('  MESH\u0000 会话  ')).toBe('MESH 会话')
    expect(sanitizeWorkspaceTitle('C:\\private\\raw.log')).toBe('NetConsole')
    expect(sanitizeWorkspaceTitle('x'.repeat(120))).toHaveLength(80)
  })

  it('does not cache or duplicate routes unless their policy opts in', () => {
    const router = createTestRouter()
    const dashboard = canonicalizeWorkspaceRoute(router, '/')
    const mesh = canonicalizeWorkspaceRoute(router, '/mesh?session_id=session-1')

    expect(dashboard.policy.cache).toBe(false)
    expect(dashboard.policy.allowDuplicate).toBe(false)
    expect(mesh.policy.cache).toBe(false)
    expect(mesh.policy.allowDuplicate).toBe(false)
  })
})
