import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getDeviceTerminalPreflight: vi.fn(),
  getExternalTerminalSettings: vi.fn(),
  issueExternalTerminalConfirmation: vi.fn(),
  launchExternalTerminals: vi.fn(),
}))

const messages = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('../api/deviceManagement', () => api)
vi.mock('element-plus', () => ({ ElMessage: messages }))

import { useDeviceTerminalLauncher } from './useDeviceTerminalLauncher'

describe('useDeviceTerminalLauncher', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getExternalTerminalSettings.mockResolvedValue({
      terminal_type: 'securecrt',
      securecrt_path: 'C:/Tools/SecureCRT.exe',
      xshell_path: '',
      putty_path: '',
      pass_password: false,
    })
  })

  it('preflights unique targets once and launches only validated UUIDs once', async () => {
    let resolvePreflight!: (value: {
      terminal_type: 'securecrt'
      launchable_devices: string[]
      skipped_devices: Array<{ device_uuid: string; available: boolean; reason: string }>
    }) => void
    api.getDeviceTerminalPreflight.mockReturnValue(new Promise((resolve) => { resolvePreflight = resolve }))
    const launcher = useDeviceTerminalLauncher()

    const firstPreflight = launcher.preflightDeviceTerminalTargets(['device-1', 'device-1', ''])
    const duplicatePreflight = await launcher.preflightDeviceTerminalTargets(['device-1'])
    expect(duplicatePreflight).toBeNull()
    expect(api.getDeviceTerminalPreflight).toHaveBeenCalledTimes(1)
    expect(api.getDeviceTerminalPreflight).toHaveBeenCalledWith(['device-1'], 'securecrt')

    resolvePreflight({
      terminal_type: 'securecrt',
      launchable_devices: ['device-1'],
      skipped_devices: [],
    })
    const preflight = await firstPreflight
    expect(preflight?.launchableDevices).toEqual(['device-1'])

    let resolveLaunch!: (value: { success: number; failed: number; failures: string[] }) => void
    api.launchExternalTerminals.mockReturnValue(new Promise((resolve) => { resolveLaunch = resolve }))
    const firstLaunch = launcher.launchDeviceTerminalTargets(preflight!.launchableDevices, preflight!.terminalType)
    const duplicateLaunch = await launcher.launchDeviceTerminalTargets(['device-1'], 'securecrt')
    expect(duplicateLaunch).toBeNull()
    expect(api.launchExternalTerminals).toHaveBeenCalledTimes(1)
    expect(api.launchExternalTerminals).toHaveBeenCalledWith(['device-1'], 'securecrt', '')

    resolveLaunch({ success: 1, failed: 0, failures: [] })
    await expect(firstLaunch).resolves.toEqual({ success: 1, failed: 0, failures: [] })
  })

  it('requires a configured allowlisted terminal and reports skipped or failed results', async () => {
    api.getExternalTerminalSettings.mockResolvedValueOnce({
      terminal_type: 'securecrt',
      securecrt_path: '',
      xshell_path: '',
      putty_path: '',
      pass_password: false,
    })
    const launcher = useDeviceTerminalLauncher()

    await expect(launcher.preflightDeviceTerminalTargets(['device-1'])).rejects.toThrow('尚未配置外部终端程序路径')
    launcher.showPreflightSkipped([{ device_uuid: 'device-1', available: false, reason: '缺少管理地址' }])
    launcher.showLaunchResult({ success: 1, failed: 1, failures: ['device-2 启动失败'] })

    expect(messages.warning).toHaveBeenNthCalledWith(1, '缺少管理地址')
    expect(messages.warning).toHaveBeenNthCalledWith(2, '外部终端启动完成：成功 1，失败 1。device-2 启动失败')
  })
})
