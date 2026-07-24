import { describe, expect, it } from 'vitest'

import {
  DATA_ROOT_REGISTRY_KEY,
  DATA_ROOT_REGISTRY_VALUE,
  readMachineDataRoot,
  resolveDesktopDataRootConfiguration,
} from '../src/main/data-root-configuration'

describe('desktop machine data-root configuration', () => {
  it('uses an explicit root before the machine-wide installer pointer', () => {
    const result = resolveDesktopDataRootConfiguration({
      platform: 'win32',
      environment: { NETCONSOLE_DATA_ROOT: 'E:\\ManualNetConsoleData' },
      queryRegistry: () => ({ status: 0, stdout: 'ignored' }),
    })

    expect(result).toEqual({ dataRoot: 'E:\\ManualNetConsoleData', source: 'environment' })
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
})
