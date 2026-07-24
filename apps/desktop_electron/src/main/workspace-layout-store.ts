import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { dirname, isAbsolute, resolve } from 'node:path'

import type { WorkspaceWindowSnapshot } from '../shared/bridge'
import { validateWorkspaceWindowSnapshot } from '../shared/validation'

export const WORKSPACE_LAYOUT_SCHEMA_VERSION = 1
export const WORKSPACE_LAYOUT_MAX_WINDOWS = 8

export interface WorkspaceWindowBounds {
  x: number
  y: number
  width: number
  height: number
}

export interface PersistedWorkspaceWindow {
  windowId: string
  role: 'main' | 'workspace'
  bounds: WorkspaceWindowBounds
  maximized: boolean
  snapshot: WorkspaceWindowSnapshot | null
}

interface PersistedWorkspaceLayout {
  schemaVersion: typeof WORKSPACE_LAYOUT_SCHEMA_VERSION
  windows: PersistedWorkspaceWindow[]
}

export class WorkspaceLayoutStore {
  readonly path: string
  private windows = new Map<string, PersistedWorkspaceWindow>()
  private loaded = false

  constructor(
    userDataPath: string,
    private readonly logger: (event: string) => void = () => undefined,
  ) {
    if (!isAbsolute(userDataPath)) throw new TypeError('userDataPath must be absolute')
    this.path = resolve(userDataPath, 'workspace-layout.json')
  }

  load(): PersistedWorkspaceWindow[] {
    if (this.loaded) return this.list()
    this.loaded = true
    try {
      const parsed = JSON.parse(readFileSync(this.path, 'utf8')) as Record<string, unknown>
      if (parsed.schemaVersion !== WORKSPACE_LAYOUT_SCHEMA_VERSION || !Array.isArray(parsed.windows)) {
        throw new TypeError('workspace layout schema is invalid')
      }
      const values = parsed.windows
        .slice(0, WORKSPACE_LAYOUT_MAX_WINDOWS)
        .map(validateWindowRecord)
      this.windows = new Map(values.map((item) => [item.windowId, item]))
    } catch {
      if (existsSync(this.path)) this.logger('ELECTRON_WORKSPACE_LAYOUT_RECOVERY_FALLBACK')
      this.windows.clear()
    }
    return this.list()
  }

  list(): PersistedWorkspaceWindow[] {
    return [...this.windows.values()].map(cloneRecord)
  }

  get(windowId: string): PersistedWorkspaceWindow | undefined {
    const value = this.windows.get(windowId)
    return value ? cloneRecord(value) : undefined
  }

  upsert(value: PersistedWorkspaceWindow): void {
    if (!this.loaded) this.load()
    const validated = validateWindowRecord(value)
    if (
      !this.windows.has(validated.windowId)
      && this.windows.size >= WORKSPACE_LAYOUT_MAX_WINDOWS
    ) {
      throw new TypeError('workspace window limit exceeded')
    }
    this.windows.set(validated.windowId, validated)
  }

  remove(windowId: string): void {
    if (!this.loaded) this.load()
    this.windows.delete(windowId)
  }

  flush(): void {
    if (!this.loaded) return
    const payload: PersistedWorkspaceLayout = {
      schemaVersion: WORKSPACE_LAYOUT_SCHEMA_VERSION,
      windows: this.list().slice(0, WORKSPACE_LAYOUT_MAX_WINDOWS),
    }
    mkdirSync(dirname(this.path), { recursive: true })
    const temporary = `${this.path}.${process.pid}.tmp`
    try {
      writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, {
        encoding: 'utf8',
        flag: 'w',
      })
      renameSync(temporary, this.path)
    } finally {
      rmSync(temporary, { force: true })
    }
  }
}

export function normalizeWorkspaceBounds(
  value: WorkspaceWindowBounds,
  workAreas: readonly WorkspaceWindowBounds[],
): WorkspaceWindowBounds {
  const width = clampInteger(value.width, 720, 3_840, 1_360)
  const height = clampInteger(value.height, 520, 2_160, 860)
  const candidate = {
    x: clampInteger(value.x, -100_000, 100_000, 80),
    y: clampInteger(value.y, -100_000, 100_000, 80),
    width,
    height,
  }
  const visible = workAreas.some((area) => intersectionArea(candidate, area) >= 12_000)
  if (visible) return candidate
  const primary = workAreas[0] || { x: 0, y: 0, width: 1_920, height: 1_080 }
  return {
    x: primary.x + Math.max(0, Math.round((primary.width - width) / 2)),
    y: primary.y + Math.max(0, Math.round((primary.height - height) / 2)),
    width: Math.min(width, primary.width),
    height: Math.min(height, primary.height),
  }
}

function validateWindowRecord(value: unknown): PersistedWorkspaceWindow {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('workspace window record is invalid')
  }
  const record = value as Record<string, unknown>
  const keys = Object.keys(record)
  if (keys.some((key) => !['windowId', 'role', 'bounds', 'maximized', 'snapshot'].includes(key))) {
    throw new TypeError('workspace window record has unknown fields')
  }
  if (
    typeof record.windowId !== 'string'
    || !/^[A-Za-z0-9_-]{1,80}$/.test(record.windowId)
    || !['main', 'workspace'].includes(String(record.role))
    || typeof record.maximized !== 'boolean'
  ) {
    throw new TypeError('workspace window record fields are invalid')
  }
  const bounds = validateBounds(record.bounds)
  const snapshot = record.snapshot == null
    ? null
    : validateWorkspaceWindowSnapshot(record.snapshot)
  if (snapshot && snapshot.windowId !== record.windowId) {
    throw new TypeError('workspace snapshot window id mismatch')
  }
  return {
    windowId: record.windowId,
    role: record.role as PersistedWorkspaceWindow['role'],
    bounds,
    maximized: record.maximized,
    snapshot,
  }
}

function validateBounds(value: unknown): WorkspaceWindowBounds {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('workspace window bounds are invalid')
  }
  const record = value as Record<string, unknown>
  if (
    Object.keys(record).some((key) => !['x', 'y', 'width', 'height'].includes(key))
    || !['x', 'y', 'width', 'height'].every((key) => (
      typeof record[key] === 'number' && Number.isInteger(record[key])
    ))
  ) {
    throw new TypeError('workspace window bounds are invalid')
  }
  return {
    x: record.x as number,
    y: record.y as number,
    width: record.width as number,
    height: record.height as number,
  }
}

function cloneRecord(value: PersistedWorkspaceWindow): PersistedWorkspaceWindow {
  return {
    ...value,
    bounds: { ...value.bounds },
    snapshot: value.snapshot
      ? {
          ...value.snapshot,
          tabs: value.snapshot.tabs.map((tab) => ({ ...tab })),
        }
      : null,
  }
}

function clampInteger(value: number, minimum: number, maximum: number, fallback: number): number {
  return Number.isInteger(value) ? Math.min(maximum, Math.max(minimum, value)) : fallback
}

function intersectionArea(left: WorkspaceWindowBounds, right: WorkspaceWindowBounds): number {
  const width = Math.max(0, Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x))
  const height = Math.max(0, Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y))
  return width * height
}
