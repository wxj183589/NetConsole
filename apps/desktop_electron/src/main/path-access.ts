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

  clear(): void {
    this.grants.clear()
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
