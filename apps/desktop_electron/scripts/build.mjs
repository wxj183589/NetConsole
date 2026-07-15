import { rm } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { build } from 'esbuild'

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const outputRoot = resolve(appRoot, 'dist')

if (!outputRoot.startsWith(`${appRoot}${process.platform === 'win32' ? '\\' : '/'}`)) {
  throw new Error('Refusing to clean a build directory outside desktop_electron')
}

await rm(outputRoot, { recursive: true, force: true })

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
])
