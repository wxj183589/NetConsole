import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

import { configDefaults, defineConfig } from 'vitest/config'
import type { Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const projectRoot = fileURLToPath(new URL('../..', import.meta.url))
const versionSource = readFileSync(resolve(projectRoot, 'src/netconsole/core/version.py'), 'utf8')
const appVersion = versionSource.match(/^APP_VERSION\s*=\s*["']([^"']+)["']/m)?.[1]
const navigationSchemaVersion = 1
const elementPlusResolver = ElementPlusResolver({ importStyle: process.env.VITEST ? false : 'css' })

function vuePlugin(): Plugin {
  const plugin = vue()
  if (!process.env.VITEST || !plugin.transform || typeof plugin.transform === 'function') return plugin
  const transform = plugin.transform
  plugin.transform = {
    ...transform,
    handler(code, id, options) {
      return transform.handler.call(this, code, id, {
        moduleType: options?.moduleType ?? 'js',
        ...options,
        ssr: false,
      })
    },
  }
  return plugin
}

if (!appVersion) throw new Error('无法从 src/netconsole/core/version.py 读取 APP_VERSION')

function gitOutput(args: string[]): string {
  return execFileSync('git', ['-C', projectRoot, ...args], { encoding: 'utf8' }).trim()
}

interface BuildMetadata {
  app_version: string
  git_commit_full: string
  git_commit_short: string
  build_time_utc: string
  build_dirty: boolean
  build_source: string
  frontend_commit: string
  backend_commit: string
}

function currentBuildMetadata(): BuildMetadata {
  const override = process.env.NETCONSOLE_BUILD_METADATA_JSON?.trim()
  if (override) {
    const metadata = JSON.parse(override) as BuildMetadata
    if (
      metadata.app_version !== appVersion
      || metadata.frontend_commit !== metadata.git_commit_full
      || metadata.backend_commit !== metadata.git_commit_full
      || metadata.git_commit_short !== metadata.git_commit_full.slice(0, 8)
    ) throw new Error('统一构建元数据不一致')
    return metadata
  }
  const revision = gitOutput(['rev-parse', 'HEAD'])
  const dirty = Boolean(gitOutput(['status', '--porcelain', '--untracked-files=normal']))
  return {
    app_version: appVersion!,
    git_commit_full: revision,
    git_commit_short: revision.slice(0, 8),
    build_time_utc: new Date().toISOString(),
    build_dirty: dirty,
    build_source: 'git-development',
    frontend_commit: revision,
    backend_commit: revision,
  }
}

function webBuildMetaPlugin() {
  return {
    name: 'netconsole-web-build-meta',
    closeBundle() {
      const buildMetadata = currentBuildMetadata()
      const buildIdentity = buildMetadata.build_dirty
        ? `${buildMetadata.git_commit_full}-dirty`
        : buildMetadata.git_commit_full
      const metadata = {
        ...buildMetadata,
        git_commit: buildIdentity,
        build_time: buildMetadata.build_time_utc,
        navigation_schema_version: navigationSchemaVersion,
        build_id: `${appVersion}+${buildIdentity}`,
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
  test: {
    exclude: [...configDefaults.exclude, 'tests/visual/e2e/**'],
    server: { deps: { inline: ['element-plus', '@element-plus/icons-vue'] } },
  },
  plugins: [
    vuePlugin(),
    AutoImport({
      resolvers: [elementPlusResolver],
      dts: false,
    }),
    Components({
      resolvers: [elementPlusResolver],
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
