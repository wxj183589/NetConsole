import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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
  it('writes an atomic validated layout and safely loads it', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-layout-'))
    roots.push(root)
    const store = new WorkspaceLayoutStore(root)
    store.load()
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

    const persisted = JSON.parse(readFileSync(store.path, 'utf8'))
    expect(persisted.schemaVersion).toBe(2)
    expect(persisted.windows).toEqual([
      { windowId: 'main', role: 'main', snapshot: null },
      {
        windowId: 'workspace-1',
        role: 'workspace',
        bounds: { x: 10, y: 20, width: 1_200, height: 800 },
        maximized: false,
        snapshot: null,
      },
    ])
    expect(new WorkspaceLayoutStore(root).load()).toHaveLength(2)
  })

  it('discards legacy main window bounds and state while preserving its snapshot', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-layout-'))
    roots.push(root)
    const store = new WorkspaceLayoutStore(root)
    writeFileSync(store.path, JSON.stringify({
      schemaVersion: 1,
      windows: [{
        windowId: 'main',
        role: 'main',
        bounds: { x: -4_000, y: 500, width: 900, height: 600 },
        maximized: false,
        snapshot: null,
      }],
    }), 'utf8')

    expect(store.load()).toEqual([{
      windowId: 'main',
      role: 'main',
      snapshot: null,
    }])
    store.flush()
    const persisted = JSON.parse(readFileSync(store.path, 'utf8'))
    expect(persisted.schemaVersion).toBe(2)
    expect(persisted.windows[0]).not.toHaveProperty('bounds')
    expect(persisted.windows[0]).not.toHaveProperty('maximized')
  })

  it('falls back from corrupt data without preventing startup', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-workspace-layout-'))
    roots.push(root)
    const logger = vi.fn()
    const store = new WorkspaceLayoutStore(root, logger)
    writeFileSync(store.path, '{broken', 'utf8')

    expect(store.load()).toEqual([])
    expect(logger).toHaveBeenCalledWith('ELECTRON_WORKSPACE_LAYOUT_RECOVERY_FALLBACK')
  })

  it('moves off-screen windows back into the primary work area', () => {
    expect(normalizeWorkspaceBounds(
      { x: 50_000, y: 50_000, width: 1_200, height: 800 },
      [{ x: 0, y: 0, width: 1_920, height: 1_080 }],
    )).toEqual({ x: 360, y: 140, width: 1_200, height: 800 })
  })
})
