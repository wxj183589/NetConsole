import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  DATA_ROOT_REGISTRY_KEY,
  DATA_ROOT_REGISTRY_VALUE,
  formatDesktopDataRootConfigurationError,
  readMachineDataRoot,
  resolveDesktopDataRootConfiguration,
} from '../src/main/data-root-configuration'
import { PortableDataRootStore } from '../src/main/portable-data-root'

describe('desktop machine data-root configuration', () => {
  it('uses an explicit root before the machine-wide installer pointer', () => {
    const result = resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: { NETCONSOLE_DATA_ROOT: 'E:\\ManualNetConsoleData' },
      queryRegistry: () => ({ status: 0, stdout: 'ignored' }),
    })

    expect(result).toEqual({ dataRoot: 'E:\\ManualNetConsoleData', source: 'environment' })
  })

  it('preserves an explicit development root for isolated real-data validation', () => {
    const result = resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: { NETCONSOLE_DATA_ROOT: 'D:\\NetConsoleData-dev' },
      queryRegistry: () => ({ status: 0, stdout: '    DataRoot    REG_SZ    D:\\NetConsoleData\r\n' }),
    })

    expect(result).toEqual({ dataRoot: 'D:\\NetConsoleData-dev', source: 'environment' })
  })

  it('reads the 64-bit HKLM pointer written by the installer', () => {
    let call: [string, string[]] | undefined
    const result = resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: {},
      queryRegistry: (command, args) => {
        call = [command, args]
        return { status: 0, stdout: '    DataRoot    REG_SZ    D:\\NetConsoleData\r\n' }
      },
    })

    expect(result).toEqual({ dataRoot: 'D:\\NetConsoleData', source: 'machine_configuration' })
    expect(call).toEqual(['reg.exe', ['query', DATA_ROOT_REGISTRY_KEY, '/v', DATA_ROOT_REGISTRY_VALUE, '/reg:64']])
  })

  it('decodes a Windows Chinese code-page registry value for packaged GUI startup', () => {
    const output = Buffer.concat([
      Buffer.from('    DataRoot    REG_SZ    D:\\NetConsoleData\\', 'ascii'),
      Buffer.from('d3c3bba7cafdbedd', 'hex'),
      Buffer.from('\r\n', 'ascii'),
    ])

    expect(readMachineDataRoot(() => ({ status: 0, stdout: output }))).toBe('D:\\NetConsoleData\\用户数据')
  })

  it('never consults the registry in explicit test mode', () => {
    expect(() => resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: { NETCONSOLE_RUNTIME_MODE: 'test' },
      queryRegistry: () => {
        throw new Error('registry must not be read')
      },
    })).toThrow('测试模式必须显式')
  })

  it('rejects malformed registry values and an unconfigured machine', () => {
    expect(readMachineDataRoot(() => ({ status: 0, stdout: 'DataRoot REG_SZ relative-data' }))).toBeUndefined()
    expect(() => resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: {},
      queryRegistry: () => ({ status: 1 }),
    })).toThrow('尚未配置')
  })

  it('uses the executable-directory data root for an unconfigured portable package', () => {
    const result = resolveDesktopDataRootConfiguration({
      platform: 'win32',
      portableMode: true,
      portableAppRoot: 'D:\\NetConsole-portable',
      environment: {},
      queryRegistry: () => {
        throw new Error('portable startup must not read the installer registry')
      },
    })

    expect(result).toEqual({
      dataRoot: 'D:\\NetConsole-portable\\data',
      source: 'portable_default',
    })
  })

  it('persists and restores a portable custom root without changing old data', () => {
    const portableRoot = mkdtempSync(join(tmpdir(), 'netconsole-portable-root-'))
    const customRoot = mkdtempSync(join(tmpdir(), 'netconsole-portable-business-'))
    try {
      writeFileSync(join(portableRoot, 'keep.txt'), 'keep', 'utf8')
      const store = new PortableDataRootStore(portableRoot)
      store.save(customRoot)

      const result = resolveDesktopDataRootConfiguration({
        platform: 'win32',
        portableMode: true,
        portableAppRoot: portableRoot,
        environment: {},
      })

      expect(result).toEqual({ dataRoot: customRoot, source: 'portable_configuration' })
      expect(store.load()).toBe(customRoot)
      expect(readFileSync(join(portableRoot, 'keep.txt'), 'utf8')).toBe('keep')
      expect(existsSync(join(portableRoot, 'data'))).toBe(false)
    } finally {
      rmSync(portableRoot, { recursive: true, force: true })
      rmSync(customRoot, { recursive: true, force: true })
    }
  })

  it('fails closed on malformed portable root configuration', () => {
    const portableRoot = mkdtempSync(join(tmpdir(), 'netconsole-portable-invalid-'))
    try {
      writeFileSync(join(portableRoot, 'portable-data-root.json'), '{not-json', 'utf8')
      expect(() => resolveDesktopDataRootConfiguration({
        platform: 'win32',
        portableMode: true,
        portableAppRoot: portableRoot,
        environment: {},
      })).toThrow('配置无法读取')
    } finally {
      rmSync(portableRoot, { recursive: true, force: true })
    }
  })

  it('turns missing installer configuration into a user-facing recovery message', () => {
    const message = formatDesktopDataRootConfigurationError(
      new Error('尚未配置 NetConsole 数据目录。请通过安装程序选择非系统盘的数据存放位置。'),
    )
    expect(message).toContain('尚未完成数据目录配置')
    expect(message).toContain('重新运行安装程序')
    expect(message).toContain('不会切换或猜测其他数据目录')
  })
})
