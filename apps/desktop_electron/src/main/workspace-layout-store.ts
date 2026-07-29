import {
  existsSync,
  rmSync,
} from 'node:fs'
import { isAbsolute, resolve } from 'node:path'

import type { WorkspaceWindowSnapshot } from '../shared/bridge'
import { validateWorkspaceWindowSnapshot } from '../shared/validation'

export const WORKSPACE_LAYOUT_SCHEMA_VERSION = 2
export const WORKSPACE_LAYOUT_MAX_WINDOWS = 8

export interface WorkspaceWindowBounds {
  x: number
  y: number
  width: number
  height: number
}

export interface PersistedMainWindow {
  windowId: string
  role: 'main'
  snapshot: WorkspaceWindowSnapshot | null
}

export interface PersistedAdditionalWorkspaceWindow {
  windowId: string
  role: 'workspace'
  bounds: WorkspaceWindowBounds
  maximized: boolean
  snapshot: WorkspaceWindowSnapshot | null
}

export type PersistedWorkspaceWindow =
  | PersistedMainWindow
  | PersistedAdditionalWorkspaceWindow

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
    this.windows.clear()
    this.removeLegacyPersistence()
    return []
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
    this.removeLegacyPersistence()
  }

  private removeLegacyPersistence(): void {
    if (!existsSync(this.path)) return
    try {
      rmSync(this.path, { force: true })
      this.logger('ELECTRON_WORKSPACE_LEGACY_STATE_CLEARED')
    } catch {
      this.logger('ELECTRON_WORKSPACE_LEGACY_STATE_CLEAR_FAILED')
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

function validateWindowRecord(
  value: unknown,
  legacyWindowState = false,
): PersistedWorkspaceWindow {
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
  ) {
    throw new TypeError('workspace window record fields are invalid')
  }
  const snapshot = record.snapshot == null
    ? null
    : validateWorkspaceWindowSnapshot(record.snapshot)
  if (snapshot && snapshot.windowId !== record.windowId) {
    throw new TypeError('workspace snapshot window id mismatch')
  }
  if (record.role === 'main') {
    if (!legacyWindowState && (record.bounds !== undefined || record.maximized !== undefined)) {
      throw new TypeError('main window state must not be persisted')
    }
    return {
      windowId: record.windowId,
      role: 'main',
      snapshot,
    }
  }
  if (typeof record.maximized !== 'boolean') {
    throw new TypeError('workspace window record fields are invalid')
  }
  return {
    windowId: record.windowId,
    role: 'workspace',
    bounds: validateBounds(record.bounds),
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
  const snapshot = value.snapshot
    ? {
        ...value.snapshot,
        tabs: value.snapshot.tabs.map((tab) => ({ ...tab })),
      }
    : null
  if (value.role === 'main') {
    return {
      windowId: value.windowId,
      role: 'main',
      snapshot,
    }
  }
  return {
    windowId: value.windowId,
    role: 'workspace',
    bounds: { ...value.bounds },
    maximized: value.maximized,
    snapshot,
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
