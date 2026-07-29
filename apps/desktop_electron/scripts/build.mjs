import { execFile } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

import { build } from 'esbuild'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const outputRoot = resolve(appRoot, 'dist')
const execFileAsync = promisify(execFile)

if (!outputRoot.startsWith(`${appRoot}${process.platform === 'win32' ? '\\' : '/'}`)) {
  throw new Error('Refusing to clean a build directory outside desktop_electron')
}

await rm(outputRoot, { recursive: true, force: true })
await mkdir(resolve(outputRoot, 'native'), { recursive: true })

const common = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node24',
  external: ['electron'],
  sourcemap: true,
  logLevel: 'info',
}

await Promise.all([
  build({
    ...common,
    entryPoints: [resolve(appRoot, 'src/main/index.ts')],
    outfile: resolve(outputRoot, 'main/index.cjs'),
  }),
  build({
    ...common,
    entryPoints: [resolve(appRoot, 'src/preload/index.ts')],
    outfile: resolve(outputRoot, 'preload/index.cjs'),
  }),
  execFileAsync('go', [
    'build',
    '-trimpath',
    '-ldflags=-s -w -H=windowsgui',
    '-o',
    resolve(outputRoot, 'native/netconsole-elevated-launcher.exe'),
    resolve(appRoot, 'native/elevated-launcher/main_windows.go'),
  ], {
    cwd: appRoot,
    env: { ...process.env, CGO_ENABLED: '0', GOOS: 'windows', GOARCH: 'amd64' },
    windowsHide: true,
  }),
])
