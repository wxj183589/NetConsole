import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const projectRoot = fileURLToPath(new URL('../..', import.meta.url))
const versionSource = readFileSync(resolve(projectRoot, 'src/netconsole/core/version.py'), 'utf8')
const appVersion = versionSource.match(/^APP_VERSION\s*=\s*["']([^"']+)["']/m)?.[1]
const navigationSchemaVersion = 1

if (!appVersion) throw new Error('无法从 src/netconsole/core/version.py 读取 APP_VERSION')

function gitOutput(args: string[]): string {
  return execFileSync('git', ['-C', projectRoot, ...args], { encoding: 'utf8' }).trim()
}

function currentGitCommit(): string {
  const override = process.env.NETCONSOLE_FRONTEND_GIT_COMMIT?.trim()
  if (override) return override
  try {
    const revision = gitOutput(['rev-parse', '--short=8', 'HEAD'])
    const dirty = gitOutput(['status', '--porcelain', '--untracked-files=normal'])
    return dirty ? `${revision}-dirty` : revision
  } catch {
    return 'unknown'
  }
}

function webBuildMetaPlugin() {
  return {
    name: 'netconsole-web-build-meta',
    closeBundle() {
      const gitCommit = currentGitCommit()
      const metadata = {
        app_version: appVersion,
        git_commit: gitCommit,
        build_time: new Date().toISOString(),
        navigation_schema_version: navigationSchemaVersion,
        build_id: `${appVersion}+${gitCommit}`,
      }
      writeFileSync(
        resolve(projectRoot, 'apps/web/dist/web-build-meta.json'),
        `${JSON.stringify(metadata, null, 2)}\n`,
        'utf8',
      )
    },
  }
}

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
    webBuildMetaPlugin(),
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
