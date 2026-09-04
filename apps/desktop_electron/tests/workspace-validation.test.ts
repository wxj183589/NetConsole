import { describe, expect, it } from 'vitest'

import {
  validateWorkspaceRoute,
  validateWorkspaceTitle,
  validateWorkspaceWindowOpenRequest,
  validateWorkspaceWindowSnapshot,
  validateRendererReadyReport,
} from '../src/shared/validation'

function snapshot(routeFullPath = '/rail-transit/mesh-analysis?session_id=session-1') {
  return {
    schemaVersion: 1,
    windowId: 'main',
    activeTabId: 'tab-1',
    tabs: [{
      id: 'tab-1',
      instanceId: 'instance-1',
      routeName: 'mesh-analysis',
      routeFullPath,
      title: 'MESH：列车07-MR-CT',
      identityKey: 'resource:mesh-analysis:session-1',
      cacheKey: 'mesh-analysis:instance-1',
      pinned: false,
      openedAt: 1,
      lastActivatedAt: 2,
    }],
  }
}

describe('workspace validation', () => {
  it('accepts and canonicalizes only known internal routes', () => {
    expect(validateWorkspaceRoute('/devices/device-1?b=2&a=1')).toBe('/devices/device-1?a=1&b=2')
    expect(validateWorkspaceRoute('/rail-transit/mesh-analysis?session_id=session-1')).toContain('session_id=session-1')
    for (const value of [
      'https://example.com/',
      'file:///C:/private/raw.log',
      'javascript:alert(1)',
      'data:text/html,test',
      'blob:http://127.0.0.1/id',
      '//example.com/path',
      '/devices/../settings',
      '/devices/%2e%2e/settings',
      '/unknown',
    ]) {
      expect(() => validateWorkspaceRoute(value)).toThrow()
    }
  })

  it('rejects sensitive query data, local paths, unknown request fields, and unsafe titles', () => {
    expect(() => validateWorkspaceRoute('/tasks?token=secret')).toThrow()
    expect(() => validateWorkspaceRoute('/tasks?confirm_token=secret')).toThrow()
    expect(() => validateWorkspaceRoute('/tasks?source=C:%5Cprivate%5Craw.log')).toThrow()
    expect(() => validateWorkspaceWindowOpenRequest({
      routeFullPath: '/',
      title: 'Dashboard',
      webPreferences: { nodeIntegration: true },
    })).toThrow()
    expect(() => validateWorkspaceTitle('C:\\private\\raw.log')).toThrow()
    expect(validateWorkspaceTitle('设备：WX3540X-AC1')).toBe('设备：WX3540X-AC1')
  })

  it('strictly validates snapshots and tab limits', () => {
    expect(validateWorkspaceWindowSnapshot(snapshot()).tabs).toHaveLength(1)
    expect(() => validateWorkspaceWindowSnapshot(snapshot('/tasks?password=secret'))).toThrow()
    expect(() => validateWorkspaceWindowSnapshot({ ...snapshot(), token: 'secret' })).toThrow()
    expect(() => validateWorkspaceWindowSnapshot({
      ...snapshot(),
      tabs: Array.from({ length: 41 }, (_, index) => ({
        ...snapshot().tabs[0],
        id: `tab-${index}`,
      })),
    })).toThrow()
  })

  it('accepts the workspace renderer lifecycle surface', () => {
    expect(validateRendererReadyReport({
      healthOk: true,
      phase: 'mounted',
      surface: 'workspace-window',
      siteId: 'hz10',
    })).toEqual({
      healthOk: true,
      phase: 'mounted',
      surface: 'workspace-window',
      siteId: 'hz10',
    })
    expect(() => validateRendererReadyReport({
      healthOk: true,
      phase: 'interactive',
      siteId: '杭州10号线',
    })).toThrow()
  })
})
