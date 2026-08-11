/// <reference types="vite/client" />

import type { NetConsoleDesktopBridge } from '../../desktop_electron/src/shared/bridge'

declare global {
  interface ImportMeta {
    readonly env: ImportMetaEnv
  }
  interface Window {
    netconsoleDesktop?: NetConsoleDesktopBridge
  }
}

export {}
