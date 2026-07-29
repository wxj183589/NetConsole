import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const mainSource = readFileSync(resolve(root, 'src/main/elevated-tool-launcher.ts'), 'utf8')
const helperSource = readFileSync(resolve(root, 'native/elevated-launcher/main_windows.go'), 'utf8')

describe('elevated external tool launcher contract', () => {
  it('uses only the fixed helper with shell disabled and structured stdin', () => {
    expect(mainSource).toContain("spawn(helperPath, [], {")
    expect(mainSource).toContain('shell: false')
    expect(mainSource).toContain("stdio: ['pipe', 'ignore', 'ignore']")
    expect(mainSource).not.toMatch(/\bexec(?:Sync)?\s*\(/)
    expect(mainSource).not.toContain('shell: true')
    expect(mainSource.toLowerCase()).not.toContain('powershell')
    expect(mainSource.toLowerCase()).not.toContain('cmd /c')
  })

  it('calls ShellExecuteExW with runas and a dedicated UAC cancellation code', () => {
    expect(helperSource).toContain('ShellExecuteExW')
    expect(helperSource).toContain('UTF16PtrFromString("runas")')
    expect(helperSource).toContain('errorCancelled')
    expect(helperSource).toContain('elevationCancelledExitCode')
    expect(helperSource.toLowerCase()).not.toContain('powershell')
    expect(helperSource.toLowerCase()).not.toContain('cmd /c')
  })
})
