import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, resolve, sep } from 'node:path'

const CODEX_TEMP_PREFIX = 'NetConsole-Codex-'

export function resolveCodexTemporaryDataRoot(
  environment: NodeJS.ProcessEnv = process.env,
  systemTempRoot = tmpdir(),
): string | undefined {
  if (environment.NETCONSOLE_DEV_TEMP_DATA_ROOT !== '1') return undefined
  const value = environment.NETCONSOLE_DATA_ROOT?.trim()
  if (!value) throw new Error('Codex temporary data root is missing')
  return validateCodexTemporaryDataRoot(value, systemTempRoot)
}

export function cleanupCodexTemporaryDataRoot(
  value: string,
  systemTempRoot = tmpdir(),
): void {
  const target = validateCodexTemporaryDataRoot(value, systemTempRoot)
  rmSync(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
}

function validateCodexTemporaryDataRoot(value: string, systemTempRoot: string): string {
  const target = resolve(value)
  const tempRoot = resolve(systemTempRoot)
  if (
    !target.startsWith(`${tempRoot}${sep}`)
    || !basename(target).startsWith(CODEX_TEMP_PREFIX)
  ) {
    throw new Error('Refusing to use an unexpected Codex temporary data root')
  }
  return target
}
