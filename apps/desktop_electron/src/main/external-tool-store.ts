import { randomUUID } from 'node:crypto'
import { promises as fs } from 'node:fs'
import { basename, dirname, extname, join, win32 } from 'node:path'

import type {
  ExternalToolCategory,
  ExternalToolCreateRequest,
  ExternalToolIconMode,
  ExternalToolLaunchMode,
  ExternalToolRecord,
  ExternalToolSystemSettingKey,
  ExternalToolUpdateRequest,
} from '../shared/bridge'

export const EXTERNAL_TOOL_SCHEMA_VERSION = 2
export const EXTERNAL_TOOL_MAX_ICON_BYTES = 5 * 1024 * 1024
export const OTHER_TOOLS_CATEGORY_ID = 'e5057ec4-03c5-4c17-b24d-b8111ee8f942'
const EXTERNAL_TOOL_STORE_MAX_BYTES = 4 * 1024 * 1024
const EXTERNAL_TOOL_MAX_CATEGORIES = 200
const EXTERNAL_TOOL_MAX_RECORDS = 2_000

const DEFAULT_CATEGORIES: readonly ExternalToolCategory[] = [
  { id: '38a94eef-e708-4144-8be4-a7f9e519b216', name: '网络工具', sort_order: 10, builtin: true },
  { id: '5efeea9e-b3e9-44f4-9ba6-f3f6871f2a52', name: '终端工具', sort_order: 20, builtin: true },
  { id: 'b0889d74-7b5c-41e8-9e90-d50fbfa9f5f0', name: '分析工具', sort_order: 30, builtin: true },
  { id: '36cf418e-6438-43b5-a35c-d738e6f1c9dc', name: '厂商工具', sort_order: 40, builtin: true },
  { id: OTHER_TOOLS_CATEGORY_ID, name: '其他工具', sort_order: 50, builtin: true },
]

interface ExternalToolState {
  schema_version: typeof EXTERNAL_TOOL_SCHEMA_VERSION
  categories: ExternalToolCategory[]
  tools: ExternalToolRecord[]
  migrations: {
    legacy_ipop_v1: boolean
  }
}

type StoreLogger = (event: string, detail?: string) => void

export interface ExternalToolStoreSnapshot {
  schema_version: 2
  categories: ExternalToolCategory[]
  tools: ExternalToolRecord[]
  migrations: {
    legacy_ipop_v1: boolean
  }
}

export class ExternalToolStore {
  readonly path: string
  readonly iconsPath: string
  private state: ExternalToolState | undefined
  private operationQueue: Promise<unknown> = Promise.resolve()

  constructor(
    userDataPath: string,
    private readonly logger: StoreLogger = () => undefined,
  ) {
    if (!win32.isAbsolute(userDataPath)) throw new TypeError('userDataPath must be absolute')
    this.path = join(userDataPath, 'external-tools.json')
    this.iconsPath = join(userDataPath, 'external-tools', 'icons')
  }

  async list(): Promise<ExternalToolStoreSnapshot> {
    await this.enqueue(async () => { await this.ensureLoaded() })
    return cloneState(this.requireState())
  }

  async get(toolId: string): Promise<ExternalToolRecord | undefined> {
    await this.enqueue(async () => { await this.ensureLoaded() })
    const record = this.requireState().tools.find((tool) => tool.id === toolId)
    return record ? cloneTool(record) : undefined
  }

  async create(
    request: ExternalToolCreateRequest,
    customIconSourcePath?: string,
  ): Promise<ExternalToolRecord> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      await assertExecutable(request.executablePath)
      const executablePath = normalizeWindowsPath(request.executablePath)
      const duplicate = state.tools.find(
        (tool) => tool.executable_path !== null
          && windowsPathKey(tool.executable_path) === windowsPathKey(executablePath),
      )
      if (duplicate) throw new ExternalToolStoreError('DUPLICATE_PATH', `该程序已经添加为「${duplicate.name}」。`, duplicate.id)
      const category = requireCategory(state, request.categoryId)
      const now = new Date().toISOString()
      const id = randomUUID()
      const workingDirectory = normalizeWindowsPath(
        request.workingDirectory || win32.dirname(executablePath),
      )
      await assertDirectory(workingDirectory)
      const customIconPath = await this.resolveCustomIcon(
        id,
        request.iconMode,
        customIconSourcePath,
      )
      const record: ExternalToolRecord = {
        id,
        name: request.name,
        source_type: 'independent',
        source_key: null,
        executable_path: executablePath,
        arguments: [...request.arguments],
        working_directory: workingDirectory,
        category_id: category.id,
        favorite: request.favorite,
        sort_order: nextToolOrder(state, category.id),
        icon_mode: request.iconMode,
        custom_icon_path: customIconPath,
        launch_privilege: request.launchPrivilege,
        launch_count: 0,
        administrator_launch_count: 0,
        last_launched_at: null,
        last_launch_mode: null,
        created_at: now,
        updated_at: now,
      }
      state.tools.push(record)
      try {
        await this.writeState()
      } catch (cause) {
        state.tools.pop()
        if (customIconPath) await fs.unlink(customIconPath).catch(() => undefined)
        throw cause
      }
      return cloneTool(record)
    })
  }

  async createSystemReference(sourceKey: ExternalToolSystemSettingKey): Promise<ExternalToolRecord> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      const duplicate = state.tools.find(
        (tool) => tool.source_type === 'system_setting' && tool.source_key === sourceKey,
      )
      if (duplicate) {
        throw new ExternalToolStoreError(
          'DUPLICATE_SOURCE',
          `系统已配置工具「${duplicate.name}」已在工具集中。`,
          duplicate.id,
        )
      }
      const category = state.categories.find((item) => item.name === '终端工具')
      if (!category) throw new ExternalToolStoreError('NOT_FOUND', '“终端工具”分类不存在。')
      const now = new Date().toISOString()
      const record: ExternalToolRecord = {
        id: randomUUID(),
        name: systemSettingToolName(sourceKey),
        source_type: 'system_setting',
        source_key: sourceKey,
        executable_path: null,
        arguments: [],
        working_directory: null,
        category_id: category.id,
        favorite: true,
        sort_order: nextToolOrder(state, category.id),
        icon_mode: 'auto',
        custom_icon_path: null,
        launch_privilege: 'normal',
        launch_count: 0,
        administrator_launch_count: 0,
        last_launched_at: null,
        last_launch_mode: null,
        created_at: now,
        updated_at: now,
      }
      state.tools.push(record)
      await this.writeWithRollback(before)
      return cloneTool(record)
    })
  }

  async migrateLegacyIpop(path: string): Promise<void> {
    await this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      if (state.migrations.legacy_ipop_v1) return
      const before = cloneState(state)
      const candidate = path.trim()
      if (!candidate) {
        state.migrations.legacy_ipop_v1 = true
        await this.writeWithRollback(before)
        return
      }
      await assertExecutable(candidate)
      const executablePath = normalizeWindowsPath(candidate)
      if (basename(executablePath).toLocaleLowerCase('en-US') !== 'ipop.exe') {
        throw new ExternalToolStoreError('INVALID_REQUEST', '旧 IPOP 路径不是 IPOP.EXE。')
      }
      const duplicate = state.tools.find(
        (tool) => tool.executable_path !== null
          && windowsPathKey(tool.executable_path) === windowsPathKey(executablePath),
      )
      if (!duplicate) {
        const category = state.categories.find((item) => item.name === '网络工具')
        if (!category) throw new ExternalToolStoreError('NOT_FOUND', '“网络工具”分类不存在。')
        const now = new Date().toISOString()
        state.tools.push({
          id: randomUUID(),
          name: 'IPOP',
          source_type: 'independent',
          source_key: null,
          executable_path: executablePath,
          arguments: [],
          working_directory: win32.dirname(executablePath),
          category_id: category.id,
          favorite: true,
          sort_order: nextToolOrder(state, category.id),
          icon_mode: 'auto',
          custom_icon_path: null,
          launch_privilege: 'normal',
          launch_count: 0,
          administrator_launch_count: 0,
          last_launched_at: null,
          last_launch_mode: null,
          created_at: now,
          updated_at: now,
        })
      }
      state.migrations.legacy_ipop_v1 = true
      await this.writeWithRollback(before)
    })
  }

  async update(
    request: ExternalToolUpdateRequest,
    customIconSourcePath?: string,
  ): Promise<ExternalToolRecord> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const existing = requireTool(state, request.id)
      requireCategory(state, request.categoryId)
      let executablePath = existing.executable_path
      let workingDirectory = existing.working_directory
      let arguments_ = [...request.arguments]
      if (existing.source_type === 'independent') {
        if (!request.executablePath) {
          throw new ExternalToolStoreError('INVALID_REQUEST', '请选择程序。')
        }
        await assertExecutable(request.executablePath)
        executablePath = normalizeWindowsPath(request.executablePath)
        const duplicate = state.tools.find(
          (tool) => tool.id !== existing.id
            && tool.executable_path !== null
            && windowsPathKey(tool.executable_path) === windowsPathKey(executablePath as string),
        )
        if (duplicate) {
          throw new ExternalToolStoreError(
            'DUPLICATE_PATH',
            `该程序已经添加为「${duplicate.name}」。`,
            duplicate.id,
          )
        }
        workingDirectory = normalizeWindowsPath(
          request.workingDirectory || win32.dirname(executablePath),
        )
        await assertDirectory(workingDirectory)
      } else {
        if (request.executablePath !== undefined || request.workingDirectory !== undefined || request.arguments.length) {
          throw new ExternalToolStoreError('INVALID_REQUEST', '系统设置引用的路径、参数和工作目录不能在工具集中修改。')
        }
        executablePath = null
        workingDirectory = null
        arguments_ = []
      }
      const oldIconPath = existing.custom_icon_path
      let customIconPath = oldIconPath
      if (request.iconMode === 'custom' && customIconSourcePath) {
        customIconPath = await this.copyCustomIcon(existing.id, customIconSourcePath)
      } else if (request.iconMode !== 'custom') {
        customIconPath = null
      } else if (!customIconPath) {
        throw new ExternalToolStoreError('INVALID_REQUEST', '请选择自定义图标。')
      }
      const changedCategory = existing.category_id !== request.categoryId
      const previous = cloneTool(existing)
      Object.assign(existing, {
        name: request.name,
        executable_path: executablePath,
        arguments: arguments_,
        working_directory: workingDirectory,
        category_id: request.categoryId,
        favorite: request.favorite,
        sort_order: changedCategory ? nextToolOrder(state, request.categoryId) : existing.sort_order,
        icon_mode: request.iconMode,
        custom_icon_path: customIconPath,
        launch_privilege: request.launchPrivilege,
        updated_at: new Date().toISOString(),
      })
      try {
        await this.writeState()
      } catch (cause) {
        Object.assign(existing, previous)
        if (customIconPath && customIconPath !== oldIconPath) await fs.unlink(customIconPath).catch(() => undefined)
        throw cause
      }
      if (oldIconPath && oldIconPath !== customIconPath) await fs.unlink(oldIconPath).catch(() => undefined)
      return cloneTool(existing)
    })
  }

  async delete(toolId: string): Promise<void> {
    await this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      const index = state.tools.findIndex((tool) => tool.id === toolId)
      if (index < 0) throw new ExternalToolStoreError('NOT_FOUND', '工具记录不存在。')
      const [removed] = state.tools.splice(index, 1)
      await this.writeWithRollback(before)
      if (removed.custom_icon_path) await fs.unlink(removed.custom_icon_path).catch(() => undefined)
    })
  }

  async setFavorite(toolId: string, favorite: boolean): Promise<ExternalToolRecord> {
    return this.mutateTool(toolId, (tool) => {
      tool.favorite = favorite
      tool.updated_at = new Date().toISOString()
    })
  }

  async recordLaunch(toolId: string, launchMode: ExternalToolLaunchMode): Promise<ExternalToolRecord> {
    return this.mutateTool(toolId, (tool) => {
      tool.launch_count += 1
      if (launchMode === 'administrator') tool.administrator_launch_count += 1
      tool.last_launched_at = new Date().toISOString()
      tool.last_launch_mode = launchMode
      tool.updated_at = tool.last_launched_at
    })
  }

  async createCategory(name: string): Promise<ExternalToolCategory> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      assertUniqueCategoryName(state, name)
      const category: ExternalToolCategory = {
        id: randomUUID(),
        name,
        sort_order: Math.max(0, ...state.categories.map((item) => item.sort_order)) + 10,
        builtin: false,
      }
      state.categories.push(category)
      await this.writeWithRollback(before)
      return { ...category }
    })
  }

  async renameCategory(categoryId: string, name: string): Promise<ExternalToolCategory> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      const category = requireCategory(state, categoryId)
      assertUniqueCategoryName(state, name, categoryId)
      category.name = name
      await this.writeWithRollback(before)
      return { ...category }
    })
  }

  async deleteCategory(categoryId: string, moveToolsToOther: boolean): Promise<void> {
    await this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      if (categoryId === OTHER_TOOLS_CATEGORY_ID) {
        throw new ExternalToolStoreError('INVALID_REQUEST', '“其他工具”分类不能删除。')
      }
      const index = state.categories.findIndex((category) => category.id === categoryId)
      if (index < 0) throw new ExternalToolStoreError('NOT_FOUND', '分类不存在。')
      const tools = state.tools.filter((tool) => tool.category_id === categoryId)
      if (tools.length && !moveToolsToOther) {
        throw new ExternalToolStoreError('INVALID_REQUEST', '分类中仍有工具，请先选择移动到“其他工具”。')
      }
      if (tools.length) {
        for (const tool of tools) {
          tool.category_id = OTHER_TOOLS_CATEGORY_ID
          tool.sort_order = nextToolOrder(state, OTHER_TOOLS_CATEGORY_ID)
          tool.updated_at = new Date().toISOString()
        }
      }
      state.categories.splice(index, 1)
      await this.writeWithRollback(before)
    })
  }

  async reorderCategories(categoryIds: string[]): Promise<void> {
    await this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      assertSameIds(categoryIds, state.categories.map((item) => item.id), '分类排序')
      for (const [index, id] of categoryIds.entries()) requireCategory(state, id).sort_order = (index + 1) * 10
      await this.writeWithRollback(before)
    })
  }

  async reorderTools(categoryId: string, toolIds: string[]): Promise<void> {
    await this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      requireCategory(state, categoryId)
      const currentIds = state.tools.filter((tool) => tool.category_id === categoryId).map((tool) => tool.id)
      assertSameIds(toolIds, currentIds, '工具排序')
      for (const [index, id] of toolIds.entries()) requireTool(state, id).sort_order = (index + 1) * 10
      await this.writeWithRollback(before)
    })
  }

  private async mutateTool(
    toolId: string,
    mutation: (tool: ExternalToolRecord) => void,
  ): Promise<ExternalToolRecord> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const before = cloneState(state)
      const tool = requireTool(state, toolId)
      mutation(tool)
      await this.writeWithRollback(before)
      return cloneTool(tool)
    })
  }

  private async ensureLoaded(): Promise<void> {
    if (this.state) return
    let loaded: { state: ExternalToolState; upgraded: boolean }
    try {
      const stat = await fs.stat(this.path)
      if (!stat.isFile() || stat.size > EXTERNAL_TOOL_STORE_MAX_BYTES) {
        throw new TypeError('external tool store file is invalid')
      }
      const raw = await fs.readFile(this.path, 'utf8')
      loaded = validatePersistedState(JSON.parse(raw), this.iconsPath)
    } catch (cause) {
      if (isMissingFile(cause)) {
        this.state = defaultState()
        await this.writeState()
        return
      }
      await this.recoverDamagedFile(cause)
      return
    }
    this.state = loaded.state
    if (loaded.upgraded) await this.writeState()
  }

  private async recoverDamagedFile(cause: unknown): Promise<void> {
    const backup = `${this.path}.corrupt-${Date.now()}`
    await fs.mkdir(dirname(this.path), { recursive: true })
    await fs.copyFile(this.path, backup).catch(() => undefined)
    this.logger('ELECTRON_EXTERNAL_TOOL_STORE_RECOVERED', errorCode(cause))
    this.state = defaultState()
    await this.writeState()
  }

  private async writeState(): Promise<void> {
    const state = this.requireState()
    const temporary = `${this.path}.tmp-${process.pid}-${randomUUID()}`
    await fs.mkdir(dirname(this.path), { recursive: true })
    try {
      await fs.writeFile(temporary, `${JSON.stringify(state, null, 2)}\n`, 'utf8')
      await fs.rename(temporary, this.path)
    } catch (cause) {
      await fs.unlink(temporary).catch(() => undefined)
      this.logger('ELECTRON_EXTERNAL_TOOL_STORE_WRITE_FAILED', errorCode(cause))
      throw new ExternalToolStoreError('PERSISTENCE_FAILED', '工具集配置保存失败，请检查磁盘权限后重试。')
    }
  }

  private async writeWithRollback(before: ExternalToolStoreSnapshot): Promise<void> {
    try {
      await this.writeState()
    } catch (cause) {
      this.state = cloneState(before)
      throw cause
    }
  }

  private async resolveCustomIcon(
    toolId: string,
    iconMode: ExternalToolIconMode,
    sourcePath?: string,
  ): Promise<string | null> {
    if (iconMode !== 'custom') return null
    if (!sourcePath) throw new ExternalToolStoreError('INVALID_REQUEST', '请选择自定义图标。')
    return this.copyCustomIcon(toolId, sourcePath)
  }

  private async copyCustomIcon(toolId: string, sourcePath: string): Promise<string> {
    const extension = extname(sourcePath).toLowerCase()
    if (!['.png', '.jpg', '.jpeg', '.ico'].includes(extension)) {
      throw new ExternalToolStoreError('INVALID_REQUEST', '自定义图标仅支持 PNG、JPG、JPEG 或 ICO。')
    }
    const source = await fs.stat(sourcePath)
    if (!source.isFile() || source.size > EXTERNAL_TOOL_MAX_ICON_BYTES) {
      throw new ExternalToolStoreError('INVALID_REQUEST', '自定义图标无效或超过 5 MB。')
    }
    await fs.mkdir(this.iconsPath, { recursive: true })
    const target = join(this.iconsPath, `${toolId}${extension}`)
    const temporary = `${target}.tmp-${randomUUID()}`
    await fs.copyFile(sourcePath, temporary)
    await fs.rename(temporary, target).catch(async (cause) => {
      await fs.unlink(temporary).catch(() => undefined)
      throw cause
    })
    return target
  }

  private requireState(): ExternalToolState {
    if (!this.state) throw new Error('external tool store is not loaded')
    return this.state
  }

  private enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.operationQueue.catch(() => undefined).then(operation)
    this.operationQueue = result
    return result
  }
}

export class ExternalToolStoreError extends Error {
  constructor(
    readonly code: 'DUPLICATE_PATH' | 'DUPLICATE_SOURCE' | 'INVALID_REQUEST' | 'NOT_FOUND' | 'PERSISTENCE_FAILED',
    message: string,
    readonly existingToolId?: string,
  ) {
    super(message)
  }
}

export function normalizeWindowsPath(value: string): string {
  const normalized = win32.normalize(value.trim())
  if (!win32.isAbsolute(normalized)) throw new TypeError('path must be an absolute Windows path')
  return normalized
}

export function windowsPathKey(value: string): string {
  return normalizeWindowsPath(value).replace(/[\\/]+$/, '').toLocaleLowerCase('en-US')
}

async function assertExecutable(value: string): Promise<void> {
  const path = normalizeWindowsPath(value)
  if (extname(path).toLowerCase() !== '.exe') throw new ExternalToolStoreError('INVALID_REQUEST', '仅支持 Windows .exe 程序。')
  try {
    if ((await fs.lstat(path)).isSymbolicLink()) throw new Error('symbolic-link')
    const stat = await fs.stat(path)
    if (!stat.isFile()) throw new Error('not-file')
  } catch {
    throw new ExternalToolStoreError('INVALID_REQUEST', '程序文件不存在或不是普通文件。')
  }
}

async function assertDirectory(value: string): Promise<void> {
  try {
    if (!(await fs.stat(value)).isDirectory()) throw new Error('not-directory')
  } catch {
    throw new ExternalToolStoreError('INVALID_REQUEST', '工作目录不存在。')
  }
}

function nextToolOrder(state: ExternalToolState, categoryId: string): number {
  return Math.max(0, ...state.tools.filter((tool) => tool.category_id === categoryId).map((tool) => tool.sort_order)) + 10
}

function requireCategory(state: ExternalToolState, categoryId: string): ExternalToolCategory {
  const category = state.categories.find((item) => item.id === categoryId)
  if (!category) throw new ExternalToolStoreError('NOT_FOUND', '分类不存在。')
  return category
}

function requireTool(state: ExternalToolState, toolId: string): ExternalToolRecord {
  const tool = state.tools.find((item) => item.id === toolId)
  if (!tool) throw new ExternalToolStoreError('NOT_FOUND', '工具记录不存在。')
  return tool
}

function assertUniqueCategoryName(state: ExternalToolState, name: string, exceptId?: string): void {
  if (state.categories.some((item) => item.id !== exceptId && item.name.toLocaleLowerCase() === name.toLocaleLowerCase())) {
    throw new ExternalToolStoreError('INVALID_REQUEST', '分类名称已存在。')
  }
}

function assertSameIds(value: string[], expected: string[], label: string): void {
  if (value.length !== expected.length || value.some((id) => !expected.includes(id))) {
    throw new ExternalToolStoreError('INVALID_REQUEST', `${label}数据已变化，请刷新后重试。`)
  }
}

function defaultState(): ExternalToolState {
  return {
    schema_version: EXTERNAL_TOOL_SCHEMA_VERSION,
    categories: DEFAULT_CATEGORIES.map((category) => ({ ...category })),
    tools: [],
    migrations: { legacy_ipop_v1: false },
  }
}

function cloneState(state: ExternalToolState): ExternalToolStoreSnapshot {
  return {
    schema_version: 2,
    categories: state.categories.map((category) => ({ ...category })),
    tools: state.tools.map(cloneTool),
    migrations: { ...state.migrations },
  }
}

function cloneTool(tool: ExternalToolRecord): ExternalToolRecord {
  return { ...tool, arguments: [...tool.arguments] }
}

function validatePersistedState(
  value: unknown,
  iconsPath: string,
): { state: ExternalToolState; upgraded: boolean } {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('工具集配置无效')
  }
  const schemaVersion = (value as { schema_version?: unknown }).schema_version
  const upgraded = schemaVersion === 1
  const record = strictRecord(
    value,
    upgraded ? ['schema_version', 'categories', 'tools'] : ['schema_version', 'categories', 'tools', 'migrations'],
    '工具集配置',
  )
  if (schemaVersion !== 1 && schemaVersion !== EXTERNAL_TOOL_SCHEMA_VERSION) {
    throw new TypeError('external tool schema version is invalid')
  }
  if (!Array.isArray(record.categories) || !Array.isArray(record.tools)) throw new TypeError('external tool collections are invalid')
  if (record.categories.length > EXTERNAL_TOOL_MAX_CATEGORIES || record.tools.length > EXTERNAL_TOOL_MAX_RECORDS) {
    throw new TypeError('external tool collection limit exceeded')
  }
  const categories = record.categories.map(validateCategory)
  const categoryIds = new Set(categories.map((item) => item.id))
  if (categoryIds.size !== categories.length || !categoryIds.has(OTHER_TOOLS_CATEGORY_ID)) throw new TypeError('external tool category ids are invalid')
  if (new Set(categories.map((item) => item.name.toLocaleLowerCase())).size !== categories.length) {
    throw new TypeError('external tool category names are duplicated')
  }
  const tools = record.tools.map((item) => (
    upgraded
      ? validateLegacyTool(item, categoryIds, iconsPath)
      : validateTool(item, categoryIds, iconsPath)
  ))
  if (new Set(tools.map((item) => item.id)).size !== tools.length) throw new TypeError('external tool ids are duplicated')
  const executablePaths = tools
    .map((item) => item.executable_path)
    .filter((item): item is string => item !== null)
  if (new Set(executablePaths.map(windowsPathKey)).size !== executablePaths.length) {
    throw new TypeError('external tool paths are duplicated')
  }
  const sourceKeys = tools
    .filter((item) => item.source_type === 'system_setting')
    .map((item) => item.source_key)
  if (new Set(sourceKeys).size !== sourceKeys.length) throw new TypeError('external tool sources are duplicated')
  const migrations = upgraded
    ? { legacy_ipop_v1: false }
    : validateMigrations(record.migrations)
  return {
    state: { schema_version: 2, categories, tools, migrations },
    upgraded,
  }
}

function validateCategory(value: unknown): ExternalToolCategory {
  const record = strictRecord(value, ['id', 'name', 'sort_order', 'builtin'], '工具分类')
  if (
    typeof record.id !== 'string'
    || !isUuid(record.id)
    || typeof record.name !== 'string'
    || !record.name.trim()
    || record.name.length > 80
    || /[\u0000-\u001f\u007f]/.test(record.name)
    || !isSafeOrder(record.sort_order)
    || typeof record.builtin !== 'boolean'
  ) throw new TypeError('external tool category is invalid')
  return { id: record.id.toLowerCase(), name: record.name.trim(), sort_order: record.sort_order, builtin: record.builtin }
}

function validateTool(value: unknown, categoryIds: Set<string>, iconsPath: string): ExternalToolRecord {
  const keys: Array<keyof ExternalToolRecord> = [
    'id', 'name', 'source_type', 'source_key', 'executable_path', 'arguments',
    'working_directory', 'category_id', 'favorite', 'sort_order', 'icon_mode',
    'custom_icon_path', 'launch_privilege', 'launch_count',
    'administrator_launch_count', 'last_launched_at', 'last_launch_mode',
    'created_at', 'updated_at',
  ]
  const record = strictRecord(value, keys, '工具记录')
  const independent = record.source_type === 'independent'
  const systemReference = record.source_type === 'system_setting'
  if (
    typeof record.id !== 'string'
    || !isUuid(record.id)
    || typeof record.name !== 'string'
    || !record.name.trim()
    || record.name.length > 80
    || /[\u0000-\u001f\u007f]/.test(record.name)
    || (!independent && !systemReference)
    || (independent && record.source_key !== null)
    || (systemReference && !['securecrt', 'xshell', 'putty'].includes(String(record.source_key)))
    || (independent && (
      typeof record.executable_path !== 'string'
      || record.executable_path.length > 32_767
      || extname(record.executable_path).toLowerCase() !== '.exe'
    ))
    || (systemReference && record.executable_path !== null)
    || !Array.isArray(record.arguments)
    || record.arguments.length > 64
    || record.arguments.some((item) => (
      typeof item !== 'string'
      || item.length > 2_000
      || /[\u0000\r\n]/.test(item)
      || /(?:&&|\|\||[|<>])/.test(item)
    ))
    || (independent && (
      typeof record.working_directory !== 'string'
      || record.working_directory.length > 32_767
    ))
    || (systemReference && (record.working_directory !== null || record.arguments.length !== 0))
    || typeof record.category_id !== 'string'
    || !categoryIds.has(record.category_id)
    || typeof record.favorite !== 'boolean'
    || !isSafeOrder(record.sort_order)
    || !['auto', 'default', 'custom'].includes(String(record.icon_mode))
    || !['normal', 'ask', 'administrator'].includes(String(record.launch_privilege))
    || (record.custom_icon_path !== null && (
      typeof record.custom_icon_path !== 'string' || record.custom_icon_path.length > 32_767
    ))
    || !Number.isSafeInteger(record.launch_count)
    || (record.launch_count as number) < 0
    || !Number.isSafeInteger(record.administrator_launch_count)
    || (record.administrator_launch_count as number) < 0
    || (record.administrator_launch_count as number) > (record.launch_count as number)
    || (record.last_launched_at !== null && !isIsoDate(record.last_launched_at))
    || (record.last_launch_mode !== null && !['normal', 'administrator'].includes(String(record.last_launch_mode)))
    || !isIsoDate(record.created_at)
    || !isIsoDate(record.updated_at)
  ) throw new TypeError('external tool record is invalid')
  if (
    record.icon_mode === 'custom'
    && (
      typeof record.custom_icon_path !== 'string'
      || !windowsPathKey(record.custom_icon_path).startsWith(`${windowsPathKey(iconsPath)}\\`)
      || !['.png', '.jpg', '.jpeg', '.ico'].includes(extname(record.custom_icon_path).toLowerCase())
      || basename(record.custom_icon_path).toLowerCase() !== `${String(record.id).toLowerCase()}${extname(record.custom_icon_path).toLowerCase()}`
    )
  ) throw new TypeError('external tool custom icon path is invalid')
  if (record.icon_mode !== 'custom' && record.custom_icon_path !== null) {
    throw new TypeError('external tool custom icon mode is invalid')
  }
  return {
    id: record.id.toLowerCase(),
    name: record.name.trim(),
    source_type: record.source_type,
    source_key: systemReference ? record.source_key : null,
    executable_path: independent ? normalizeWindowsPath(record.executable_path) : null,
    arguments: [...record.arguments] as string[],
    working_directory: independent ? normalizeWindowsPath(record.working_directory) : null,
    category_id: record.category_id,
    favorite: record.favorite,
    sort_order: record.sort_order,
    icon_mode: record.icon_mode as ExternalToolIconMode,
    custom_icon_path: record.custom_icon_path,
    launch_privilege: record.launch_privilege,
    launch_count: record.launch_count as number,
    administrator_launch_count: record.administrator_launch_count as number,
    last_launched_at: record.last_launched_at as string | null,
    last_launch_mode: record.last_launch_mode as ExternalToolLaunchMode | null,
    created_at: record.created_at as string,
    updated_at: record.updated_at as string,
  }
}

function validateLegacyTool(
  value: unknown,
  categoryIds: Set<string>,
  iconsPath: string,
): ExternalToolRecord {
  const record = strictRecord(value, [
    'id', 'name', 'executable_path', 'arguments', 'working_directory', 'category_id',
    'favorite', 'sort_order', 'icon_mode', 'custom_icon_path', 'launch_count',
    'last_launched_at', 'created_at', 'updated_at',
  ], '旧版工具记录')
  return validateTool({
    ...record,
    source_type: 'independent',
    source_key: null,
    launch_privilege: 'normal',
    administrator_launch_count: 0,
    last_launch_mode: null,
  }, categoryIds, iconsPath)
}

function validateMigrations(value: unknown): ExternalToolState['migrations'] {
  const record = strictRecord(value, ['legacy_ipop_v1'], '工具集迁移标识')
  if (typeof record.legacy_ipop_v1 !== 'boolean') throw new TypeError('external tool migrations are invalid')
  return { legacy_ipop_v1: record.legacy_ipop_v1 }
}

function systemSettingToolName(sourceKey: ExternalToolSystemSettingKey): string {
  return sourceKey === 'securecrt' ? 'SecureCRT' : sourceKey === 'xshell' ? 'Xshell' : 'PuTTY'
}

function strictRecord(value: unknown, allowed: readonly string[], label: string): Record<string, any> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`${label}无效`)
  const record = value as Record<string, unknown>
  if (Object.keys(record).some((key) => !allowed.includes(key))) throw new TypeError(`${label}包含未知字段`)
  return record
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
}

function isSafeOrder(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isIsoDate(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value)) && value.length <= 40
}

function isMissingFile(cause: unknown): boolean {
  return Boolean(cause && typeof cause === 'object' && (cause as NodeJS.ErrnoException).code === 'ENOENT')
}

function errorCode(cause: unknown): string {
  return cause && typeof cause === 'object' && typeof (cause as NodeJS.ErrnoException).code === 'string'
    ? String((cause as NodeJS.ErrnoException).code)
    : 'INVALID_DATA'
}

export function externalToolFileName(tool: ExternalToolRecord): string {
  return tool.executable_path ? basename(tool.executable_path) : systemSettingToolName(tool.source_key!)
}
