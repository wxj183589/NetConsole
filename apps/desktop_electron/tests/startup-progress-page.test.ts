import { describe, expect, it, vi } from 'vitest'

import { StartupProgressPage, startupStageLabel, startupStagePercent } from '../src/main/startup-progress-page'

describe('startup progress stage labels', () => {
  it.each([
    ['paths_resolved', '正在准备数据环境'],
    ['instance_lock_acquired', '正在检查运行状态'],
    ['storage_manifest_ready', '正在检查数据兼容性'],
    ['active_site_database_ready', '正在读取当前局点'],
    ['application_built', '正在初始化核心服务'],
    ['listener_ready', '本地核心服务已启动'],
    ['backend.health_ready', '本地服务已就绪'],
  ])('maps real stage %s to a user-facing label', (stage, label) => {
    expect(startupStageLabel(stage)).toBe(label)
  })

  it('does not expose an internal stage as a fallback label', () => {
    expect(startupStageLabel('unexpected_internal_stage')).toBe('正在初始化本地核心服务')
  })

  it.each([
    ['waiting_backend', 15],
    ['backend_starting', 30],
    ['backend_ready', 55],
    ['loading_workspace', 78],
    ['ready', 100],
  ])('maps %s to a fixed stage percentage', (stage, percent) => {
    expect(startupStagePercent(stage)).toBe(percent)
  })

  it('uses a matching initial percentage and jumps the bar without an elapsed timer', async () => {
    const executeJavaScript = vi.fn(async () => undefined)
    const loadURL = vi.fn(async (_url: string) => undefined)
    const window = {
      setBackgroundColor: vi.fn(),
      loadURL,
      isDestroyed: () => false,
      webContents: { executeJavaScript },
    } as never
    const page = new StartupProgressPage({ window, isDark: () => false })

    await page.load()
    const html = decodeURIComponent(String(loadURL.mock.calls[0][0]))
    expect(html).toContain('width:8%')
    expect(html).toContain('>8%</div>')
    expect(html).not.toContain('已用时')
    expect(html).not.toContain('setInterval')

    page.update('backend_ready')
    expect(executeJavaScript).toHaveBeenLastCalledWith(
      expect.stringContaining('setStage("backend_ready",55)'),
      true,
    )
    page.update('ready')
    expect(executeJavaScript).toHaveBeenLastCalledWith(
      expect.stringContaining('setStage("ready",100)'),
      true,
    )
  })
})
