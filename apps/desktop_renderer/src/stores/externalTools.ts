import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createExternalTool,
  createExternalToolCategory,
  createExternalToolSystemReference,
  deleteExternalTool,
  deleteExternalToolCategory,
  launchExternalTool,
  listExternalTools,
  refreshExternalToolStatuses,
  renameExternalToolCategory,
  reorderExternalToolCategories,
  reorderExternalTools,
  revealExternalTool,
  setExternalToolFavorite,
  updateExternalTool,
} from '../api/externalTools'
import type {
  ExternalToolCategory,
  ExternalToolCreateRequest,
  ExternalToolDeleteCategoryRequest,
  ExternalToolListResult,
  ExternalToolLaunchMode,
  ExternalToolLaunchResult,
  ExternalToolMutationResult,
  ExternalToolUpdateRequest,
  ExternalToolView,
  ExternalToolSystemSettingKey,
} from '../types/externalTools'

export const useExternalToolsStore = defineStore('external-tools', () => {
  const categories = ref<ExternalToolCategory[]>([])
  const tools = ref<ExternalToolView[]>([])
  const loading = ref(false)
  const error = ref('')
  const launchingIds = ref<Set<string>>(new Set())

  const favoriteTools = computed(() => tools.value
    .filter((tool) => tool.favorite)
    .sort(toolOrder))
  const commonTools = computed(() => tools.value
    .filter((tool) => !tool.favorite && tool.launch_count > 0)
    .sort((left, right) => (
      right.launch_count - left.launch_count
      || String(right.last_launched_at).localeCompare(String(left.last_launched_at))
    ))
    .slice(0, 12))

  function applyList(list: ExternalToolListResult): void {
    categories.value = list.categories
    tools.value = list.tools
  }

  async function refresh(statuses = false): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      applyList(await (statuses ? refreshExternalToolStatuses() : listExternalTools()))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '工具集加载失败'
    } finally {
      loading.value = false
    }
  }

  async function save(request: ExternalToolCreateRequest | ExternalToolUpdateRequest): Promise<ExternalToolMutationResult> {
    const result = 'id' in request
      ? await updateExternalTool(request)
      : await createExternalTool(request)
    if (result.list) applyList(result.list)
    return result
  }

  async function remove(toolId: string): Promise<ExternalToolMutationResult> {
    const result = await deleteExternalTool(toolId)
    if (result.list) applyList(result.list)
    return result
  }

  async function favorite(tool: ExternalToolView): Promise<ExternalToolMutationResult> {
    const result = await setExternalToolFavorite(tool.id, !tool.favorite)
    if (result.list) applyList(result.list)
    return result
  }

  async function launch(
    tool: ExternalToolView,
    launchMode: ExternalToolLaunchMode,
  ): Promise<ExternalToolLaunchResult | undefined> {
    if (launchingIds.value.has(tool.id)) return undefined
    launchingIds.value = new Set(launchingIds.value).add(tool.id)
    try {
      const result = await launchExternalTool(tool.id, launchMode)
      if (result.success) await refresh()
      return result
    } finally {
      const next = new Set(launchingIds.value)
      next.delete(tool.id)
      launchingIds.value = next
    }
  }

  async function addSystemReference(
    sourceKey: ExternalToolSystemSettingKey,
  ): Promise<ExternalToolMutationResult> {
    const result = await createExternalToolSystemReference(sourceKey)
    if (result.list) applyList(result.list)
    return result
  }

  async function reveal(toolId: string): Promise<void> {
    const result = await revealExternalTool(toolId)
    if (!result.success) throw new Error(result.error || '无法在资源管理器中显示该工具')
  }

  async function createCategory(name: string): Promise<ExternalToolMutationResult> {
    const result = await createExternalToolCategory(name)
    if (result.list) applyList(result.list)
    return result
  }

  async function renameCategory(categoryId: string, name: string): Promise<ExternalToolMutationResult> {
    const result = await renameExternalToolCategory(categoryId, name)
    if (result.list) applyList(result.list)
    return result
  }

  async function deleteCategory(request: ExternalToolDeleteCategoryRequest): Promise<ExternalToolMutationResult> {
    const result = await deleteExternalToolCategory(request)
    if (result.list) applyList(result.list)
    return result
  }

  async function reorderCategories(categoryIds: string[]): Promise<ExternalToolMutationResult> {
    const result = await reorderExternalToolCategories({ categoryIds })
    if (result.list) applyList(result.list)
    return result
  }

  async function reorderTools(categoryId: string, toolIds: string[]): Promise<ExternalToolMutationResult> {
    const result = await reorderExternalTools({ categoryId, toolIds })
    if (result.list) applyList(result.list)
    return result
  }

  return {
    categories,
    tools,
    loading,
    error,
    launchingIds,
    favoriteTools,
    commonTools,
    refresh,
    save,
    remove,
    favorite,
    launch,
    addSystemReference,
    reveal,
    createCategory,
    renameCategory,
    deleteCategory,
    reorderCategories,
    reorderTools,
  }
})

function toolOrder(left: ExternalToolView, right: ExternalToolView): number {
  return left.sort_order - right.sort_order || left.name.localeCompare(right.name, 'zh-CN')
}
