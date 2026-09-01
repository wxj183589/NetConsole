import { describe, expect, it, vi } from 'vitest'

import { ShutdownProgressPage, shutdownStagePercent } from '../src/main/shutdown-progress-page'

function createWindow() {
  return {
    isDestroyed: vi.fn(() => false),
    setBackgroundColor: vi.fn(),
    loadURL: vi.fn<(url: string) => Promise<void>>(async () => undefined),
    webContents: { executeJavaScript: vi.fn<(script: string, userGesture?: boolean) => Promise<void>>(async () => undefined) },
  }
}

describe('ShutdownProgressPage', () => {
  it('maps real shutdown phases to deterministic, monotonic percentages', () => {
    expect(shutdownStagePercent('shutdown_started')).toBe(10)
    expect(shutdownStagePercent('blocking_new_work')).toBe(30)
    expect(shutdownStagePercent('draining_tasks')).toBe(55)
    expect(shutdownStagePercent('persistence_draining')).toBe(70)
    expect(shutdownStagePercent('backend_stopped')).toBe(95)
    expect(shutdownStagePercent('complete')).toBe(100)
    expect(shutdownStagePercent('unknown')).toBe(0)
  })

  it('loads once, renders the current stage, and updates without navigation', async () => {
    const window = createWindow()
    const page = new ShutdownProgressPage({ window: window as never, isDark: () => false })
    page.update('draining_downloads', '正在结束文件保存')
    await page.load()
    page.update('finalizing_windows', '正在完成退出')

    expect(window.loadURL).toHaveBeenCalledOnce()
    const html = decodeURIComponent(String(window.loadURL.mock.calls[0][0]))
    expect(html).toContain('正在安全退出 NetConsole')
    expect(html).toContain('40%')
    expect(html).toContain('width:40%')
    expect(html).not.toMatch(/已等待|预计剩余|预计时间|setInterval|startedAt|Date\.now|elapsedSeconds|waitSeconds/)
    expect(window.webContents.executeJavaScript).toHaveBeenCalledTimes(2)
    expect(window.webContents.executeJavaScript.mock.calls.at(-1)?.[0]).toContain('正在完成退出')
    expect(window.webContents.executeJavaScript.mock.calls.at(-1)?.[0]).toContain(',98)')
  })

  it('keeps the displayed percentage stable when a later event is out of order', async () => {
    const window = createWindow()
    const page = new ShutdownProgressPage({ window: window as never, isDark: () => false })
    await page.load()
    page.update('draining_tasks', '正在安全停止后台任务')
    page.update('stopping_backend', '正在停止本地核心服务')

    expect(window.webContents.executeJavaScript.mock.calls.at(-2)?.[0]).toContain(',55)')
    expect(window.webContents.executeJavaScript.mock.calls.at(-1)?.[0]).toContain(',55)')
  })

  it('cleans up updates after disposal', async () => {
    const window = createWindow()
    const page = new ShutdownProgressPage({ window: window as never, isDark: () => true })
    await page.load()
    page.dispose()
    page.update('unknown', 'ignored')

    expect(window.webContents.executeJavaScript).toHaveBeenCalledOnce()
  })
})
