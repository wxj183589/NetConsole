import { describe, expect, it } from 'vitest'

import source from './ConsoleWorkspaceView.vue?raw'
import workspaceSource from './useConsoleWorkspace.ts?raw'

describe('ConsoleWorkspaceView responsive toolbar', () => {
  it('keeps all terminal actions reachable at the minimum desktop width', () => {
    expect(source).toContain('overflow-x: auto;')
    expect(source).toContain('.terminal-search { flex: 0 0 150px;')
  })

  it('opens a registered device passed from device management exactly once', () => {
    expect(workspaceSource).toContain("query.device_uuid")
    expect(workspaceSource).toContain("router.replace({ name: 'device-console'")
    expect(workspaceSource).toContain('if (requestedDevice) await openDevice(requestedDevice)')
  })
})
