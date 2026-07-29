// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  launchExternalTool,
  listExternalTools,
  splitExternalToolArguments,
} from './externalTools'

afterEach(() => Reflect.deleteProperty(window, 'netconsoleDesktop'))

describe('external tools desktop API', () => {
  it('fails closed in browser mode instead of falling back to HTTP or downloads', async () => {
    expect(() => listExternalTools()).toThrow('仅支持 NetConsole 桌面版')
    expect(() => launchExternalTool('7c890030-3a3f-4d6b-b58e-7624d21daff9')).toThrow('仅支持 NetConsole 桌面版')
  })

  it('passes only a tool id when launching', async () => {
    const launch = vi.fn(async (toolId: string) => ({ success: true, toolId }))
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { launchExternalTool: launch },
    })
    const id = '7c890030-3a3f-4d6b-b58e-7624d21daff9'
    await launchExternalTool(id)
    expect(launch).toHaveBeenCalledWith(id)
    expect(launch).toHaveBeenCalledOnce()
  })

  it('converts quoted text to argv and rejects shell syntax', () => {
    expect(splitExternalToolArguments('--profile "现场 维护" --read-only')).toEqual([
      '--profile', '现场 维护', '--read-only',
    ])
    expect(() => splitExternalToolArguments('--profile x && calc')).toThrow('不支持管道')
    expect(() => splitExternalToolArguments('"not closed')).toThrow('引号未闭合')
  })
})
