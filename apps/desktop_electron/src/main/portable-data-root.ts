import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { isAbsolute, join, resolve } from 'node:path'

export const PORTABLE_MODE_MARKER = 'portable.mode'
export const PORTABLE_DATA_ROOT_CONFIGURATION = 'portable-data-root.json'
export const PORTABLE_DATA_DIRECTORY = 'data'

export class PortableDataRootConfigurationError extends Error {
  readonly code = 'PORTABLE_DATA_ROOT_CONFIGURATION_INVALID'

  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'PortableDataRootConfigurationError'
  }
}

export class PortableDataRootUnavailableError extends Error {
  readonly code = 'PORTABLE_DATA_ROOT_UNAVAILABLE'
  readonly dataRoot: string

  constructor(dataRoot: string, cause: unknown) {
    super(`便携版默认数据目录不可写或不可用：${dataRoot}`, { cause })
    this.name = 'PortableDataRootUnavailableError'
    this.dataRoot = dataRoot
  }
}

export function defaultPortableDataRoot(portableAppRoot: string): string {
  return resolve(requireAbsolutePath(portableAppRoot, 'portable application directory'), PORTABLE_DATA_DIRECTORY)
}

export function detectPortableMode(options: {
  portableAppRoot: string
  environment?: NodeJS.ProcessEnv
  fileExists?: (path: string) => boolean
}): boolean {
  const environment = options.environment ?? process.env
  if (environment.NETCONSOLE_PORTABLE_MODE?.trim() === '1') return true
  const fileExists = options.fileExists ?? existsSync
  return fileExists(join(requireAbsolutePath(options.portableAppRoot, 'portable application directory'), PORTABLE_MODE_MARKER))
}

export class PortableDataRootStore {
  readonly path: string
  readonly portableAppRoot: string

  constructor(portableAppRoot: string, private readonly fileExists: (path: string) => boolean = existsSync) {
    this.portableAppRoot = requireAbsolutePath(portableAppRoot, 'portable application directory')
    this.path = join(this.portableAppRoot, PORTABLE_DATA_ROOT_CONFIGURATION)
  }

  load(): string | undefined {
    if (!this.fileExists(this.path)) return undefined
    let parsed: unknown
    try {
      parsed = JSON.parse(readFileSync(this.path, 'utf8'))
    } catch (cause) {
      throw new PortableDataRootConfigurationError(
        `便携版数据根配置无法读取：${this.path}`,
        { cause },
      )
    }
    if (!parsed || typeof parsed !== 'object') {
      throw new PortableDataRootConfigurationError('便携版数据根配置必须是 JSON 对象')
    }
    const value = parsed as Record<string, unknown>
    if (value.schema_version !== 1 || typeof value.data_root !== 'string') {
      throw new PortableDataRootConfigurationError('便携版数据根配置版本或 data_root 无效')
    }
    try {
      return requireAbsolutePath(value.data_root, '便携版 data_root')
    } catch (cause) {
      throw new PortableDataRootConfigurationError('便携版 data_root 必须是绝对路径', { cause })
    }
  }

  save(dataRoot: string | undefined): void {
    const normalized = dataRoot ? requireAbsolutePath(dataRoot, '便携版 data_root') : undefined
    if (!normalized || normalized === defaultPortableDataRoot(this.portableAppRoot)) {
      rmSync(this.path, { force: true })
      return
    }
    const temporary = `${this.path}.${process.pid}.tmp`
    try {
      writeFileSync(
        temporary,
        `${JSON.stringify({ schema_version: 1, data_root: normalized }, null, 2)}\n`,
        { encoding: 'utf8', flag: 'w' },
      )
      renameSync(temporary, this.path)
    } finally {
      rmSync(temporary, { force: true })
    }
  }
}

function requireAbsolutePath(value: string, label: string): string {
  if (!isAbsolute(value) || /[\u0000-\u001f]/.test(value)) {
    throw new TypeError(`${label} must be an absolute path`)
  }
  return resolve(value)
}
