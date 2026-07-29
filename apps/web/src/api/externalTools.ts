import type {
  ExternalToolCategoryReorderRequest,
  ExternalToolCreateRequest,
  ExternalToolDeleteCategoryRequest,
  ExternalToolIconSelectionResult,
  ExternalToolLaunchResult,
  ExternalToolLaunchMode,
  ExternalToolListResult,
  ExternalToolMutationResult,
  ExternalToolReorderRequest,
  ExternalToolSelectionResult,
  ExternalToolSystemReferenceCreateRequest,
  ExternalToolSystemSettingKey,
  ExternalToolUpdateRequest,
} from '../types/externalTools'

function bridge() {
  if (typeof window === 'undefined' || !window.netconsoleDesktop) {
    throw new Error('第三方工具启动仅支持 NetConsole 桌面版')
  }
  return window.netconsoleDesktop
}

export function listExternalTools(): Promise<ExternalToolListResult> {
  return bridge().listExternalTools()
}

export function refreshExternalToolStatuses(): Promise<ExternalToolListResult> {
  return bridge().refreshExternalToolStatuses()
}

export function selectExternalToolExecutable(): Promise<ExternalToolSelectionResult> {
  return bridge().selectExternalToolExecutable()
}

export function selectExternalToolWorkingDirectory() {
  return bridge().selectExternalToolWorkingDirectory()
}

export function selectExternalToolIcon(): Promise<ExternalToolIconSelectionResult> {
  return bridge().selectExternalToolIcon()
}

export function createExternalTool(request: ExternalToolCreateRequest): Promise<ExternalToolMutationResult> {
  return bridge().createExternalTool(request)
}

export function createExternalToolSystemReference(
  sourceKey: ExternalToolSystemSettingKey,
): Promise<ExternalToolMutationResult> {
  const request: ExternalToolSystemReferenceCreateRequest = { sourceKey }
  return bridge().createExternalToolSystemReference(request)
}

export function updateExternalTool(request: ExternalToolUpdateRequest): Promise<ExternalToolMutationResult> {
  return bridge().updateExternalTool(request)
}

export function deleteExternalTool(toolId: string): Promise<ExternalToolMutationResult> {
  return bridge().deleteExternalTool(toolId)
}

export function setExternalToolFavorite(toolId: string, favorite: boolean): Promise<ExternalToolMutationResult> {
  return bridge().setExternalToolFavorite(toolId, favorite)
}

export function reorderExternalTools(request: ExternalToolReorderRequest): Promise<ExternalToolMutationResult> {
  return bridge().reorderExternalTools(request)
}

export function reorderExternalToolCategories(request: ExternalToolCategoryReorderRequest): Promise<ExternalToolMutationResult> {
  return bridge().reorderExternalToolCategories(request)
}

export function createExternalToolCategory(name: string): Promise<ExternalToolMutationResult> {
  return bridge().createExternalToolCategory(name)
}

export function renameExternalToolCategory(categoryId: string, name: string): Promise<ExternalToolMutationResult> {
  return bridge().renameExternalToolCategory(categoryId, name)
}

export function deleteExternalToolCategory(request: ExternalToolDeleteCategoryRequest): Promise<ExternalToolMutationResult> {
  return bridge().deleteExternalToolCategory(request)
}

export function launchExternalTool(
  toolId: string,
  launchMode: ExternalToolLaunchMode,
): Promise<ExternalToolLaunchResult> {
  return bridge().launchExternalTool({ toolId, launchMode })
}

export function revealExternalTool(toolId: string): Promise<ExternalToolLaunchResult> {
  return bridge().revealExternalTool(toolId)
}

export function splitExternalToolArguments(value: string): string[] {
  const input = value.trim()
  if (!input) return []
  if (/(?:&&|\|\||[|<>])/.test(input)) {
    throw new Error('启动参数不支持管道、重定向、&& 或 ||')
  }
  const result: string[] = []
  let current = ''
  let quote: '"' | "'" | null = null
  let escaping = false
  for (const character of input) {
    if (escaping) {
      current += character
      escaping = false
      continue
    }
    if (character === '\\' && quote === '"') {
      escaping = true
      continue
    }
    if (quote) {
      if (character === quote) quote = null
      else current += character
      continue
    }
    if (character === '"' || character === "'") {
      quote = character
    } else if (/\s/.test(character)) {
      if (current) {
        result.push(current)
        current = ''
      }
    } else {
      current += character
    }
  }
  if (quote) throw new Error('启动参数中的引号未闭合')
  if (escaping) current += '\\'
  if (current) result.push(current)
  if (result.length > 64) throw new Error('启动参数数量不能超过 64 个')
  return result
}

export function formatExternalToolArguments(arguments_: string[]): string {
  return arguments_.map((value) => (
    /\s|["']/.test(value) ? `"${value.replaceAll('\\', '\\\\').replaceAll('"', '\\"')}"` : value
  )).join(' ')
}
