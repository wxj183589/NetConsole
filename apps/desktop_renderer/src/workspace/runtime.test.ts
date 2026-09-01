// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  composeWorkspaceWindowTitle,
  setWorkspaceWindowTitleContext,
  updateDesktopWorkspaceTitle,
} from './runtime'

describe('workspace native title context', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'netconsoleDesktop', {
      configurable: true,
      value: { setWorkspaceWindowTitle: vi.fn() },
    })
    setWorkspaceWindowTitleContext('', '')
    vi.mocked(window.netconsoleDesktop!.setWorkspaceWindowTitle!).mockClear()
  })

  it('composes the authoritative data root and business mode without hardcoded production values', () => {
    expect(composeWorkspaceWindowTitle('设备管理', {
      dataRoot: 'D:\\NetConsoleData-dev',
      runtimeMode: 'DEVELOPMENT',
    })).toBe('设备管理 - NetConsole | 当前数据根：D:\\NetConsoleData-dev | 运行模式：DEVELOPMENT')
    expect(composeWorkspaceWindowTitle('设备管理', {
      dataRoot: 'D:\\NetConsoleData-dev',
      runtimeMode: 'PRODUCTION',
    })).toContain('运行模式：PRODUCTION')
  })

  it('keeps the current page title when health context changes', () => {
    updateDesktopWorkspaceTitle('轨旁 AP 业务')
    setWorkspaceWindowTitleContext('D:\\NetConsoleData-dev', 'DEVELOPMENT')

    expect(window.netconsoleDesktop?.setWorkspaceWindowTitle).toHaveBeenLastCalledWith(
      '轨旁 AP 业务 - NetConsole | 当前数据根：D:\\NetConsoleData-dev | 运行模式：DEVELOPMENT',
    )
  })

  it('bounds long page and environment titles to the native bridge contract', () => {
    const title = composeWorkspaceWindowTitle('轨道交通 / MR 原始 MESH 日志分析', {
      dataRoot: 'D:\\NetConsoleData-dev',
      runtimeMode: 'DEVELOPMENT',
    })

    expect(title.length).toBeLessThanOrEqual(80)
    expect(title).toContain('轨道交通 / MR 原始 MESH 日志分析')
    expect(title).toContain(' - NetConsole')
  })
})
