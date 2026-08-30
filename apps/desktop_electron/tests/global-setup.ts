import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { join } from 'node:path'

export default function setup(): () => void {
  const testBase = 'D:\\study\\NetConsole-Workspace\\test-data\\NetConsole'
  mkdirSync(testBase, { recursive: true })
  const testRoot = mkdtempSync(join(testBase, 'electron-vitest-'))
  process.env.TEMP = testRoot
  process.env.TMP = testRoot
  process.env.NETCONSOLE_RUNTIME_MODE = 'test'
  process.env.NETCONSOLE_STORAGE_MODE = 'isolated_test'
  process.env.NETCONSOLE_DATA_ROOT = testRoot
  return () => {
    rmSync(testRoot, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
  }
}
