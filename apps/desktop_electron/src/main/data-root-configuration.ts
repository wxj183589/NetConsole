import { spawnSync } from 'node:child_process'
import { isAbsolute, resolve } from 'node:path'

export const DATA_ROOT_REGISTRY_KEY = 'HKLM\\Software\\NetConsole'
export const DATA_ROOT_REGISTRY_VALUE = 'DataRoot'

export type DesktopDataRootSource = 'environment' | 'machine_configuration'

export interface DesktopDataRootResolution {
  dataRoot: string
  source: DesktopDataRootSource
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
  const explicit = environment.NETCONSOLE_DATA_ROOT?.trim()
  if (explicit) return { dataRoot: requireAbsolutePath(explicit), source: 'environment' }

  if ((environment.NETCONSOLE_RUNTIME_MODE ?? '').trim().toLowerCase() === 'test') {
    throw new Error('测试模式必须显式设置 NETCONSOLE_DATA_ROOT')
  }
  const platform = options.platform ?? process.platform
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
  const output = String(result.stdout ?? '')
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
  return spawnSync(command, args, { encoding: 'utf8', windowsHide: true })
}
