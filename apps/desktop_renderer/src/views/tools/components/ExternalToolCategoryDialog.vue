<script setup lang="ts">
import { ArrowDown, ArrowUp, Delete, Edit } from '@element-plus/icons-vue'
import type { ExternalToolCategory, ExternalToolView } from '../../../types/externalTools'

const props = defineProps<{
  modelValue: boolean
  categories: ExternalToolCategory[]
  tools: ExternalToolView[]
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  create: []
  rename: [category: ExternalToolCategory]
  remove: [category: ExternalToolCategory]
  reorder: [categoryIds: string[]]
}>()

function move(index: number, direction: -1 | 1): void {
  const next = props.categories.map((category) => category.id)
  const target = index + direction
  if (target < 0 || target >= next.length) return
  ;[next[index], next[target]] = [next[target], next[index]]
  emit('reorder', next)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="管理分类"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="category-toolbar">
      <span>分类顺序决定“所有工具”的分组顺序。</span>
      <el-button type="primary" @click="emit('create')">新增分类</el-button>
    </div>
    <div class="category-list">
      <div v-for="(category, index) in categories" :key="category.id" class="category-row">
        <div>
          <strong>{{ category.name }}</strong>
          <span>{{ tools.filter((tool) => tool.category_id === category.id).length }} 个工具</span>
        </div>
        <div>
          <el-button text circle :icon="ArrowUp" :disabled="index === 0" aria-label="上移" @click="move(index, -1)" />
          <el-button text circle :icon="ArrowDown" :disabled="index === categories.length - 1" aria-label="下移" @click="move(index, 1)" />
          <el-button text circle :icon="Edit" aria-label="重命名" @click="emit('rename', category)" />
          <el-button text circle :icon="Delete" :disabled="category.name === '其他工具'" aria-label="删除分类" @click="emit('remove', category)" />
        </div>
      </div>
    </div>
    <template #footer><el-button @click="emit('update:modelValue', false)">完成</el-button></template>
  </el-dialog>
</template>

<style scoped>
.category-toolbar, .category-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.category-toolbar { margin-bottom: 14px; color: var(--el-text-color-secondary); }
.category-list { display: grid; gap: 8px; max-height: 52vh; overflow: auto; }
.category-row { padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; }
.category-row strong { margin-right: 10px; }
.category-row span { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
