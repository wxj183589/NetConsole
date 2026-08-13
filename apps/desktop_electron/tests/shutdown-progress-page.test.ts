import { describe, expect, it, vi } from 'vitest'

import { ShutdownProgressPage } from '../src/main/shutdown-progress-page'

function createWindow() {
  return {
    isDestroyed: vi.fn(() => false),
    setBackgroundColor: vi.fn(),
    loadURL: vi.fn<(url: string) => Promise<void>>(async () => undefined),
    webContents: { executeJavaScript: vi.fn<(script: string, userGesture?: boolean) => Promise<void>>(async () => undefined) },
  }
}

describe('ShutdownProgressPage', () => {
  it('loads once, renders the current stage, and updates without navigation', async () => {
    const window = createWindow()
    const page = new ShutdownProgressPage({ window: window as never, isDark: () => false })
    page.update('正在结束文件保存')
    await page.load()
    page.update('正在完成退出')

    expect(window.loadURL).toHaveBeenCalledOnce()
    expect(decodeURIComponent(String(window.loadURL.mock.calls[0][0]))).toContain('正在安全退出 NetConsole')
    expect(window.webContents.executeJavaScript).toHaveBeenCalledTimes(2)
    expect(window.webContents.executeJavaScript.mock.calls.at(-1)?.[0]).toContain('正在完成退出')
  })

  it('cleans up updates after disposal', async () => {
    const window = createWindow()
    const page = new ShutdownProgressPage({ window: window as never, isDark: () => true })
    await page.load()
    page.dispose()
    page.update('ignored')

    expect(window.webContents.executeJavaScript).toHaveBeenCalledOnce()
  })
})
