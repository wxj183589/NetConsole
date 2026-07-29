<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  formatExternalToolArguments,
  splitExternalToolArguments,
  selectExternalToolExecutable,
  selectExternalToolIcon,
  selectExternalToolWorkingDirectory,
} from '../../../api/externalTools'
import type {
  ExternalToolCategory,
  ExternalToolCreateRequest,
  ExternalToolIconMode,
  ExternalToolUpdateRequest,
  ExternalToolView,
} from '../../../types/externalTools'

const props = defineProps<{
  modelValue: boolean
  tool?: ExternalToolView | null
  categories: ExternalToolCategory[]
  relocateOnOpen?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [request: ExternalToolCreateRequest | ExternalToolUpdateRequest, launch: boolean]
  'create-category': [name: string]
  'open-existing': [toolId: string]
}>()

const saving = ref(false)
const dirty = ref(false)
const resetting = ref(false)
const iconPreview = ref('')
const form = reactive({
  name: '',
  executablePath: '',
  argumentsText: '',
  workingDirectory: '',
  categoryId: '',
  favorite: false,
  iconMode: 'auto' as ExternalToolIconMode,
  iconSelectionId: '',
})

const title = computed(() => props.tool ? '编辑工具' : '添加工具')

watch(() => props.modelValue, async (visible) => {
  if (!visible) return
  reset()
  if (props.relocateOnOpen) await chooseExecutable()
}, { immediate: true })
watch(form, () => {
  if (props.modelValue && !resetting.value && !saving.value) dirty.value = true
}, { deep: true })

function reset(): void {
  resetting.value = true
  const other = props.categories.find((category) => category.name === '其他工具') || props.categories[0]
  Object.assign(form, props.tool ? {
    name: props.tool.name,
    executablePath: props.tool.executable_path,
    argumentsText: formatExternalToolArguments(props.tool.arguments),
    workingDirectory: props.tool.working_directory,
    categoryId: props.tool.category_id,
    favorite: props.tool.favorite,
    iconMode: props.tool.icon_mode,
    iconSelectionId: '',
  } : {
    name: '',
    executablePath: '',
    argumentsText: '',
    workingDirectory: '',
    categoryId: other?.id || '',
    favorite: false,
    iconMode: 'auto',
    iconSelectionId: '',
  })
  iconPreview.value = props.tool?.icon_data_url || ''
  saving.value = false
  dirty.value = false
  queueMicrotask(() => {
    resetting.value = false
    dirty.value = false
  })
}

async function chooseExecutable(): Promise<void> {
  let result: Awaited<ReturnType<typeof selectExternalToolExecutable>>
  try {
    result = await selectExternalToolExecutable()
  } catch (cause) {
    return void ElMessage.error(cause instanceof Error ? cause.message : '程序选择失败')
  }
  if (result.cancelled || !result.path) return
  if (result.duplicateTool && result.duplicateTool.id !== props.tool?.id) {
    try {
      await ElMessageBox.confirm(
        `该程序已经添加为「${result.duplicateTool.name}」。`,
        '程序已添加',
        { confirmButtonText: '打开现有工具', cancelButtonText: '取消', type: 'warning' },
      )
      emit('update:modelValue', false)
      queueMicrotask(() => emit('open-existing', result.duplicateTool!.id))
    } catch {
      // 用户取消。
    }
    return
  }
  form.executablePath = result.path
  form.workingDirectory = result.workingDirectory || ''
  if (!props.tool || !form.name.trim()) form.name = result.suggestedName || ''
  if (form.iconMode === 'auto') iconPreview.value = result.iconDataUrl || ''
  dirty.value = true
}

async function chooseWorkingDirectory(): Promise<void> {
  let result: Awaited<ReturnType<typeof selectExternalToolWorkingDirectory>>
  try {
    result = await selectExternalToolWorkingDirectory()
  } catch (cause) {
    return void ElMessage.error(cause instanceof Error ? cause.message : '目录选择失败')
  }
  if (!result.cancelled && result.path) {
    form.workingDirectory = result.path
    dirty.value = true
  }
}

async function chooseIcon(): Promise<void> {
  let result: Awaited<ReturnType<typeof selectExternalToolIcon>>
  try {
    result = await selectExternalToolIcon()
  } catch (cause) {
    return void ElMessage.error(cause instanceof Error ? cause.message : '图标选择失败')
  }
  if (result.cancelled || !result.selectionId) return
  form.iconMode = 'custom'
  form.iconSelectionId = result.selectionId
  iconPreview.value = result.iconDataUrl || ''
  dirty.value = true
}

function quickCreateCategory(): void {
  ElMessageBox.prompt('请输入分类名称', '新增分类', {
    confirmButtonText: '新增',
    cancelButtonText: '取消',
    inputPattern: /^.{1,80}$/,
    inputErrorMessage: '分类名称为 1–80 个字符',
  }).then(({ value }) => emit('create-category', value.trim())).catch(() => undefined)
}

async function submit(launch: boolean): Promise<void> {
  if (!form.name.trim()) return void ElMessage.warning('请输入工具名称')
  if (!form.executablePath) return void ElMessage.warning('请选择程序')
  if (!form.categoryId) return void ElMessage.warning('请选择分类')
  let arguments_: string[]
  try {
    arguments_ = splitExternalToolArguments(form.argumentsText)
  } catch (cause) {
    return void ElMessage.warning(cause instanceof Error ? cause.message : '启动参数无效')
  }
  if (form.iconMode === 'custom' && !form.iconSelectionId && props.tool?.icon_mode !== 'custom') {
    return void ElMessage.warning('请选择自定义图标')
  }
  saving.value = true
  const base: ExternalToolCreateRequest = {
    name: form.name.trim(),
    executablePath: form.executablePath,
    arguments: arguments_,
    ...(form.workingDirectory ? { workingDirectory: form.workingDirectory } : {}),
    categoryId: form.categoryId,
    favorite: form.favorite,
    iconMode: form.iconMode,
    ...(form.iconSelectionId ? { iconSelectionId: form.iconSelectionId } : {}),
  }
  emit('save', props.tool ? { id: props.tool.id, ...base } : base, launch)
}

function markSaved(success: boolean): void {
  saving.value = false
  if (success) {
    dirty.value = false
    emit('update:modelValue', false)
  }
}

async function beforeClose(done: () => void): Promise<void> {
  if (!dirty.value || saving.value) return done()
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确定关闭吗？', '放弃修改', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    done()
  } catch {
    // 继续编辑。
  }
}

function requestClose(): void {
  void beforeClose(() => emit('update:modelValue', false))
}

defineExpose({ markSaved, chooseExecutable, submit, form })
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="680px"
    destroy-on-close
    :before-close="beforeClose"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form label-position="top" @change="dirty = true">
      <el-form-item label="工具名称" required>
        <el-input v-model="form.name" maxlength="80" show-word-limit data-testid="tool-name" />
      </el-form-item>
      <el-form-item label="程序路径" required>
        <el-input v-model="form.executablePath" readonly data-testid="tool-executable">
          <template #append><el-button @click="chooseExecutable">选择程序</el-button></template>
        </el-input>
      </el-form-item>
      <div class="editor-grid">
        <el-form-item label="分类" required>
          <el-select v-model="form.categoryId" style="width:100%">
            <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
            <template #footer><el-button text type="primary" @click="quickCreateCategory">+ 新增分类</el-button></template>
          </el-select>
        </el-form-item>
        <el-form-item label="收藏">
          <el-switch v-model="form.favorite" active-text="加入收藏" />
        </el-form-item>
      </div>
      <el-form-item label="启动参数">
        <el-input v-model="form.argumentsText" placeholder='示例：--profile "现场维护"' data-testid="tool-arguments" />
        <div class="field-help">按 argv 保存；不支持管道、重定向、&& 或 ||。</div>
      </el-form-item>
      <el-form-item label="工作目录">
        <el-input v-model="form.workingDirectory" readonly placeholder="留空时使用 EXE 所在目录">
          <template #append><el-button @click="chooseWorkingDirectory">选择目录</el-button></template>
        </el-input>
      </el-form-item>
      <el-form-item label="图标">
        <div class="icon-editor">
          <div class="icon-preview"><img v-if="iconPreview" :src="iconPreview" alt="" /></div>
          <el-radio-group v-model="form.iconMode" @change="dirty = true">
            <el-radio-button value="auto">自动读取</el-radio-button>
            <el-radio-button value="default">默认图标</el-radio-button>
            <el-radio-button value="custom">自定义图标</el-radio-button>
          </el-radio-group>
          <el-button @click="chooseIcon">选择自定义图标</el-button>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="saving" @click="requestClose">取消</el-button>
      <el-button :loading="saving" @click="submit(false)">保存</el-button>
      <el-button type="primary" :loading="saving" @click="submit(true)">保存并启动</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.editor-grid { display: grid; grid-template-columns: minmax(0, 1fr) 180px; gap: 16px; }
.field-help { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 5px; }
.icon-editor { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.icon-preview { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 8px; background: var(--el-fill-color-light); }
.icon-preview img { max-width: 34px; max-height: 34px; }
@media (max-width: 720px) { .editor-grid { grid-template-columns: 1fr; } }
</style>
