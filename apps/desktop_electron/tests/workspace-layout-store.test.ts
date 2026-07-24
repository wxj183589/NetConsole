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
      bounds: { x: 10, y: 20, width: 1_200, height: 800 },
      maximized: false,
      snapshot: null,
    })
    store.flush()

    expect(JSON.parse(readFileSync(store.path, 'utf8')).schemaVersion).toBe(1)
    expect(new WorkspaceLayoutStore(root).load()).toHaveLength(1)
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
