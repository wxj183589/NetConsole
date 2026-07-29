import { EventEmitter } from 'node:events'
import { promises as fs } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ExternalToolStore,
  ExternalToolStoreError,
  OTHER_TOOLS_CATEGORY_ID,
  windowsPathKey,
} from '../src/main/external-tool-store'
import { ExternalToolService } from '../src/main/external-tool-service'
import type { ExternalToolCreateRequest } from '../src/shared/bridge'

const roots: string[] = []

async function fixture() {
  const root = join(tmpdir(), 'netconsole-external-tools-tests', `${Date.now()}-${Math.random().toString(16).slice(2)}`)
  roots.push(root)
  await fs.mkdir(root, { recursive: true })
  const executable = join(root, 'Tools', 'IPOP.EXE')
  await fs.mkdir(join(root, 'Tools'), { recursive: true })
  await fs.writeFile(executable, 'test executable')
  const icon = join(root, 'icon.png')
  await fs.writeFile(icon, 'test icon')
  const store = new ExternalToolStore(root)
  const snapshot = await store.list()
  const request: ExternalToolCreateRequest = {
    name: 'IPOP',
    executablePath: executable,
    arguments: ['--profile', '现场'],
    workingDirectory: join(root, 'Tools'),
    categoryId: OTHER_TOOLS_CATEGORY_ID,
    favorite: false,
    iconMode: 'auto',
  }
  return { root, executable, icon, store, snapshot, request }
}

afterEach(async () => {
  for (const root of roots.splice(0)) await fs.rm(root, { recursive: true, force: true })
})

describe('ExternalToolStore', () => {
  it('initializes the five default categories and writes schema version 1', async () => {
    const { store, snapshot } = await fixture()
    expect(snapshot.schema_version).toBe(1)
    expect(snapshot.categories.map((item) => item.name)).toEqual([
      '网络工具', '终端工具', '分析工具', '厂商工具', '其他工具',
    ])
    expect(JSON.parse(await fs.readFile(store.path, 'utf8')).schema_version).toBe(1)
  })

  it('creates, updates, favorites and deletes a tool without deleting the executable', async () => {
    const { store, request, executable } = await fixture()
    const created = await store.create(request)
    expect(created.executable_path).toBe(executable)
    expect((await store.setFavorite(created.id, true)).favorite).toBe(true)
    const updated = await store.update({ ...request, id: created.id, name: 'IPOP 维护版' })
    expect(updated.name).toBe('IPOP 维护版')
    await store.delete(created.id)
    await expect(fs.stat(executable)).resolves.toBeDefined()
    expect((await store.list()).tools).toEqual([])
  })

  it('compares normalized Windows paths without case sensitivity', async () => {
    const { store, request, executable } = await fixture()
    await store.create(request)
    expect(windowsPathKey(`${executable.replaceAll('\\', '/')}\\`)).toBe(windowsPathKey(executable))
    await expect(store.create({ ...request, executablePath: executable.toUpperCase() }))
      .rejects.toMatchObject({ code: 'DUPLICATE_PATH' })
  })

  it('serializes concurrent mutations without losing data', async () => {
    const { store, request } = await fixture()
    const created = await store.create(request)
    await Promise.all([
      store.setFavorite(created.id, true),
      store.createCategory('现场工具'),
      store.recordLaunch(created.id),
    ])
    const snapshot = await store.list()
    expect(snapshot.tools[0]).toMatchObject({ favorite: true, launch_count: 1 })
    expect(snapshot.categories.some((item) => item.name === '现场工具')).toBe(true)
    expect((await fs.readdir(join(store.path, '..'))).some((name) => name.includes('.tmp-'))).toBe(false)
  })

  it('supports category rename, reorder and controlled deletion with reassignment', async () => {
    const { store, request } = await fixture()
    const category = await store.createCategory('临时分类')
    const tool = await store.create({ ...request, categoryId: category.id })
    await store.renameCategory(category.id, '现场分类')
    await expect(store.deleteCategory(category.id, false)).rejects.toBeInstanceOf(ExternalToolStoreError)
    await store.deleteCategory(category.id, true)
    expect((await store.get(tool.id))?.category_id).toBe(OTHER_TOOLS_CATEGORY_ID)
    const ids = (await store.list()).categories.map((item) => item.id).reverse()
    await store.reorderCategories(ids)
    expect((await store.list()).categories.sort((a, b) => a.sort_order - b.sort_order).map((item) => item.id)).toEqual(ids)
  })

  it('copies custom icons into userData and removes the cache on delete', async () => {
    const { store, request, icon } = await fixture()
    const tool = await store.create({ ...request, iconMode: 'custom' }, icon)
    expect(tool.custom_icon_path).toContain(join('external-tools', 'icons'))
    await expect(fs.stat(tool.custom_icon_path!)).resolves.toBeDefined()
    await store.delete(tool.id)
    await expect(fs.stat(tool.custom_icon_path!)).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('preserves a diagnostic copy and recovers defaults from damaged or unsupported JSON', async () => {
    const first = await fixture()
    await fs.writeFile(first.store.path, '{broken', 'utf8')
    const logger = vi.fn()
    const recovered = new ExternalToolStore(first.root, logger)
    expect((await recovered.list()).categories).toHaveLength(5)
    expect(logger).toHaveBeenCalledWith('ELECTRON_EXTERNAL_TOOL_STORE_RECOVERED', expect.any(String))
    expect((await fs.readdir(first.root)).some((name) => name.startsWith('external-tools.json.corrupt-'))).toBe(true)

    await fs.writeFile(first.store.path, JSON.stringify({ schema_version: 99, categories: [], tools: [] }), 'utf8')
    expect((await new ExternalToolStore(first.root).list()).schema_version).toBe(1)
  })
})

describe('ExternalToolService launcher', () => {
  it('spawns only the stored executable and argv with shell disabled, then records success', async () => {
    const { store, request } = await fixture()
    const tool = await store.create(request)
    const child = Object.assign(new EventEmitter(), { unref: vi.fn() })
    const spawn = vi.fn(() => {
      queueMicrotask(() => child.emit('spawn'))
      return child
    })
    const service = new ExternalToolService({
      store,
      spawn,
      reveal: vi.fn(),
      getExecutableIcon: vi.fn(async () => null),
      getCustomIcon: vi.fn(async () => null),
    })

    await expect(service.launch(tool.id)).resolves.toEqual({ success: true, toolId: tool.id })
    expect(spawn).toHaveBeenCalledWith(tool.executable_path, tool.arguments, {
      shell: false,
      detached: true,
      stdio: 'ignore',
      cwd: tool.working_directory,
      windowsHide: false,
    })
    expect(child.unref).toHaveBeenCalledOnce()
    expect((await store.get(tool.id))?.launch_count).toBe(1)
  })

  it('does not increment launch count when spawn fails', async () => {
    const { store, request } = await fixture()
    const tool = await store.create(request)
    const child = Object.assign(new EventEmitter(), { unref: vi.fn() })
    const service = new ExternalToolService({
      store,
      spawn: () => {
        queueMicrotask(() => {
          child.emit('error', Object.assign(new Error('denied'), { code: 'EACCES' }))
        })
        return child
      },
      reveal: vi.fn(),
      getExecutableIcon: vi.fn(async () => null),
      getCustomIcon: vi.fn(async () => null),
    })
    await expect(service.launch(tool.id)).resolves.toMatchObject({ success: false, error: '没有权限启动该程序。' })
    expect((await store.get(tool.id))?.launch_count).toBe(0)
    expect(child.unref).not.toHaveBeenCalled()
  })
})
