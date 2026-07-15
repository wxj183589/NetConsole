import type { BrowserWindow, Session } from 'electron'

export function contentSecurityPolicy(
  development: boolean,
  allowedOrigins: readonly string[],
): string {
  const origins = allowedOrigins.filter(isSafeLoopbackOrigin)
  const script = development ? "'self' 'unsafe-eval'" : "'self'"
  const connections = ["'self'", ...origins, ...origins.map(toWebSocketOrigin)]
  return [
    "default-src 'self'",
    `script-src ${script}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${[...new Set(connections)].join(' ')}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join('; ')
}

export function isAllowedNavigation(target: string, allowedOrigins: readonly string[]): boolean {
  try {
    const url = new URL(target)
    return allowedOrigins.some((origin) => url.origin === origin && isSafeLoopbackOrigin(origin))
  } catch {
    return false
  }
}

export function desktopSessionCookiePath(development: boolean): '/' | '/ws' {
  return development ? '/ws' : '/'
}

export function installWindowSecurity(
  window: BrowserWindow,
  getAllowedOrigins: () => readonly string[],
  development: boolean,
): void {
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  const guardNavigation = (event: { preventDefault(): void }, target: string): void => {
    if (!isAllowedNavigation(target, getAllowedOrigins())) event.preventDefault()
  }
  window.webContents.on('will-navigate', guardNavigation)
  window.webContents.on('will-redirect', guardNavigation)
  window.webContents.on('will-attach-webview', (event) => event.preventDefault())

  const currentSession: Session = window.webContents.session
  currentSession.setPermissionCheckHandler(() => false)
  currentSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  currentSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.resourceType !== 'mainFrame') {
      callback({ responseHeaders: details.responseHeaders })
      return
    }
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [contentSecurityPolicy(development, getAllowedOrigins())],
      },
    })
  })
}

export function isTrustedRendererSender(
  event: { sender: unknown; senderFrame?: { url: string } | null },
  window: { webContents: { mainFrame: unknown } },
  allowedOrigins: readonly string[],
): boolean {
  const frame = event.senderFrame
  return event.sender === window.webContents
    && frame === window.webContents.mainFrame
    && Boolean(frame && isAllowedNavigation(frame.url, allowedOrigins))
}

function isSafeLoopbackOrigin(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' && url.hostname === '127.0.0.1' && Boolean(url.port) && url.origin === value
  } catch {
    return false
  }
}

function toWebSocketOrigin(value: string): string {
  const url = new URL(value)
  return `ws://${url.host}`
}
