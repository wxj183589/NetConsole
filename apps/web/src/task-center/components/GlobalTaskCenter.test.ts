import { describe, expect, it } from 'vitest'

import source from './GlobalTaskCenter.vue?raw'

describe('GlobalTaskCenter', () => {
  it('keeps one global task connection and three non-blocking task surfaces', () => {
    expect(source).toContain("const GLOBAL_POLLING_CONSUMER = 'global-task-center'")
    expect(source).toContain('data-testid="global-task-indicator"')
    expect(source).toContain('data-testid="task-center-drawer"')
    expect(source).toContain('data-testid="active-task-floating-card"')
    expect(source).toContain('进入完整任务中心')
    expect(source).toContain('floatingDismissedSignature')
  })

  it('deduplicates terminal notifications and separates foreground from native delivery', () => {
    expect(source).toContain('previous === key')
    expect(source).toContain("document.visibilityState === 'visible' && document.hasFocus()")
    expect(source).toContain("runtime.hostType !== 'electron'")
    expect(source).toContain('showTaskNotification')
    expect(source).toContain("duration: kind === 'success' ? 5000 : 0")
  })

  it('updates the tray with bounded aggregate task status instead of task payloads', () => {
    expect(source).toContain('setTaskTrayStatus({ active, failed, warning })')
    expect(source).not.toContain('ipcRenderer')
  })
})
