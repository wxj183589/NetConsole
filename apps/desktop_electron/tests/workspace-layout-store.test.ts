import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  WorkspaceLayoutStore,
  normalizeWorkspaceBounds,
} from '../src/main/workspace-layout-store'

const roots: string[] = []

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

describe('WorkspaceLayoutStore', () => {
  it('keeps layout records in process memory only', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-layout-'))
    roots.push(root)
    const store = new WorkspaceLayoutStore(root)
    expect(store.load()).toEqual([])
    store.upsert({
      windowId: 'main',
      role: 'main',
      snapshot: null,
    })
    store.upsert({
      windowId: 'workspace-1',
      role: 'workspace',
      bounds: { x: 10, y: 20, width: 1_200, height: 800 },
      maximized: false,
      snapshot: null,
    })
    store.flush()

    expect(store.list()).toEqual([
      { windowId: 'main', role: 'main', snapshot: null },
      {
        windowId: 'workspace-1',
        role: 'workspace',
        bounds: { x: 10, y: 20, width: 1_200, height: 800 },
        maximized: false,
        snapshot: null,
      },
    ])
    expect(existsSync(store.path)).toBe(false)
    expect(new WorkspaceLayoutStore(root).load()).toEqual([])
  })

  it('clears the legacy workspace file without touching unrelated preferences', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-layout-'))
    roots.push(root)
    const logger = vi.fn()
    const store = new WorkspaceLayoutStore(root, logger)
    const preferencesPath = join(root, 'ui-preferences.json')
    writeFileSync(preferencesPath, '{"theme":"dark"}', 'utf8')
    writeFileSync(store.path, JSON.stringify({
      schemaVersion: 1,
      windows: [{
        windowId: 'main',
        role: 'main',
        bounds: { x: -4_000, y: 500, width: 900, height: 600 },
        maximized: true,
        snapshot: {
          activeTabId: 'tasks',
          tabs: [{ routeFullPath: '/tasks' }],
        },
      }],
    }), 'utf8')

    expect(store.load()).toEqual([])
    expect(existsSync(store.path)).toBe(false)
    expect(existsSync(preferencesPath)).toBe(true)
    expect(logger).toHaveBeenCalledWith('ELECTRON_WORKSPACE_LEGACY_STATE_CLEARED')
  })

  it('moves off-screen windows back into the primary work area', () => {
    expect(normalizeWorkspaceBounds(
      { x: 50_000, y: 50_000, width: 1_200, height: 800 },
      [{ x: 0, y: 0, width: 1_920, height: 1_080 }],
    )).toEqual({ x: 360, y: 140, width: 1_200, height: 800 })
  })
})
