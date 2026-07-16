import { randomUUID } from 'node:crypto'
import { extname, isAbsolute, resolve } from 'node:path'

import { validateBridgePath } from '../shared/validation'

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
}

export class GrantedPathRegistry {
  private readonly grants = new Map<string, GrantedPath>()
  private readonly capabilities = new Map<string, GrantedPath>()

  grant(path: string, kind: GrantedPathKind = 'file'): string {
    const normalized = normalizeAbsolutePath(path)
    this.grants.set(this.key(normalized), { path: normalized, kind })
    return normalized
  }

  grantAll(paths: readonly string[], kind: GrantedPathKind = 'file'): string[] {
    return paths.map((path) => this.grant(path, kind))
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

  grantCapability(path: string, kind: GrantedPathKind = 'save'): string {
    const capabilityId = randomUUID()
    this.capabilities.set(capabilityId, { path: normalizeAbsolutePath(path), kind })
    if (this.capabilities.size > 256) this.capabilities.delete(this.capabilities.keys().next().value!)
    return capabilityId
  }

  requireCapability(value: unknown, openable = false): string {
    if (typeof value !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)) throw new Error('文件授权标识无效')
    const granted = this.capabilities.get(value)
    if (!granted) throw new Error('文件授权已失效')
    if (openable && granted.kind !== 'directory' && !SAFE_OPEN_EXTENSIONS.has(extname(granted.path).toLocaleLowerCase())) {
      throw new Error('桌面桥接只允许打开受支持的数据与报告文件')
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
