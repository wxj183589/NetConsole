/// <reference types="vite/client" />

import type { NetConsoleDesktopBridge } from '../../desktop_electron/src/shared/bridge'

declare global {
  interface Window {
    netconsoleDesktop?: NetConsoleDesktopBridge
  }
}

export {}
