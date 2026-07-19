import { describe, expect, it } from 'vitest'

import { SETTINGS_TOOL_DEFINITIONS, settingsToolMismatchMessage, settingsToolNameMatches } from '../src/shared/bridge'

describe('settings tool definitions', () => {
  it.each(['putty.exe', 'PuTTY.exe', 'putty64.exe', 'PuTTY64.exe', 'PUTTY64.EXE'])('accepts PuTTY executable %s case-insensitively', (name) => {
    expect(settingsToolNameMatches('putty', `D:\\Tools\\${name}`)).toBe(true)
  })

  it.each(['puttygen.exe', 'plink.exe', 'psftp.exe', 'putty.exe.bak', 'putty.bat'])('rejects non-PuTTY executable %s', (name) => {
    expect(settingsToolNameMatches('putty', `D:\\Tools\\${name}`)).toBe(false)
  })

  it('keeps the renderer contract semantic and uses an exe-only native filter', () => {
    expect(SETTINGS_TOOL_DEFINITIONS.putty).toMatchObject({
      filterName: 'PuTTY',
      executableNames: ['putty.exe', 'putty64.exe'],
    })
    expect(settingsToolMismatchMessage('putty')).toBe('所选程序与 PuTTY 类型不匹配。请选择 putty.exe 或 putty64.exe。')
  })
})
