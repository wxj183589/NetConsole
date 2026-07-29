import { promises as fs } from 'node:fs'
import { spawn } from 'node:child_process'
import { extname, win32 } from 'node:path'

import type { ElevatedToolLaunchRequest } from './external-tool-service'

const ELEVATION_CANCELLED_EXIT_CODE = 23

export async function launchExternalToolElevated(
  helperPath: string,
  request: ElevatedToolLaunchRequest,
): Promise<'launched' | 'cancelled'> {
  await validateHelper(helperPath)
  validateRequest(request)
  const payload = JSON.stringify({
    version: 1,
    executable_path: win32.normalize(request.executablePath),
    arguments: [...request.arguments],
    working_directory: win32.normalize(request.workingDirectory),
  })
  const exitCode = await runHelper(helperPath, payload)
  if (exitCode === 0) return 'launched'
  if (exitCode === ELEVATION_CANCELLED_EXIT_CODE) return 'cancelled'
  throw Object.assign(new Error('elevated launcher failed'), { code: `ELEVATED_HELPER_EXIT_${exitCode}` })
}

async function validateHelper(helperPath: string): Promise<void> {
  if (!win32.isAbsolute(helperPath) || extname(helperPath).toLowerCase() !== '.exe') {
    throw new TypeError('elevated launcher path is invalid')
  }
  const link = await fs.lstat(helperPath)
  const stat = await fs.stat(helperPath)
  if (link.isSymbolicLink() || !stat.isFile()) throw new TypeError('elevated launcher is invalid')
}

function validateRequest(request: ElevatedToolLaunchRequest): void {
  if (
    !win32.isAbsolute(request.executablePath)
    || extname(request.executablePath).toLowerCase() !== '.exe'
    || !win32.isAbsolute(request.workingDirectory)
    || request.arguments.length > 64
    || request.arguments.some((item) => (
      item.length > 2_000
      || /[\u0000\r\n]/.test(item)
      || /(?:&&|\|\||[|<>])/.test(item)
    ))
  ) {
    throw new TypeError('elevated launch request is invalid')
  }
}

function runHelper(helperPath: string, payload: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawn(helperPath, [], {
      shell: false,
      windowsHide: true,
      stdio: ['pipe', 'ignore', 'ignore'],
    })
    child.once('error', reject)
    child.once('close', (code) => resolve(code ?? -1))
    child.stdin.once('error', reject)
    child.stdin.end(payload, 'utf8')
  })
}
