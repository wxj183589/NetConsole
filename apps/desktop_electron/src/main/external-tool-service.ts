import { randomUUID } from 'node:crypto'
import { promises as fs } from 'node:fs'
import { basename, extname, win32 } from 'node:path'

import type {
  ExternalToolCategoryReorderRequest,
  ExternalToolCreateRequest,
  ExternalToolDeleteCategoryRequest,
  ExternalToolIconSelectionResult,
  ExternalToolLaunchMode,
  ExternalToolLaunchRequest,
  ExternalToolLaunchResult,
  ExternalToolListResult,
  ExternalToolMutationResult,
  ExternalToolRecord,
  ExternalToolReorderRequest,
  ExternalToolSelectionResult,
  ExternalToolStatus,
  ExternalToolSystemReferenceCreateRequest,
  ExternalToolSystemSettingKey,
  ExternalToolUpdateRequest,
  ExternalToolView,
} from '../shared/bridge'
import { settingsToolNameMatches } from '../shared/bridge'
import {
  EXTERNAL_TOOL_MAX_ICON_BYTES,
  ExternalToolStore,
  ExternalToolStoreError,
  externalToolFileName,
  windowsPathKey,
} from './external-tool-store'
import type { ExternalToolSystemSettings } from './external-tool-settings'

interface SpawnedProcessLike {
  once(event: 'spawn' | 'error', listener: (cause?: Error) => void): this
  removeAllListeners?(event: 'spawn' | 'error'): this
  unref(): void
}

interface ExternalToolServiceDependencies {
  store: ExternalToolStore
  spawn: (
    executable: string,
    arguments_: readonly string[],
    options: { shell: false; detached: true; stdio: 'ignore'; cwd: string; windowsHide: false },
  ) => SpawnedProcessLike
  reveal(path: string): void
  getExecutableIcon(path: string): Promise<string | null>
  getCustomIcon(path: string): Promise<string | null>
  resolveSystemSettings(): Promise<ExternalToolSystemSettings>
  elevatedLaunch(request: ElevatedToolLaunchRequest): Promise<'launched' | 'cancelled'>
  applicationExecutablePath?: string
  logger?: (event: string, detail?: string) => void
}

export interface ElevatedToolLaunchRequest {
  executablePath: string
  arguments: string[]
  workingDirectory: string
}

interface StagedIcon {
  path: string
  expiresAt: number
}

export interface ExternalToolServiceLike {
  list(): Promise<ExternalToolListResult>
  describeExecutable(path: string): Promise<ExternalToolSelectionResult>
  stageCustomIcon(path: string): Promise<ExternalToolIconSelectionResult>
  create(request: ExternalToolCreateRequest): Promise<ExternalToolMutationResult>
  createSystemReference(request: ExternalToolSystemReferenceCreateRequest): Promise<ExternalToolMutationResult>
  update(request: ExternalToolUpdateRequest): Promise<ExternalToolMutationResult>
  delete(toolId: string): Promise<ExternalToolMutationResult>
  setFavorite(toolId: string, favorite: boolean): Promise<ExternalToolMutationResult>
  reorderTools(request: ExternalToolReorderRequest): Promise<ExternalToolMutationResult>
  reorderCategories(request: ExternalToolCategoryReorderRequest): Promise<ExternalToolMutationResult>
  createCategory(name: string): Promise<ExternalToolMutationResult>
  renameCategory(categoryId: string, name: string): Promise<ExternalToolMutationResult>
  deleteCategory(request: ExternalToolDeleteCategoryRequest): Promise<ExternalToolMutationResult>
  launch(request: ExternalToolLaunchRequest): Promise<ExternalToolLaunchResult>
  reveal(toolId: string): Promise<ExternalToolLaunchResult>
}

export class ExternalToolService implements ExternalToolServiceLike {
  private readonly iconCache = new Map<string, string | null>()
  private readonly stagedIcons = new Map<string, StagedIcon>()

  constructor(private readonly dependencies: ExternalToolServiceDependencies) {}

  async list(): Promise<ExternalToolListResult> {
    let snapshot = await this.dependencies.store.list()
    const needsSettings = (
      !snapshot.migrations.legacy_ipop_v1
      || snapshot.tools.some((tool) => tool.source_type === 'system_setting')
    )
    const settings = needsSettings ? await this.readSystemSettings() : undefined
    if (!snapshot.migrations.legacy_ipop_v1 && settings) {
      try {
        await this.dependencies.store.migrateLegacyIpop(settings.legacyIpopPath)
        snapshot = await this.dependencies.store.list()
      } catch (cause) {
        this.dependencies.logger?.(
          'ELECTRON_EXTERNAL_TOOL_IPOP_MIGRATION_FAILED',
          `error_code=${errorCode(cause)}`,
        )
      }
    }
    const categories = [...snapshot.categories].sort((left, right) => left.sort_order - right.sort_order)
    const categoryNames = new Map(categories.map((category) => [category.id, category.name]))
    const tools = await Promise.all(snapshot.tools.map(async (tool) => {
      const resolved = resolveTool(tool, settings)
      const { status, message } = await inspectToolStatus(resolved)
      return {
        ...tool,
        executable_path: resolved.executablePath,
        working_directory: resolved.workingDirectory,
        category_name: categoryNames.get(tool.category_id) || '未知分类',
        executable_name: resolved.executablePath ? basename(resolved.executablePath) : externalToolFileName(tool),
        status,
        status_message: message,
        icon_data_url: await this.iconFor(tool, resolved.executablePath),
      } satisfies ExternalToolView
    }))
    tools.sort((left, right) => (
      left.category_id.localeCompare(right.category_id)
      || left.sort_order - right.sort_order
      || left.name.localeCompare(right.name, 'zh-CN')
    ))
    return { schema_version: 2, categories, tools }
  }

  async describeExecutable(path: string): Promise<ExternalToolSelectionResult> {
    const normalized = win32.normalize(path)
    if (!win32.isAbsolute(normalized) || extname(normalized).toLowerCase() !== '.exe') {
      throw new ExternalToolStoreError('INVALID_REQUEST', '仅支持 Windows .exe 程序。')
    }
    const selected = await fs.stat(normalized)
    if (!selected.isFile()) throw new ExternalToolStoreError('INVALID_REQUEST', '程序路径不是普通文件。')
    const snapshot = await this.dependencies.store.list()
    const duplicate = snapshot.tools.find(
      (tool) => tool.executable_path !== null
        && windowsPathKey(tool.executable_path) === windowsPathKey(normalized),
    )
    return {
      cancelled: false,
      path: normalized,
      suggestedName: basename(normalized, extname(normalized)),
      workingDirectory: win32.dirname(normalized),
      iconDataUrl: await this.dependencies.getExecutableIcon(normalized).catch(() => null),
      ...(duplicate ? { duplicateTool: { id: duplicate.id, name: duplicate.name } } : {}),
    }
  }

  async stageCustomIcon(path: string): Promise<ExternalToolIconSelectionResult> {
    const extension = extname(path).toLowerCase()
    const stat = await fs.stat(path)
    if (!stat.isFile() || !['.png', '.jpg', '.jpeg', '.ico'].includes(extension) || stat.size > EXTERNAL_TOOL_MAX_ICON_BYTES) {
      throw new ExternalToolStoreError('INVALID_REQUEST', '自定义图标无效或超过 5 MB。')
    }
    this.removeExpiredSelections()
    if (this.stagedIcons.size >= 20) this.stagedIcons.delete(this.stagedIcons.keys().next().value as string)
    const selectionId = randomUUID()
    this.stagedIcons.set(selectionId, { path, expiresAt: Date.now() + 10 * 60_000 })
    const iconDataUrl = await this.dependencies.getCustomIcon(path)
    if (!iconDataUrl) throw new ExternalToolStoreError('INVALID_REQUEST', '无法读取所选图标。')
    return { cancelled: false, selectionId, iconDataUrl }
  }

  async create(request: ExternalToolCreateRequest): Promise<ExternalToolMutationResult> {
    return this.mutation(async () => {
      const iconPath = this.consumeIconSelection(request)
      const record = await this.dependencies.store.create(request, iconPath)
      this.iconCache.clear()
      return record
    })
  }

  async createSystemReference(
    request: ExternalToolSystemReferenceCreateRequest,
  ): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.createSystemReference(request.sourceKey))
  }

  async update(request: ExternalToolUpdateRequest): Promise<ExternalToolMutationResult> {
    return this.mutation(async () => {
      const iconPath = this.consumeIconSelection(request)
      const record = await this.dependencies.store.update(request, iconPath)
      this.iconCache.clear()
      return record
    })
  }

  async delete(toolId: string): Promise<ExternalToolMutationResult> {
    return this.mutation(async () => {
      await this.dependencies.store.delete(toolId)
      this.iconCache.clear()
    })
  }

  async setFavorite(toolId: string, favorite: boolean): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.setFavorite(toolId, favorite))
  }

  async reorderTools(request: ExternalToolReorderRequest): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.reorderTools(request.categoryId, request.toolIds))
  }

  async reorderCategories(request: ExternalToolCategoryReorderRequest): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.reorderCategories(request.categoryIds))
  }

  async createCategory(name: string): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.createCategory(name))
  }

  async renameCategory(categoryId: string, name: string): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.renameCategory(categoryId, name))
  }

  async deleteCategory(request: ExternalToolDeleteCategoryRequest): Promise<ExternalToolMutationResult> {
    return this.mutation(() => this.dependencies.store.deleteCategory(request.categoryId, request.moveToolsToOther))
  }

  async launch(request: ExternalToolLaunchRequest): Promise<ExternalToolLaunchResult> {
    const tool = await this.dependencies.store.get(request.toolId)
    if (!tool) return { success: false, toolId: request.toolId, error: '工具记录不存在。' }
    const settings = tool.source_type === 'system_setting'
      ? await this.readSystemSettings()
      : undefined
    const resolved = resolveTool(tool, settings)
    const inspected = await inspectToolStatus(resolved)
    if (inspected.status !== 'AVAILABLE') {
      return { success: false, toolId: tool.id, status: inspected.status, error: inspected.message }
    }
    const launchMode = tool.launch_privilege === 'administrator'
      ? 'administrator'
      : request.launchMode
    try {
      if (launchMode === 'administrator') {
        if (isNetConsoleExecutable(resolved.executablePath, this.dependencies.applicationExecutablePath)) {
          return { success: false, toolId: tool.id, error: '禁止以管理员身份启动 NetConsole。' }
        }
        const result = await this.dependencies.elevatedLaunch({
          executablePath: resolved.executablePath,
          arguments: [...tool.arguments],
          workingDirectory: resolved.workingDirectory,
        })
        if (result === 'cancelled') {
          this.dependencies.logger?.('ELECTRON_EXTERNAL_TOOL_ELEVATION_CANCELLED', `tool_id=${tool.id}`)
          return {
            success: false,
            toolId: tool.id,
            status: 'cancelled',
            errorCode: 'ELEVATION_CANCELLED',
            error: '已取消管理员身份启动。',
          }
        }
      } else {
        const child = this.dependencies.spawn(resolved.executablePath, tool.arguments, {
          shell: false,
          detached: true,
          stdio: 'ignore',
          cwd: resolved.workingDirectory,
          windowsHide: false,
        })
        await waitForSpawn(child)
        child.unref()
      }
      await this.dependencies.store.recordLaunch(tool.id, launchMode)
      this.dependencies.logger?.(
        'ELECTRON_EXTERNAL_TOOL_LAUNCHED',
        `tool_id=${tool.id} launch_mode=${launchMode}`,
      )
      return { success: true, toolId: tool.id }
    } catch (cause) {
      this.dependencies.logger?.(
        'ELECTRON_EXTERNAL_TOOL_LAUNCH_FAILED',
        `tool_id=${tool.id} launch_mode=${launchMode} error_code=${errorCode(cause)}`,
      )
      return { success: false, toolId: tool.id, error: launchError(cause) }
    }
  }

  async reveal(toolId: string): Promise<ExternalToolLaunchResult> {
    const tool = await this.dependencies.store.get(toolId)
    if (!tool) return { success: false, toolId, error: '工具记录不存在。' }
    const settings = tool.source_type === 'system_setting'
      ? await this.readSystemSettings()
      : undefined
    const resolved = resolveTool(tool, settings)
    const inspected = await inspectToolStatus(resolved)
    if (inspected.status === 'MISSING' || inspected.status === 'INVALID') {
      return { success: false, toolId, status: inspected.status, error: inspected.message }
    }
    this.dependencies.reveal(resolved.executablePath)
    return { success: true, toolId }
  }

  private async mutation(operation: () => Promise<unknown>): Promise<ExternalToolMutationResult> {
    try {
      const value = await operation()
      const list = await this.list()
      const record = isToolRecord(value) ? value : undefined
      return {
        success: true,
        list,
        ...(record ? { tool: list.tools.find((tool) => tool.id === record.id) } : {}),
      }
    } catch (cause) {
      const error = cause instanceof ExternalToolStoreError
        ? cause
        : new ExternalToolStoreError('PERSISTENCE_FAILED', '工具集操作失败，请检查日志后重试。')
      const existing = error.existingToolId
        ? (await this.list()).tools.find((tool) => tool.id === error.existingToolId)
        : undefined
      this.dependencies.logger?.('ELECTRON_EXTERNAL_TOOL_MUTATION_FAILED', `error_code=${error.code}`)
      return {
        success: false,
        errorCode: error.code,
        error: error.message,
        ...(existing ? { existingTool: { id: existing.id, name: existing.name } } : {}),
      }
    }
  }

  private consumeIconSelection(
    request: Pick<ExternalToolCreateRequest, 'iconMode' | 'iconSelectionId'>,
  ): string | undefined {
    if (request.iconMode !== 'custom') return undefined
    if (!request.iconSelectionId) return undefined
    this.removeExpiredSelections()
    const selection = this.stagedIcons.get(request.iconSelectionId)
    if (!selection) throw new ExternalToolStoreError('INVALID_REQUEST', '图标选择已过期，请重新选择。')
    this.stagedIcons.delete(request.iconSelectionId)
    return selection.path
  }

  private async iconFor(tool: ExternalToolRecord, executablePath: string): Promise<string | null> {
    if (tool.icon_mode === 'default') return null
    const path = tool.icon_mode === 'custom' ? tool.custom_icon_path : executablePath
    if (!path) return null
    const key = `${tool.icon_mode}:${path.toLocaleLowerCase('en-US')}`
    if (this.iconCache.has(key)) return this.iconCache.get(key) ?? null
    const value = tool.icon_mode === 'custom'
      ? await this.dependencies.getCustomIcon(path).catch(() => null)
      : await this.dependencies.getExecutableIcon(path).catch(() => null)
    this.iconCache.set(key, value)
    if (this.iconCache.size > 256) this.iconCache.delete(this.iconCache.keys().next().value as string)
    return value
  }

  private async readSystemSettings(): Promise<ExternalToolSystemSettings | undefined> {
    try {
      return await this.dependencies.resolveSystemSettings()
    } catch (cause) {
      this.dependencies.logger?.(
        'ELECTRON_EXTERNAL_TOOL_SETTINGS_READ_FAILED',
        `error_code=${errorCode(cause)}`,
      )
      return undefined
    }
  }

  private removeExpiredSelections(): void {
    const now = Date.now()
    for (const [id, item] of this.stagedIcons) if (item.expiresAt <= now) this.stagedIcons.delete(id)
  }
}

interface ResolvedExternalTool {
  executablePath: string
  workingDirectory: string
  resolutionError?: string
}

export async function inspectToolStatus(
  tool: ResolvedExternalTool,
): Promise<{ status: ExternalToolStatus; message: string }> {
  if (tool.resolutionError) return { status: 'INVALID', message: tool.resolutionError }
  if (!win32.isAbsolute(tool.executablePath) || extname(tool.executablePath).toLowerCase() !== '.exe') {
    return { status: 'INVALID', message: '程序路径或文件类型无效' }
  }
  try {
    if ((await fs.lstat(tool.executablePath)).isSymbolicLink()) {
      return { status: 'INVALID', message: '程序路径不能是符号链接' }
    }
    const executable = await fs.stat(tool.executablePath)
    if (!executable.isFile()) return { status: 'INVALID', message: '程序路径不是普通文件' }
  } catch {
    return { status: 'MISSING', message: '程序文件不存在' }
  }
  if (!win32.isAbsolute(tool.workingDirectory)) {
    return { status: 'INVALID', message: '工作目录配置无效' }
  }
  try {
    if (!(await fs.stat(tool.workingDirectory)).isDirectory()) {
      return { status: 'WORKDIR_MISSING', message: '工作目录不存在' }
    }
  } catch {
    return { status: 'WORKDIR_MISSING', message: '工作目录不存在' }
  }
  return { status: 'AVAILABLE', message: '可用' }
}

function resolveTool(
  tool: ExternalToolRecord,
  settings: ExternalToolSystemSettings | undefined,
): ResolvedExternalTool {
  if (tool.source_type === 'independent') {
    return {
      executablePath: tool.executable_path ?? '',
      workingDirectory: tool.working_directory ?? '',
    }
  }
  if (!settings) {
    return {
      executablePath: '',
      workingDirectory: '',
      resolutionError: '无法读取系统设置中的外部终端路径',
    }
  }
  const sourceKey = tool.source_key as ExternalToolSystemSettingKey
  const executablePath = settings.terminalPaths[sourceKey]
  if (!executablePath) {
    return {
      executablePath: '',
      workingDirectory: '',
      resolutionError: '请先在系统设置 → 外部终端中配置路径',
    }
  }
  if (!win32.isAbsolute(executablePath) || !settingsToolNameMatches(sourceKey, executablePath)) {
    return {
      executablePath,
      workingDirectory: '',
      resolutionError: '系统设置中的外部终端路径无效',
    }
  }
  return {
    executablePath: win32.normalize(executablePath),
    workingDirectory: win32.dirname(executablePath),
  }
}

function waitForSpawn(child: SpawnedProcessLike): Promise<void> {
  return new Promise((resolve, reject) => {
    child.once('spawn', () => {
      child.removeAllListeners?.('error')
      resolve()
    })
    child.once('error', (cause) => {
      child.removeAllListeners?.('spawn')
      reject(cause ?? new Error('spawn failed'))
    })
  })
}

function launchError(cause: unknown): string {
  const code = errorCode(cause)
  if (code === 'ENOENT') return '程序文件不存在。'
  if (code === 'EACCES' || code === 'EPERM') return '没有权限启动该程序。'
  if (code === 'EINVAL') return '工具配置已损坏，请重新编辑。'
  return 'Windows 拒绝启动该程序，请检查程序权限和兼容性。'
}

function isNetConsoleExecutable(executablePath: string, applicationExecutablePath?: string): boolean {
  if (basename(executablePath).toLocaleLowerCase('en-US') === 'netconsole.exe') return true
  if (!applicationExecutablePath) return false
  try {
    return windowsPathKey(executablePath) === windowsPathKey(applicationExecutablePath)
  } catch {
    return false
  }
}

function errorCode(cause: unknown): string {
  return cause && typeof cause === 'object' && typeof (cause as NodeJS.ErrnoException).code === 'string'
    ? String((cause as NodeJS.ErrnoException).code)
    : 'UNKNOWN'
}

function isToolRecord(value: unknown): value is ExternalToolRecord {
  return Boolean(value && typeof value === 'object' && typeof (value as ExternalToolRecord).id === 'string')
}
