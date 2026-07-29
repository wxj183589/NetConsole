<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'

import { useExternalToolsStore } from '../../stores/externalTools'
import type {
  ExternalToolCategory,
  ExternalToolCreateRequest,
  ExternalToolLaunchMode,
  ExternalToolSystemSettingKey,
  ExternalToolUpdateRequest,
  ExternalToolView,
} from '../../types/externalTools'
import ExternalToolCard from './components/ExternalToolCard.vue'
import ExternalToolCategoryDialog from './components/ExternalToolCategoryDialog.vue'
import ExternalToolEditorDialog from './components/ExternalToolEditorDialog.vue'

const store = useExternalToolsStore()
const router = useRouter()
const { categories, tools, loading, error, launchingIds, favoriteTools, commonTools } = storeToRefs(store)
const activeTab = ref<'all' | 'favorites'>('all')
const search = ref('')
const editorVisible = ref(false)
const categoryVisible = ref(false)
const editingTool = ref<ExternalToolView | null>(null)
const relocateOnOpen = ref(false)
const editor = ref<InstanceType<typeof ExternalToolEditorDialog>>()
const isDesktop = typeof window !== 'undefined' && Boolean(window.netconsoleDesktop)

const filteredTools = computed(() => {
  const keyword = search.value.trim().toLocaleLowerCase()
  if (!keyword) return tools.value
  return tools.value.filter((tool) => (
    [tool.name, tool.category_name, tool.executable_name]
      .join(' ')
      .toLocaleLowerCase()
      .includes(keyword)
  ))
})

const groupedTools = computed(() => categories.value
  .map((category) => ({
    category,
    tools: filteredTools.value
      .filter((tool) => tool.category_id === category.id)
      .sort((left, right) => left.sort_order - right.sort_order || left.name.localeCompare(right.name, 'zh-CN')),
  }))
  .filter((group) => group.tools.length))
const filteredIds = computed(() => new Set(filteredTools.value.map((tool) => tool.id)))
const visibleFavoriteTools = computed(() => favoriteTools.value.filter((tool) => filteredIds.value.has(tool.id)))
const visibleCommonTools = computed(() => commonTools.value.filter((tool) => filteredIds.value.has(tool.id)))

onMounted(() => {
  if (isDesktop) void store.refresh()
})

function openEditor(tool: ExternalToolView | null = null, relocate = false): void {
  editingTool.value = tool
  relocateOnOpen.value = relocate
  editorVisible.value = true
}

async function saveTool(
  request: ExternalToolCreateRequest | ExternalToolUpdateRequest,
  launch: boolean,
): Promise<void> {
  try {
    const result = await store.save(request)
    if (!result.success) {
      editor.value?.markSaved(false)
      if (result.errorCode === 'DUPLICATE_PATH' && result.existingTool) {
        editorVisible.value = false
        queueMicrotask(() => { void openExisting(result.existingTool!.id) })
        return
      }
      return void ElMessage.error(result.error || '工具保存失败')
    }
    editor.value?.markSaved(true)
    ElMessage.success('工具已保存')
    if (launch && result.tool) await launchTool(result.tool)
  } catch (cause) {
    editor.value?.markSaved(false)
    ElMessage.error(cause instanceof Error ? cause.message : '工具保存失败')
  }
}

async function launchTool(
  tool: ExternalToolView,
  requestedMode?: ExternalToolLaunchMode,
): Promise<void> {
  try {
    let launchMode = requestedMode
      ?? (tool.launch_privilege === 'administrator' ? 'administrator' : 'normal')
    if (!requestedMode && tool.launch_privilege === 'ask') {
      try {
        await ElMessageBox.confirm(
          '选择本次启动权限。',
          '启动权限',
          {
            confirmButtonText: '管理员身份',
            cancelButtonText: '普通权限',
            distinguishCancelAndClose: true,
            type: 'warning',
          },
        )
        launchMode = 'administrator'
      } catch (action) {
        if (action === 'cancel') launchMode = 'normal'
        else return
      }
    }
    const result = await store.launch(tool, launchMode)
    if (!result) return
    if (result.errorCode === 'ELEVATION_CANCELLED') {
      ElMessage.info('已取消管理员身份启动。')
    } else if (!result.success) {
      ElMessage.error(result.error || '工具启动失败')
    }
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '工具启动失败')
  }
}

async function addSystemReference(value: string | number | object): Promise<void> {
  const sourceKey = String(value)
  if (!['securecrt', 'xshell', 'putty'].includes(sourceKey)) return
  const result = await store.addSystemReference(sourceKey as ExternalToolSystemSettingKey)
  if (result.success) ElMessage.success('系统已配置工具已添加')
  else if (result.existingTool) await openExisting(result.existingTool.id)
  else ElMessage.error(result.error || '系统已配置工具添加失败')
}

async function configureSystemTool(): Promise<void> {
  await router.push({ path: '/system-settings', query: { section: 'external-terminal' } })
}

async function toggleFavorite(tool: ExternalToolView): Promise<void> {
  const result = await store.favorite(tool)
  if (!result.success) ElMessage.error(result.error || '收藏状态更新失败')
}

async function revealTool(tool: ExternalToolView): Promise<void> {
  try {
    await store.reveal(tool.id)
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '无法在资源管理器中显示该工具')
  }
}

async function removeTool(tool: ExternalToolView): Promise<void> {
  try {
    await ElMessageBox.confirm(
      tool.source_type === 'system_setting'
        ? '仅删除工具集快捷入口，不会清除系统设置中的外部终端路径。'
        : '仅删除 NetConsole 中的工具记录，不会删除本机程序文件。',
      '删除工具',
      { confirmButtonText: '删除记录', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  const result = await store.remove(tool.id)
  if (result.success) ElMessage.success('工具记录已删除')
  else ElMessage.error(result.error || '工具记录删除失败')
}

async function promptCreateCategory(): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入分类名称', '新增分类', {
      confirmButtonText: '新增',
      cancelButtonText: '取消',
      inputPattern: /^.{1,80}$/,
      inputErrorMessage: '分类名称为 1–80 个字符',
    })
    const result = await store.createCategory(value.trim())
    if (!result.success) ElMessage.error(result.error || '分类创建失败')
  } catch {
    // 用户取消。
  }
}

async function promptRenameCategory(category: ExternalToolCategory): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的分类名称', '重命名分类', {
      inputValue: category.name,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /^.{1,80}$/,
      inputErrorMessage: '分类名称为 1–80 个字符',
    })
    const result = await store.renameCategory(category.id, value.trim())
    if (!result.success) ElMessage.error(result.error || '分类重命名失败')
  } catch {
    // 用户取消。
  }
}

async function removeCategory(category: ExternalToolCategory): Promise<void> {
  const hasTools = tools.value.some((tool) => tool.category_id === category.id)
  try {
    await ElMessageBox.confirm(
      hasTools
        ? `“${category.name}”中仍有工具，删除后这些工具将移动到“其他工具”。`
        : `确定删除空分类“${category.name}”吗？`,
      '删除分类',
      {
        confirmButtonText: hasTools ? '移动并删除' : '删除分类',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  const result = await store.deleteCategory({ categoryId: category.id, moveToolsToOther: hasTools })
  if (!result.success) ElMessage.error(result.error || '分类删除失败')
}

async function openExisting(toolId: string): Promise<void> {
  const tool = tools.value.find((item) => item.id === toolId)
  if (tool) {
    activeTab.value = 'all'
    openEditor(tool)
  }
}

async function reorderCategories(ids: string[]): Promise<void> {
  const result = await store.reorderCategories(ids)
  if (!result.success) ElMessage.error(result.error || '分类排序失败')
}
</script>

<template>
  <section class="tool-collection">
    <el-alert
      v-if="!isDesktop"
      title="第三方工具启动仅支持 NetConsole 桌面版"
      type="warning"
      :closable="false"
      show-icon
    />
    <template v-else>
      <header class="collection-header">
        <div>
          <h1>工具集</h1>
          <p>集中管理并启动本机第三方运维工具，工具路径仅保存在当前电脑。</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="openEditor()">添加工具</el-button>
          <el-dropdown @command="addSystemReference">
            <el-button :icon="Connection">添加系统已配置工具</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="securecrt">SecureCRT</el-dropdown-item>
                <el-dropdown-item command="xshell">Xshell</el-dropdown-item>
                <el-dropdown-item command="putty">PuTTY</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button :icon="Setting" @click="categoryVisible = true">管理分类</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="store.refresh(true)">刷新状态</el-button>
        </div>
      </header>

      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />

      <div class="collection-controls">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="所有工具" name="all" />
          <el-tab-pane label="收藏与常用" name="favorites" />
        </el-tabs>
        <el-input v-model="search" :prefix-icon="Search" clearable placeholder="搜索工具名称、分类或可执行文件名" />
      </div>

      <div v-loading="loading" class="collection-content">
        <el-empty v-if="!loading && tools.length === 0" description="尚未添加第三方工具">
          <el-button type="primary" @click="openEditor()">添加第一个工具</el-button>
        </el-empty>

        <template v-else-if="activeTab === 'all'">
          <el-empty v-if="groupedTools.length === 0" description="没有符合搜索条件的工具" />
          <section v-for="group in groupedTools" :key="group.category.id" class="tool-group">
            <div class="group-heading">
              <h2>{{ group.category.name }}</h2>
              <span>{{ group.tools.length }} 个工具</span>
            </div>
            <div class="tool-grid">
              <ExternalToolCard
                v-for="tool in group.tools"
                :key="tool.id"
                :tool="tool"
                :launching="launchingIds.has(tool.id)"
                @launch="launchTool"
                @launch-admin="(item) => launchTool(item, 'administrator')"
                @favorite="toggleFavorite"
                @edit="openEditor"
                @relocate="(item) => openEditor(item, true)"
                @reveal="revealTool"
                @remove="removeTool"
                @configure="configureSystemTool"
              />
            </div>
          </section>
        </template>

        <template v-else>
          <section class="tool-group">
            <div class="group-heading"><h2>收藏工具</h2><span>{{ visibleFavoriteTools.length }} 个</span></div>
            <el-empty v-if="visibleFavoriteTools.length === 0" description="尚未收藏工具" :image-size="64" />
            <div v-else class="tool-grid">
              <ExternalToolCard
                v-for="tool in visibleFavoriteTools"
                :key="tool.id"
                :tool="tool"
                :launching="launchingIds.has(tool.id)"
                @launch="launchTool" @favorite="toggleFavorite" @edit="openEditor"
                @launch-admin="(item) => launchTool(item, 'administrator')"
                @relocate="(item) => openEditor(item, true)" @reveal="revealTool" @remove="removeTool"
                @configure="configureSystemTool"
              />
            </div>
          </section>
          <section class="tool-group">
            <div class="group-heading"><h2>最近 / 常用</h2><span>最多 12 个</span></div>
            <el-empty v-if="visibleCommonTools.length === 0" description="启动工具后将在此显示" :image-size="64" />
            <div v-else class="tool-grid">
              <ExternalToolCard
                v-for="tool in visibleCommonTools"
                :key="tool.id"
                :tool="tool"
                :launching="launchingIds.has(tool.id)"
                @launch="launchTool" @favorite="toggleFavorite" @edit="openEditor"
                @launch-admin="(item) => launchTool(item, 'administrator')"
                @relocate="(item) => openEditor(item, true)" @reveal="revealTool" @remove="removeTool"
                @configure="configureSystemTool"
              />
            </div>
          </section>
        </template>
      </div>

      <ExternalToolEditorDialog
        ref="editor"
        v-model="editorVisible"
        :tool="editingTool"
        :categories="categories"
        :relocate-on-open="relocateOnOpen"
        @save="saveTool"
        @create-category="promptCreateCategory"
        @open-existing="openExisting"
      />
      <ExternalToolCategoryDialog
        v-model="categoryVisible"
        :categories="categories"
        :tools="tools"
        @create="promptCreateCategory"
        @rename="promptRenameCategory"
        @remove="removeCategory"
        @reorder="reorderCategories"
      />
    </template>
  </section>
</template>

<style scoped>
.tool-collection { height: 100%; min-height: 0; padding: 20px 24px 28px; overflow: auto; box-sizing: border-box; }
.collection-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
.collection-header h1 { margin: 0 0 6px; font-size: 24px; }
.collection-header p { margin: 0; color: var(--el-text-color-secondary); }
.header-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; }
.collection-controls { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(280px, 420px); align-items: end; gap: 24px; margin-top: 16px; }
.collection-controls :deep(.el-tabs__header) { margin-bottom: 0; }
.collection-content { min-height: 320px; padding-top: 20px; }
.tool-group + .tool-group { margin-top: 28px; }
.group-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.group-heading h2 { margin: 0; font-size: 17px; }
.group-heading span { color: var(--el-text-color-secondary); font-size: 12px; }
.tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
@media (max-width: 900px) {
  .collection-header { flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .collection-controls { grid-template-columns: 1fr; }
}
</style>
