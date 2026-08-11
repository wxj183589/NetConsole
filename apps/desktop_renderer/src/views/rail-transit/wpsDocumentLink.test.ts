// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  hostType: 'electron' as 'browser' | 'electron',
  openExternalUrl: vi.fn(),
}))

vi.mock('../../platform/runtime', () => ({
  getPlatformAdapter: () => ({
    hostType: mocks.hostType,
    openExternalUrl: mocks.openExternalUrl,
  }),
}))

import { openWpsDocumentUrl, validateWpsDocumentUrl } from './wpsDocumentLink'

describe('WPS document external links', () => {
  beforeEach(() => {
    mocks.hostType = 'electron'
    mocks.openExternalUrl.mockReset()
    mocks.openExternalUrl.mockResolvedValue({ success: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('validates and delegates ordinary WPS document URLs', async () => {
    const url = 'https://www.kdocs.cn/l/standard'
    expect(validateWpsDocumentUrl(url)).toBe(url)
    await expect(openWpsDocumentUrl(url)).resolves.toEqual({ success: true })
    expect(mocks.openExternalUrl).toHaveBeenCalledWith(url)
  })

  it('rejects unsafe or non-WPS document URLs before invoking the adapter', async () => {
    for (const value of [
      'http://www.kdocs.cn/l/document',
      'https://example.com/l/document',
      'https://www.kdocs.cn/l/document?token=secret',
      'https://user:password@www.kdocs.cn/l/document',
    ]) {
      await expect(openWpsDocumentUrl(value)).resolves.toEqual({ success: false, error: '在线文档地址无效' })
    }
    expect(mocks.openExternalUrl).not.toHaveBeenCalled()
  })

  it('does not use window.open when Electron external opening fails', async () => {
    mocks.openExternalUrl.mockResolvedValue({ success: false, error: '系统浏览器打开失败' })
    const nativeOpen = vi.spyOn(window, 'open').mockImplementation(() => null)

    await expect(openWpsDocumentUrl('https://www.kdocs.cn/l/document')).resolves.toEqual({
      success: false,
      error: '系统浏览器打开失败',
    })
    expect(nativeOpen).not.toHaveBeenCalled()
  })

  it('uses controlled browser fallback when the desktop capability is unavailable', async () => {
    mocks.hostType = 'browser'
    mocks.openExternalUrl.mockResolvedValue({ success: false, error: '当前能力仅在 NetConsole Electron Desktop 中可用' })
    const nativeOpen = vi.spyOn(window, 'open').mockImplementation(() => ({ closed: false } as Window))

    await expect(openWpsDocumentUrl('https://www.kdocs.cn/l/document')).resolves.toEqual({ success: true })
    expect(nativeOpen).toHaveBeenCalledWith('https://www.kdocs.cn/l/document', '_blank', 'noopener,noreferrer')
  })
})
