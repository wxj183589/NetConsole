import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { describe, expect, it } from 'vitest'
import { validateDroppedFilePaths } from '../src/main/sftp-drop'
import { validateUiPreferenceKey, validateUiPreferenceValue } from '../src/shared/validation'

describe('SFTP authorized local inputs', () => {
  it('accepts regular selected files and rejects a directory junction escape', async () => {
    const root = await mkdtemp(resolve(tmpdir(), 'sftp-drop-'))
    try {
      const actual = resolve(root, 'actual')
      const redirected = resolve(root, 'redirected')
      await mkdir(actual)
      await writeFile(resolve(actual, '中文.cfg'), 'data')
      await validateDroppedFilePaths([resolve(actual, '中文.cfg')])
      await symlink(actual, redirected, process.platform === 'win32' ? 'junction' : 'dir')
      await expect(validateDroppedFilePaths([resolve(redirected, '中文.cfg')])).rejects.toThrow()
      await expect(validateDroppedFilePaths(['../arbitrary'])).rejects.toThrow()
      await expect(validateDroppedFilePaths([actual])).rejects.toThrow()
    } finally { await rm(root, { recursive: true, force: true }) }
  })
  it('keeps the remembered download path private to Main', () => {
    expect(() => validateUiPreferenceKey('console.sftp-download-directory')).toThrow()
    expect(() => validateUiPreferenceValue('console.sftp-download-directory', 'D:/arbitrary')).toThrow()
    expect(validateUiPreferenceValue('console.layout', { collapsed: true, sidebarWidth: 270, sftpWidth: 430 })).toEqual({ collapsed: true, sidebarWidth: 270, sftpWidth: 430 })
  })
})
