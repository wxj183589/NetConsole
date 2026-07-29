import { randomUUID } from 'node:crypto'
import { promises as fs } from 'node:fs'
import { basename, dirname, extname, join, win32 } from 'node:path'

import type {
  ExternalToolCategory,
  ExternalToolCreateRequest,
  ExternalToolIconMode,
  ExternalToolRecord,
  ExternalToolUpdateRequest,
} from '../shared/bridge'

export const EXTERNAL_TOOL_SCHEMA_VERSION = 1
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
}

type StoreLogger = (event: string, detail?: string) => void

export interface ExternalToolStoreSnapshot {
  schema_version: 1
  categories: ExternalToolCategory[]
  tools: ExternalToolRecord[]
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
        (tool) => windowsPathKey(tool.executable_path) === windowsPathKey(executablePath),
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
        executable_path: executablePath,
        arguments: [...request.arguments],
        working_directory: workingDirectory,
        category_id: category.id,
        favorite: request.favorite,
        sort_order: nextToolOrder(state, category.id),
        icon_mode: request.iconMode,
        custom_icon_path: customIconPath,
        launch_count: 0,
        last_launched_at: null,
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

  async update(
    request: ExternalToolUpdateRequest,
    customIconSourcePath?: string,
  ): Promise<ExternalToolRecord> {
    return this.enqueue(async () => {
      await this.ensureLoaded()
      const state = this.requireState()
      const existing = requireTool(state, request.id)
      await assertExecutable(request.executablePath)
      const executablePath = normalizeWindowsPath(request.executablePath)
      const duplicate = state.tools.find(
        (tool) => tool.id !== existing.id
          && windowsPathKey(tool.executable_path) === windowsPathKey(executablePath),
      )
      if (duplicate) throw new ExternalToolStoreError('DUPLICATE_PATH', `该程序已经添加为「${duplicate.name}」。`, duplicate.id)
      requireCategory(state, request.categoryId)
      const workingDirectory = normalizeWindowsPath(
        request.workingDirectory || win32.dirname(executablePath),
      )
      await assertDirectory(workingDirectory)
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
        arguments: [...request.arguments],
        working_directory: workingDirectory,
        category_id: request.categoryId,
        favorite: request.favorite,
        sort_order: changedCategory ? nextToolOrder(state, request.categoryId) : existing.sort_order,
        icon_mode: request.iconMode,
        custom_icon_path: customIconPath,
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

  async recordLaunch(toolId: string): Promise<ExternalToolRecord> {
    return this.mutateTool(toolId, (tool) => {
      tool.launch_count += 1
      tool.last_launched_at = new Date().toISOString()
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
    try {
      const stat = await fs.stat(this.path)
      if (!stat.isFile() || stat.size > EXTERNAL_TOOL_STORE_MAX_BYTES) {
        throw new TypeError('external tool store file is invalid')
      }
      const raw = await fs.readFile(this.path, 'utf8')
      this.state = validatePersistedState(JSON.parse(raw), this.iconsPath)
    } catch (cause) {
      if (isMissingFile(cause)) {
        this.state = defaultState()
        await this.writeState()
        return
      }
      await this.recoverDamagedFile(cause)
    }
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
    readonly code: 'DUPLICATE_PATH' | 'INVALID_REQUEST' | 'NOT_FOUND' | 'PERSISTENCE_FAILED',
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
  }
}

function cloneState(state: ExternalToolState): ExternalToolStoreSnapshot {
  return {
    schema_version: 1,
    categories: state.categories.map((category) => ({ ...category })),
    tools: state.tools.map(cloneTool),
  }
}

function cloneTool(tool: ExternalToolRecord): ExternalToolRecord {
  return { ...tool, arguments: [...tool.arguments] }
}

function validatePersistedState(value: unknown, iconsPath: string): ExternalToolState {
  const record = strictRecord(value, ['schema_version', 'categories', 'tools'], '工具集配置')
  if (record.schema_version !== EXTERNAL_TOOL_SCHEMA_VERSION) throw new TypeError('external tool schema version is invalid')
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
  const tools = record.tools.map((item) => validateTool(item, categoryIds, iconsPath))
  if (new Set(tools.map((item) => item.id)).size !== tools.length) throw new TypeError('external tool ids are duplicated')
  if (new Set(tools.map((item) => windowsPathKey(item.executable_path))).size !== tools.length) {
    throw new TypeError('external tool paths are duplicated')
  }
  return { schema_version: 1, categories, tools }
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
    'id', 'name', 'executable_path', 'arguments', 'working_directory', 'category_id',
    'favorite', 'sort_order', 'icon_mode', 'custom_icon_path', 'launch_count',
    'last_launched_at', 'created_at', 'updated_at',
  ]
  const record = strictRecord(value, keys, '工具记录')
  if (
    typeof record.id !== 'string'
    || !isUuid(record.id)
    || typeof record.name !== 'string'
    || !record.name.trim()
    || record.name.length > 80
    || /[\u0000-\u001f\u007f]/.test(record.name)
    || typeof record.executable_path !== 'string'
    || record.executable_path.length > 32_767
    || extname(record.executable_path).toLowerCase() !== '.exe'
    || !Array.isArray(record.arguments)
    || record.arguments.length > 64
    || record.arguments.some((item) => (
      typeof item !== 'string'
      || item.length > 2_000
      || /[\u0000\r\n]/.test(item)
      || /(?:&&|\|\||[|<>])/.test(item)
    ))
    || typeof record.working_directory !== 'string'
    || record.working_directory.length > 32_767
    || typeof record.category_id !== 'string'
    || !categoryIds.has(record.category_id)
    || typeof record.favorite !== 'boolean'
    || !isSafeOrder(record.sort_order)
    || !['auto', 'default', 'custom'].includes(String(record.icon_mode))
    || (record.custom_icon_path !== null && (
      typeof record.custom_icon_path !== 'string' || record.custom_icon_path.length > 32_767
    ))
    || !Number.isSafeInteger(record.launch_count)
    || (record.launch_count as number) < 0
    || (record.last_launched_at !== null && !isIsoDate(record.last_launched_at))
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
    executable_path: normalizeWindowsPath(record.executable_path),
    arguments: [...record.arguments] as string[],
    working_directory: normalizeWindowsPath(record.working_directory),
    category_id: record.category_id,
    favorite: record.favorite,
    sort_order: record.sort_order,
    icon_mode: record.icon_mode as ExternalToolIconMode,
    custom_icon_path: record.custom_icon_path,
    launch_count: record.launch_count as number,
    last_launched_at: record.last_launched_at as string | null,
    created_at: record.created_at as string,
    updated_at: record.updated_at as string,
  }
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
  return basename(tool.executable_path)
}
