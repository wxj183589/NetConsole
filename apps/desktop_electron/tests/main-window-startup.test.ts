import { describe, expect, it, vi } from 'vitest'

import {
  centeredBounds,
  installMainWindowStartup,
} from '../src/main/main-window-startup'

function createHarness() {
  let readyToShow: (() => void) | undefined
  let destroyed = false
  const calls: string[] = []
  const window = {
    isDestroyed: () => destroyed,
    setBounds: vi.fn(() => calls.push('setBounds')),
    maximize: vi.fn(() => calls.push('maximize')),
    show: vi.fn(() => calls.push('show')),
    focus: vi.fn(() => calls.push('focus')),
    once: vi.fn((event: 'ready-to-show', listener: () => void) => {
      if (event === 'ready-to-show') readyToShow = listener
    }),
  }
  return {
    window,
    calls,
    emitReadyToShow: () => readyToShow?.(),
    destroy: () => { destroyed = true },
  }
}

describe('main window startup', () => {
  it('uses the current primary display when ready and starts maximized and focused', () => {
    const harness = createHarness()
    let primaryWorkArea = { x: 1_920, y: 0, width: 1_920, height: 1_040 }
    installMainWindowStartup(harness.window, () => primaryWorkArea)

    primaryWorkArea = { x: -2_560, y: 40, width: 2_560, height: 1_400 }
    harness.emitReadyToShow()

    expect(harness.window.setBounds).toHaveBeenCalledWith({
      x: -1_920,
      y: 340,
      width: 1_280,
      height: 800,
    })
    expect(harness.calls).toEqual(['setBounds', 'maximize', 'show', 'focus'])
  })

  it('does not reapply startup state after the one-shot ready event', () => {
    const harness = createHarness()
    installMainWindowStartup(
      harness.window,
      () => ({ x: 0, y: 0, width: 1_920, height: 1_040 }),
    )

    harness.emitReadyToShow()
    expect(harness.window.maximize).toHaveBeenCalledOnce()
  })

  it('does nothing if startup finishes after the window was destroyed', () => {
    const harness = createHarness()
    installMainWindowStartup(
      harness.window,
      () => ({ x: 0, y: 0, width: 1_920, height: 1_040 }),
    )
    harness.destroy()
    harness.emitReadyToShow()

    expect(harness.calls).toEqual([])
  })

  it('keeps the safe default bounds inside a small primary work area', () => {
    expect(centeredBounds({ x: 100, y: 50, width: 1_100, height: 720 })).toEqual({
      x: 100,
      y: 50,
      width: 1_100,
      height: 720,
    })
  })
})
