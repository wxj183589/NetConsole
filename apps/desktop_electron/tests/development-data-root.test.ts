import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  cleanupCodexTemporaryDataRoot,
  resolveCodexTemporaryDataRoot,
} from '../src/main/development-data-root'

describe('Codex temporary development data root', () => {
  it('stays disabled without the explicit marker', () => {
    expect(resolveCodexTemporaryDataRoot({ NETCONSOLE_DATA_ROOT: 'C:\\outside' }, 'C:\\Temp')).toBeUndefined()
  })

  it('accepts and cleans only the dedicated system temporary prefix', () => {
    const tempRoot = mkdtempSync(join(tmpdir(), 'netconsole-electron-test-'))
    const dataRoot = join(tempRoot, 'NetConsole-Codex-safe')
    mkdirSync(dataRoot, { recursive: true })
    try {
      const resolved = resolveCodexTemporaryDataRoot({
        NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
        NETCONSOLE_DATA_ROOT: dataRoot,
      }, tempRoot)
      cleanupCodexTemporaryDataRoot(resolved!, tempRoot)

      expect(existsSync(dataRoot)).toBe(false)
    } finally {
      rmSync(tempRoot, { recursive: true, force: true })
    }
  })

  it('rejects a marked path outside the system temporary root', () => {
    expect(() => resolveCodexTemporaryDataRoot({
      NETCONSOLE_DEV_TEMP_DATA_ROOT: '1',
      NETCONSOLE_DATA_ROOT: 'C:\\NetConsole-Codex-unsafe',
    }, 'C:\\Temp')).toThrow('unexpected Codex temporary data root')
  })
})
