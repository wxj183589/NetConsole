import type { NativeActionResult } from '../shared/bridge'

export interface DetachedTerminalWindow {
  loadURL(url: string): Promise<void>
  once(event: 'closed', callback: () => void): void
  destroy(): void
}
export class DetachedTerminalWindowManager<T extends DetachedTerminalWindow> {
  readonly windows = new Set<T>()
  private sessions = new Set<string>()
  constructor(private options: {
    create: () => T
    prepare: (window: T, target: string) => void
    target: (id: string) => string
    verify: (id: string) => Promise<void>
    closeSession: (id: string) => Promise<void>
  }) {}

  async open(id: unknown): Promise<NativeActionResult> {
    if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)) throw new Error('终端 Session ID 无效')
    if (this.sessions.has(id)) throw new Error('此会话已有独立终端窗口')
    this.sessions.add(id)
    try { await this.options.verify(id) } catch (error) { this.sessions.delete(id); throw error }
    let window: T
    try { window = this.options.create() } catch (error) { this.sessions.delete(id); throw error }
    this.windows.add(window)
    window.once('closed', () => { this.windows.delete(window); this.sessions.delete(id); void this.options.closeSession(id).catch(() => undefined) })
    try {
      const target = this.options.target(id)
      this.options.prepare(window, target)
      await window.loadURL(target)
      return { success: true }
    } catch {
      window.destroy()
      return { success: false, error: '独立终端窗口加载失败' }
    }
  }
}
