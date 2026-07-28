import { randomUUID } from 'node:crypto'
import { lstat } from 'node:fs/promises'
import { basename, extname, isAbsolute, resolve } from 'node:path'

import { isOpenableArtifactFileName, validateArtifactFileName, validateBridgePath } from '../shared/validation'

const SAFE_OPEN_EXTENSIONS = new Set([
  '.csv',
  '.json',
  '.log',
  '.md',
  '.pdf',
  '.txt',
  '.xls',
  '.xlsx',
  '.zip',
])

type GrantedPathKind = 'file' | 'directory' | 'save'

interface GrantedPath {
  path: string
  kind: GrantedPathKind
  saveTarget?: SaveTargetSnapshot
}

export type SaveTargetSnapshot =
  | { kind: 'missing' }
  | {
      kind: 'file'
      size: number
      mtimeMs: number
      ctimeMs: number
      birthtimeMs: number
      dev: number
      ino: number
    }
  | { kind: 'other' }

export interface SavePathAuthorization {
  path: string
  saveTarget?: SaveTargetSnapshot
}

type CapabilityPurpose = 'artifact-download' | 'selected-file'
type CapabilityAction = 'open' | 'reveal'

interface CapabilityGrant {
  path: string
  purpose: CapabilityPurpose
  actions: ReadonlySet<CapabilityAction>
  fileType: string
  expiresAt: number
}

interface GrantedPathRegistryOptions {
  now?: () => number
  ttlMs?: number
  maxCapabilities?: number
}

export class GrantedPathRegistry {
  private readonly grants = new Map<string, GrantedPath>()
  private readonly capabilities = new Map<string, CapabilityGrant>()

  constructor(private readonly options: GrantedPathRegistryOptions = {}) {}

  grant(path: string, kind: GrantedPathKind = 'file'): string {
    const normalized = normalizeAbsolutePath(path)
    this.grants.set(this.key(normalized), { path: normalized, kind })
    return normalized
  }

  grantAll(paths: readonly string[], kind: GrantedPathKind = 'file'): string[] {
    return paths.map((path) => this.grant(path, kind))
  }

  async grantSavePath(path: string): Promise<string> {
    const normalized = normalizeAbsolutePath(path)
    const saveTarget = await inspectSaveTarget(normalized)
    if (saveTarget.kind === 'other') throw new Error('另存为目标必须是文件，不能是目录或特殊路径')
    this.grants.set(this.key(normalized), { path: normalized, kind: 'save', saveTarget })
    return normalized
  }

  requireGranted(value: unknown): string {
    return this.requireGrant(value).path
  }

  requireOpenable(value: unknown): string {
    const granted = this.requireGrant(value)
    if (
      granted.kind !== 'directory'
      && !SAFE_OPEN_EXTENSIONS.has(extname(granted.path).toLocaleLowerCase())
    ) {
      throw new Error('桌面桥接只允许打开已选择的目录或受支持的数据与报告文件')
    }
    return granted.path
  }

  requireSavePath(value: unknown): string {
    return this.requireSavePathAuthorization(value).path
  }

  requireSavePathAuthorization(value: unknown): SavePathAuthorization {
    const granted = this.requireGrant(value)
    if (granted.kind !== 'save') throw new Error('该路径未获另存为授权')
    return { path: granted.path, saveTarget: granted.saveTarget }
  }

  requireDirectoryPath(value: unknown): string {
    const granted = this.requireGrant(value)
    if (granted.kind !== 'directory') throw new Error('该路径未获目录选择授权')
    return granted.path
  }

  grantCapability(
    path: string,
    purpose: CapabilityPurpose = 'artifact-download',
    actions: readonly CapabilityAction[] = ['open', 'reveal'],
  ): string | undefined {
    const normalized = normalizeAbsolutePath(path)
    const effectiveActions = new Set(isOpenableArtifactFileName(basename(normalized)) ? actions : [])
    if (!effectiveActions.size) return undefined
    const capabilityId = randomUUID()
    this.capabilities.set(capabilityId, {
      path: normalized,
      purpose,
      actions: effectiveActions,
      fileType: validateArtifactFileName(basename(normalized)),
      expiresAt: this.now() + (this.options.ttlMs ?? 15 * 60 * 1_000),
    })
    if (this.capabilities.size > (this.options.maxCapabilities ?? 256)) {
      this.capabilities.delete(this.capabilities.keys().next().value!)
    }
    return capabilityId
  }

  requireCapability(
    value: unknown,
    purpose: CapabilityPurpose,
    action: CapabilityAction,
  ): string {
    if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) throw new Error('文件授权标识无效')
    const granted = this.capabilities.get(value)
    if (!granted) throw new Error('文件授权已失效')
    if (this.now() >= granted.expiresAt) {
      this.capabilities.delete(value)
      throw new Error('文件授权已过期')
    }
    if (granted.purpose !== purpose || !granted.actions.has(action)) {
      throw new Error('文件授权用途不匹配')
    }
    if (validateArtifactFileName(basename(granted.path)) !== granted.fileType) {
      throw new Error('文件授权类型已变化')
    }
    return granted.path
  }

  clear(): void {
    this.grants.clear()
    this.capabilities.clear()
  }

  private key(path: string): string {
    return process.platform === 'win32' ? path.toLocaleLowerCase() : path
  }

  private now(): number {
    return (this.options.now ?? Date.now)()
  }

  private requireGrant(value: unknown): GrantedPath {
    const normalized = normalizeAbsolutePath(validateBridgePath(value))
    const granted = this.grants.get(this.key(normalized))
    if (!granted) throw new Error('该路径未由当前桌面会话授权')
    return granted
  }
}

export function normalizeAbsolutePath(value: string): string {
  if (!isAbsolute(value)) throw new Error('路径必须是绝对路径')
  return resolve(value)
}

export async function inspectSaveTarget(path: string): Promise<SaveTargetSnapshot> {
  try {
    const value = await lstat(path)
    if (!value.isFile()) return { kind: 'other' }
    return {
      kind: 'file',
      size: value.size,
      mtimeMs: value.mtimeMs,
      ctimeMs: value.ctimeMs,
      birthtimeMs: value.birthtimeMs,
      dev: value.dev,
      ino: value.ino,
    }
  } catch (cause) {
    if (cause instanceof Error && 'code' in cause && cause.code === 'ENOENT') {
      return { kind: 'missing' }
    }
    throw cause
  }
}

export async function assertSaveTargetUnchanged(
  path: string,
  expected: SaveTargetSnapshot,
): Promise<void> {
  const current = await inspectSaveTarget(path)
  if (!saveTargetsMatch(expected, current)) throw new SaveTargetChangedError()
}

export class SaveTargetChangedError extends Error {
  readonly code = 'SAVE_TARGET_CHANGED'

  constructor() {
    super('目标文件在导出期间发生变化，请重新选择保存位置。')
    this.name = 'SaveTargetChangedError'
  }
}

function saveTargetsMatch(left: SaveTargetSnapshot, right: SaveTargetSnapshot): boolean {
  if (left.kind !== right.kind) return false
  if (left.kind !== 'file' || right.kind !== 'file') return true
  return left.size === right.size
    && left.mtimeMs === right.mtimeMs
    && left.ctimeMs === right.ctimeMs
    && left.birthtimeMs === right.birthtimeMs
    && left.dev === right.dev
    && left.ino === right.ino
}
