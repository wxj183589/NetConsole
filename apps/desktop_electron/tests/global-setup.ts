import { mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export default function setup(): () => void {
  const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
  const testBase = resolve(repositoryRoot, '..', 'test-data', 'NetConsole')
  process.env.NETCONSOLE_PROJECT_ROOT = repositoryRoot
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
