import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { DesktopBootstrapStore } from '../src/main/bootstrap'

const roots: string[] = []

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

describe('desktop bootstrap', () => {
  it('atomically persists only data root and active site id', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-bootstrap-'))
    roots.push(root)
    const store = new DesktopBootstrapStore(root)

    store.save({ schema_version: 1, data_root: 'D:\\NetConsoleData', active_site_id: 'line-12' })

    expect(store.load()).toEqual({ schema_version: 1, data_root: 'D:\\NetConsoleData', active_site_id: 'line-12' })
    expect(readFileSync(store.path, 'utf8')).not.toMatch(/token|password/i)
  })

  it('returns a safe empty fallback for damaged bootstrap', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-bootstrap-'))
    roots.push(root)
    const store = new DesktopBootstrapStore(root)
    writeFileSync(store.path, '{broken', 'utf8')

    expect(store.load()).toEqual({})
  })

  it('backs up and rejects a persistent bootstrap that points to isolated Temp data', () => {
    const root = mkdtempSync(join(tmpdir(), 'netconsole-bootstrap-'))
    const isolated = mkdtempSync(join(tmpdir(), 'NetConsole-Codex-polluted-'))
    roots.push(root, isolated)
    mkdirSync(join(isolated, 'sites'), { recursive: true })
    const store = new DesktopBootstrapStore(root)
    store.save({ schema_version: 1, data_root: isolated, active_site_id: 'line-12' })

    const result = store.loadForRuntime({ storageMode: 'persistent', now: () => new Date('2026-07-20T12:00:00Z') })

    expect(result.value).toEqual({ active_site_id: 'line-12' })
    expect(result.rejectedEphemeralRoot).toBe(true)
    expect(result.backupPath && existsSync(result.backupPath)).toBe(true)
    expect(JSON.parse(readFileSync(store.path, 'utf8')).data_root).toBe(isolated)
  })
})
