import { spawnSync } from 'node:child_process'
import { isAbsolute, resolve } from 'node:path'
import { TextDecoder } from 'node:util'

export const DATA_ROOT_REGISTRY_KEY = 'HKLM\\Software\\NetConsole'
export const DATA_ROOT_REGISTRY_VALUE = 'DataRoot'

export type DesktopDataRootSource = 'environment' | 'machine_configuration'

export interface DesktopDataRootResolution {
  dataRoot: string
  source: DesktopDataRootSource
}

export function formatDesktopDataRootConfigurationError(cause: unknown): string {
  const detail = cause instanceof Error ? cause.message : String(cause)
  if (/尚未配置|runtime_mode\.json|storage-manifest\.json|数据目录/.test(detail)) {
    return `NetConsole 尚未完成数据目录配置。${detail}\n\n请重新运行安装程序，选择非系统盘上的本地固定磁盘目录；安装未完成前不会切换或猜测其他数据目录。`
  }
  return `NetConsole 本地运行环境配置失败。${detail}\n\n请查看安装器诊断日志，排除配置问题后重新安装。`
}

export type RegistryQuery = (command: string, args: string[]) => {
  status: number | null
  stdout?: string | Buffer
} | undefined

export function resolveDesktopDataRootConfiguration(options: {
  environment?: NodeJS.ProcessEnv
  platform?: NodeJS.Platform
  queryRegistry?: RegistryQuery
} = {}): DesktopDataRootResolution {
  const environment = options.environment ?? process.env
  const platform = options.platform ?? process.platform
  const explicit = environment.NETCONSOLE_DATA_ROOT?.trim()
  if (explicit) {
    return { dataRoot: requireAbsolutePath(explicit), source: 'environment' }
  }

  if ((environment.NETCONSOLE_RUNTIME_MODE ?? '').trim().toLowerCase() === 'test') {
    throw new Error('测试模式必须显式设置 NETCONSOLE_DATA_ROOT')
  }
  if (platform !== 'win32') {
    throw new Error('NETCONSOLE_DATA_ROOT must be configured outside Windows')
  }
  const machineRoot = readMachineDataRoot(options.queryRegistry ?? defaultRegistryQuery)
  if (!machineRoot) {
    throw new Error('尚未配置 NetConsole 数据目录。请通过安装程序选择非系统盘的数据存放位置。')
  }
  return { dataRoot: machineRoot, source: 'machine_configuration' }
}

export function readMachineDataRoot(queryRegistry: RegistryQuery = defaultRegistryQuery): string | undefined {
  const result = queryRegistry('reg.exe', ['query', DATA_ROOT_REGISTRY_KEY, '/v', DATA_ROOT_REGISTRY_VALUE, '/reg:64'])
  if (!result || result.status !== 0) return undefined
  const output = decodeRegistryOutput(result.stdout ?? '')
  const line = output.split(/\r?\n/).find((candidate) => new RegExp(`^\\s*${DATA_ROOT_REGISTRY_VALUE}\\s+REG_(?:SZ|EXPAND_SZ)\\s+`, 'i').test(candidate))
  if (!line) return undefined
  const value = line.replace(new RegExp(`^\\s*${DATA_ROOT_REGISTRY_VALUE}\\s+REG_(?:SZ|EXPAND_SZ)\\s+`, 'i'), '').trim()
  if (!value || /[\u0000-\u001f]/.test(value)) return undefined
  try {
    return requireAbsolutePath(value)
  } catch {
    return undefined
  }
}

function requireAbsolutePath(value: string): string {
  if (!isAbsolute(value) || /[\u0000-\u001f]/.test(value)) {
    throw new Error('NETCONSOLE_DATA_ROOT must be an absolute path')
  }
  return resolve(value)
}

function defaultRegistryQuery(command: string, args: string[]) {
  // reg.exe uses the active Windows console code page when launched by a GUI
  // process. Keep the bytes and decode UTF-8/GB18030 explicitly so Chinese
  // installation and data-root paths survive a packaged Electron startup.
  return spawnSync(command, args, { encoding: 'buffer', windowsHide: true })
}

function decodeRegistryOutput(value: string | Buffer): string {
  if (typeof value === 'string') return value
  if (value.length >= 2 && value[0] === 0xff && value[1] === 0xfe) {
    return value.subarray(2).toString('utf16le')
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(value)
  } catch {
    return new TextDecoder('gb18030').decode(value)
  }
}
