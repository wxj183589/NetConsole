import { beforeEach, describe, expect, it, vi } from 'vitest'

const deviceApi = vi.hoisted(() => ({
  getDeviceTerminalPreflight: vi.fn(),
  getExternalTerminalSettings: vi.fn(),
  issueExternalTerminalConfirmation: vi.fn(),
  launchExternalTerminals: vi.fn(),
}))
const acApi = vi.hoisted(() => ({
  getAcExternalTerminalOptions: vi.fn(),
  openAcFitApExternalTerminal: vi.fn(),
}))
const messages = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}))
const routerPush = vi.hoisted(() => vi.fn())

vi.mock('../api/deviceManagement', () => deviceApi)
vi.mock('../api/acWebParity', () => acApi)
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('element-plus', () => ({
  ElMessage: messages,
  ElMessageBox: { confirm: messages.confirm },
}))

import { useExternalTerminalLauncher } from './useExternalTerminalLauncher'

describe('useExternalTerminalLauncher', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    deviceApi.getExternalTerminalSettings.mockResolvedValue({
      terminal_type: 'securecrt',
      securecrt_path: 'C:/Tools/SecureCRT.exe',
      xshell_path: '',
      putty_path: '',
      pass_password: false,
    })
    acApi.getAcExternalTerminalOptions.mockResolvedValue({
      default_terminal_type: 'securecrt',
      options: [{ terminal_type: 'securecrt', label: 'SecureCRT' }],
    })
    acApi.openAcFitApExternalTerminal.mockResolvedValue({
      ap_id: 'fit-ap-1',
      terminal_type: 'securecrt',
      protocol: 'telnet',
      port: 23,
      success: true,
      message: '已打开 AP 外部终端',
    })
  })

  it('preflights unique device targets once and launches only validated UUIDs once', async () => {
    let resolvePreflight!: (value: {
      terminal_type: 'securecrt'
      launchable_devices: string[]
      skipped_devices: Array<{ device_uuid: string; available: boolean; reason: string }>
    }) => void
    deviceApi.getDeviceTerminalPreflight.mockReturnValue(new Promise((resolve) => { resolvePreflight = resolve }))
    const launcher = useExternalTerminalLauncher()

    const firstPreflight = launcher.preflightDeviceTerminalTargets(['device-1', 'device-1', ''])
    const duplicatePreflight = await launcher.preflightDeviceTerminalTargets(['device-1'])
    expect(duplicatePreflight).toBeNull()
    expect(deviceApi.getDeviceTerminalPreflight).toHaveBeenCalledTimes(1)
    expect(deviceApi.getDeviceTerminalPreflight).toHaveBeenCalledWith(['device-1'], 'securecrt')

    resolvePreflight({ terminal_type: 'securecrt', launchable_devices: ['device-1'], skipped_devices: [] })
    const preflight = await firstPreflight
    let resolveLaunch!: (value: { success: number; failed: number; failures: string[] }) => void
    deviceApi.launchExternalTerminals.mockReturnValue(new Promise((resolve) => { resolveLaunch = resolve }))
    const firstLaunch = launcher.launchDeviceTerminalTargets(preflight!.launchableDevices, preflight!.terminalType)
    const duplicateLaunch = await launcher.launchDeviceTerminalTargets(['device-1'], 'securecrt')
    expect(duplicateLaunch).toBeNull()
    expect(deviceApi.launchExternalTerminals).toHaveBeenCalledTimes(1)
    resolveLaunch({ success: 1, failed: 0, failures: [] })
    await expect(firstLaunch).resolves.toEqual({ success: 1, failed: 0, failures: [] })
  })

  it('launches a FIT-AP through the existing AC target contract and suppresses rapid duplicates', async () => {
    let resolveOptions!: (value: {
      default_terminal_type: 'securecrt'
      options: Array<{ terminal_type: 'securecrt'; label: string }>
    }) => void
    acApi.getAcExternalTerminalOptions.mockReturnValue(new Promise((resolve) => { resolveOptions = resolve }))
    const launcher = useExternalTerminalLauncher()

    const first = launcher.requestFitApTerminal({ acId: ' ac-1 ', apId: ' fit-ap-1 ' })
    await expect(launcher.requestFitApTerminal({ acId: 'ac-1', apId: 'fit-ap-1' })).resolves.toBeNull()
    expect(acApi.getAcExternalTerminalOptions).toHaveBeenCalledTimes(1)

    resolveOptions({ default_terminal_type: 'securecrt', options: [{ terminal_type: 'securecrt', label: 'SecureCRT' }] })
    await expect(first).resolves.toMatchObject({ ap_id: 'fit-ap-1', success: true })
    expect(acApi.openAcFitApExternalTerminal).toHaveBeenCalledTimes(1)
    expect(acApi.openAcFitApExternalTerminal).toHaveBeenCalledWith('fit-ap-1', 'ac-1', 'securecrt')
    expect(messages.success).toHaveBeenCalledWith('已打开 AP 外部终端')
  })

  it('shares FIT-AP terminal selection, settings prompt, and device result messages', async () => {
    acApi.getAcExternalTerminalOptions.mockResolvedValueOnce({
      default_terminal_type: 'xshell',
      options: [
        { terminal_type: 'securecrt', label: 'SecureCRT' },
        { terminal_type: 'xshell', label: 'Xshell' },
      ],
    })
    const launcher = useExternalTerminalLauncher()
    await launcher.requestFitApTerminal({ acId: 'ac-1', apId: 'fit-ap-1' })
    expect(launcher.fitApTerminalVisible.value).toBe(true)
    expect(launcher.fitApTerminalType.value).toBe('xshell')

    await launcher.launchSelectedFitApTerminal()
    expect(acApi.openAcFitApExternalTerminal).toHaveBeenCalledWith('fit-ap-1', 'ac-1', 'xshell')

    acApi.getAcExternalTerminalOptions.mockResolvedValueOnce({ default_terminal_type: null, options: [] })
    messages.confirm.mockResolvedValueOnce(undefined)
    await launcher.requestFitApTerminal({ acId: 'ac-2', apId: 'fit-ap-2' })
    expect(routerPush).toHaveBeenCalledWith({ name: 'tool-collection', query: { section: 'external-terminal' } })

    launcher.showPreflightSkipped([{ device_uuid: 'device-1', available: false, reason: '缺少管理地址' }])
    launcher.showLaunchResult({ success: 1, failed: 1, failures: ['device-2 启动失败'] })
    expect(messages.warning).toHaveBeenNthCalledWith(1, '缺少管理地址')
    expect(messages.warning).toHaveBeenNthCalledWith(2, '外部终端启动完成：成功 1，失败 1。device-2 启动失败')
  })

  it('uses the shared sanitized error message when FIT-AP launch fails', async () => {
    acApi.openAcFitApExternalTerminal.mockRejectedValueOnce(
      new Error('启动失败 password=secret C:\\Tools\\SecureCRT.exe'),
    )
    const launcher = useExternalTerminalLauncher()

    await launcher.requestFitApTerminal({ acId: 'ac-1', apId: 'fit-ap-1' })

    expect(messages.error).toHaveBeenCalledWith('启动失败 password=*** <本机路径>')
    expect(acApi.openAcFitApExternalTerminal).toHaveBeenCalledTimes(1)
  })
})
