import { describe, expect, it } from 'vitest'

import {
  contentSecurityPolicy,
  desktopSessionCookiePath,
  isAllowedNavigation,
  isTrustedRendererSender,
} from '../src/main/security'

describe('Electron security policy', () => {
  it('limits the development cookie to WebSocket paths and authenticates production assets', () => {
    expect(desktopSessionCookiePath(true)).toBe('/ws')
    expect(desktopSessionCookiePath(false)).toBe('/')
  })

  it('keeps production script policy free of eval and limits connections to loopback origins', () => {
    const policy = contentSecurityPolicy(false, [
      'http://127.0.0.1:43123',
      'https://example.com',
    ])

    expect(policy).toContain("script-src 'self'")
    expect(policy).not.toContain('unsafe-eval')
    expect(policy).toContain('http://127.0.0.1:43123')
    expect(policy).toContain('ws://127.0.0.1:43123')
    expect(policy).not.toContain('example.com')
    expect(policy).toContain("object-src 'none'")
    expect(policy).toContain("frame-ancestors 'none'")
  })

  it('allows navigation only inside an explicitly registered loopback origin', () => {
    const origins = ['http://127.0.0.1:5173']
    expect(isAllowedNavigation('http://127.0.0.1:5173/tasks', origins)).toBe(true)
    expect(isAllowedNavigation('http://127.0.0.1:5174/tasks', origins)).toBe(false)
    expect(isAllowedNavigation('https://example.com', origins)).toBe(false)
    expect(isAllowedNavigation('file:///C:/Windows/System32/calc.exe', origins)).toBe(false)
  })

  it('trusts only the current main frame at an allowed origin for IPC', () => {
    const mainFrame = { url: 'http://127.0.0.1:5173/tasks' }
    const webContents = { mainFrame }
    const window = { webContents }
    const origins = ['http://127.0.0.1:5173']

    expect(isTrustedRendererSender({ sender: webContents, senderFrame: mainFrame }, window, origins)).toBe(true)
    expect(isTrustedRendererSender({ sender: webContents, senderFrame: { url: mainFrame.url } }, window, origins)).toBe(false)
    mainFrame.url = 'https://example.com/'
    expect(isTrustedRendererSender({ sender: webContents, senderFrame: mainFrame }, window, origins)).toBe(false)
  })
})
