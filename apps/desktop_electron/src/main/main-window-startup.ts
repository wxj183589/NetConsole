import type { WorkspaceWindowBounds } from './workspace-layout-store'

export const MAIN_WINDOW_DEFAULT_WIDTH = 1_280
export const MAIN_WINDOW_DEFAULT_HEIGHT = 800

export interface MainWindowStartupLike {
  isDestroyed(): boolean
  setBounds(bounds: WorkspaceWindowBounds): void
  maximize(): void
  show(): void
  focus(): void
  once(event: 'ready-to-show', listener: () => void): void
}

export function installMainWindowStartup(
  window: MainWindowStartupLike,
  getPrimaryWorkArea: () => WorkspaceWindowBounds,
  logger: (event: string) => void = () => undefined,
): void {
  window.once('ready-to-show', () => {
    if (window.isDestroyed()) return
    window.setBounds(centeredBounds(getPrimaryWorkArea()))
    window.maximize()
    window.show()
    window.focus()
    logger('ELECTRON_MAIN_WINDOW_STARTED_MAXIMIZED_ON_PRIMARY_DISPLAY')
  })
}

export function centeredBounds(workArea: WorkspaceWindowBounds): WorkspaceWindowBounds {
  const width = Math.min(MAIN_WINDOW_DEFAULT_WIDTH, workArea.width)
  const height = Math.min(MAIN_WINDOW_DEFAULT_HEIGHT, workArea.height)
  return {
    x: workArea.x + Math.max(0, Math.round((workArea.width - width) / 2)),
    y: workArea.y + Math.max(0, Math.round((workArea.height - height) / 2)),
    width,
    height,
  }
}
