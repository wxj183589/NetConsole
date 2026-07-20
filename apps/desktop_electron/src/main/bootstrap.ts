import { copyFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, isAbsolute, resolve, sep } from 'node:path'

import type { DesktopStorageMode } from './development-data-root'

export interface DesktopBootstrap {
  schema_version: 1
  data_root: string
  active_site_id: string
}

export interface DesktopBootstrapLoadResult {
  value: Partial<DesktopBootstrap>
  rejectedEphemeralRoot: boolean
  backupPath?: string
}

export class DesktopBootstrapStore {
  readonly path: string

  constructor(userDataPath: string) {
    if (!isAbsolute(userDataPath)) throw new TypeError('userDataPath must be absolute')
    this.path = resolve(userDataPath, 'bootstrap.json')
  }

  load(): Partial<DesktopBootstrap> {
    try {
      const parsed = JSON.parse(readFileSync(this.path, 'utf8')) as Record<string, unknown>
      if (parsed.schema_version !== 1) return {}
      const dataRoot = safePath(parsed.data_root)
      const activeSiteId = safeSiteId(parsed.active_site_id)
      return {
        schema_version: 1,
        ...(dataRoot ? { data_root: dataRoot } : {}),
        ...(activeSiteId ? { active_site_id: activeSiteId } : {}),
      }
    } catch {
      return {}
    }
  }

  loadForRuntime(options: {
    storageMode: DesktopStorageMode
    systemTempRoot?: string
    now?: () => Date
  }): DesktopBootstrapLoadResult {
    const value = this.load()
    if (options.storageMode === 'isolated_test' || !value.data_root) {
      return { value, rejectedEphemeralRoot: false }
    }
    if (!isRejectedPersistentRoot(value.data_root, options.systemTempRoot ?? tmpdir())) {
      return { value, rejectedEphemeralRoot: false }
    }
    const timestamp = (options.now?.() ?? new Date()).toISOString().replace(/[:.]/g, '-')
    const backupPath = `${this.path}.invalid-${timestamp}`
    if (existsSync(this.path)) copyFileSync(this.path, backupPath)
    return {
      value: value.active_site_id ? { active_site_id: value.active_site_id } : {},
      rejectedEphemeralRoot: true,
      ...(existsSync(backupPath) ? { backupPath } : {}),
    }
  }

  save(value: DesktopBootstrap): void {
    const dataRoot = safePath(value.data_root)
    const activeSiteId = safeSiteId(value.active_site_id)
    if (!dataRoot || !activeSiteId) throw new TypeError('bootstrap value is invalid')
    mkdirSync(dirname(this.path), { recursive: true })
    const temporary = `${this.path}.${process.pid}.tmp`
    try {
      writeFileSync(temporary, `${JSON.stringify({ schema_version: 1, data_root: dataRoot, active_site_id: activeSiteId }, null, 2)}\n`, { encoding: 'utf8', flag: 'w' })
      renameSync(temporary, this.path)
    } finally {
      rmSync(temporary, { force: true })
    }
  }
}

function isRejectedPersistentRoot(value: string, systemTempRoot: string): boolean {
  const candidate = resolve(value)
  const temporary = resolve(systemTempRoot)
  if (candidate === temporary || candidate.startsWith(`${temporary}${sep}`)) return true
  if (candidate.split(/[\\/]/).some((part) => part.startsWith('NetConsole-Codex-'))) return true
  return !existsSync(resolve(candidate, 'data', 'sites'))
}

function safePath(value: unknown): string | undefined {
  if (typeof value !== 'string' || !isAbsolute(value) || /[\u0000-\u001f]/.test(value)) return undefined
  return resolve(value)
}

function safeSiteId(value: unknown): string | undefined {
  if (typeof value !== 'string' || !/^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$/.test(value)) return undefined
  return value
}
