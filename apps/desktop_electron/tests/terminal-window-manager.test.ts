import { describe, expect, it, vi } from 'vitest'
import { DetachedTerminalWindowManager } from '../src/main/terminal-window-manager'

describe('independent terminal windows', () => {
  it('validates IDs and creates independent windows without an admission count', async () => {
    const closeSession = vi.fn(async () => undefined)
    const windows: Array<{ loadURL: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; closed?: () => void; once: (event: string, fn: () => void) => void }> = []
    const manager = new DetachedTerminalWindowManager({
      create: () => {
        const window = { loadURL: vi.fn(async () => undefined), destroy: vi.fn(), once(_event: string, fn: () => void) { this.closed = fn }, closed: undefined as (() => void) | undefined }
        windows.push(window)
        return window
      },
      prepare: vi.fn(), target: id => `/console?terminal_session=${id}`,
      verify: vi.fn(async () => undefined), closeSession,
    })
    await expect(manager.open('../secret')).rejects.toThrow()
    for (let index = 0; index < 12; index++) expect(await manager.open(index.toString(16).padStart(32, '0'))).toEqual({ success: true })
    expect(manager.windows.size).toBe(12)
    windows[0]?.closed?.()
    expect(manager.windows.size).toBe(11)
    expect(closeSession).toHaveBeenCalledWith('0'.repeat(32))
    expect(windows[1]?.destroy).not.toHaveBeenCalled()
  })
})
