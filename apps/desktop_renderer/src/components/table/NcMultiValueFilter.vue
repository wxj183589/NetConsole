<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string[]
  options: readonly string[]
  placeholder?: string
  disabled?: boolean
  labels?: Readonly<Record<string, string>>
}>(), { placeholder: '全部', disabled: false })
const emit = defineEmits<{ 'update:modelValue': [values: string[]]; change: [values: string[]] }>()

const visible = ref(false)
const search = ref('')
const draft = ref<string[]>([])
const uniqueOptions = computed(() => [...new Set(props.options.filter(Boolean))])
const matchingOptions = computed(() => uniqueOptions.value.filter((option) => (
  (props.labels?.[option] || option).toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
  || option.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
)))
const selectedCount = computed(() => props.modelValue.length || uniqueOptions.value.length)
const caption = computed(() => {
  if (!props.modelValue.length) return props.placeholder
  if (props.modelValue.length === 1) return props.labels?.[props.modelValue[0]] || props.modelValue[0]
  return `已选 ${props.modelValue.length} 项`
})

watch(visible, (opened) => {
  if (!opened) return
  draft.value = props.modelValue.length ? [...props.modelValue] : [...uniqueOptions.value]
  search.value = ''
})

function selectVisible(): void {
  draft.value = [...new Set([...draft.value, ...matchingOptions.value])]
}
function invertVisible(): void {
  const selected = new Set(draft.value)
  for (const option of matchingOptions.value) {
    if (selected.has(option)) selected.delete(option)
    else selected.add(option)
  }
  draft.value = [...selected]
}
function apply(): void {
  const selected = uniqueOptions.value.filter((option) => draft.value.includes(option))
  if (!selected.length) return
  const normalized = selected.length === uniqueOptions.value.length ? [] : selected
  emit('update:modelValue', normalized)
  emit('change', normalized)
  visible.value = false
}
</script>

<template>
  <el-popover v-model:visible="visible" trigger="click" placement="bottom-start" :width="310" :disabled="disabled" popper-class="nc-multi-value-filter-popover">
    <template #reference>
      <el-button class="nc-multi-value-filter" :disabled="disabled" :title="caption" :aria-label="placeholder">
        <span class="nc-multi-value-filter__caption">{{ caption }}</span>
        <span class="nc-multi-value-filter__count">{{ selectedCount }}/{{ uniqueOptions.length }}</span>
        <span aria-hidden="true">⌄</span>
      </el-button>
    </template>
    <div class="nc-multi-value-filter__panel">
      <el-input v-model="search" size="small" clearable placeholder="搜索选项" aria-label="搜索选项" />
      <div class="nc-multi-value-filter__actions">
        <el-button link size="small" @click="selectVisible">全选</el-button>
        <el-button link size="small" @click="invertVisible">反选</el-button>
        <el-button link size="small" @click="draft = [...uniqueOptions]">恢复全部</el-button>
      </div>
      <div class="nc-multi-value-filter__list" role="group" :aria-label="placeholder">
        <el-checkbox-group v-model="draft" class="nc-multi-value-filter__group">
          <el-checkbox v-for="option in matchingOptions" :key="option" :value="option">{{ labels?.[option] || option }}</el-checkbox>
        </el-checkbox-group>
        <el-empty v-if="!matchingOptions.length" description="没有匹配项" :image-size="42" />
      </div>
      <div class="nc-multi-value-filter__footer">
        <el-button size="small" @click="visible = false">取消</el-button>
        <el-button type="primary" size="small" :disabled="!draft.length" @click="apply">确定</el-button>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.nc-multi-value-filter{width:100%;justify-content:space-between;min-width:140px}
.nc-multi-value-filter__caption{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nc-multi-value-filter__count{color:var(--el-text-color-secondary);font-size:11px;margin-left:auto;padding:0 8px}
.nc-multi-value-filter__panel{display:grid;gap:8px}
.nc-multi-value-filter__actions{display:flex;gap:5px;border-bottom:1px solid var(--el-border-color-lighter);padding-bottom:5px}
.nc-multi-value-filter__list{display:flex;flex-direction:column;max-height:265px;overflow-y:auto}
.nc-multi-value-filter__group{display:flex;flex-direction:column}
.nc-multi-value-filter__list .el-checkbox{margin:0;padding:4px 5px;min-height:28px}
.nc-multi-value-filter__footer{display:flex;justify-content:flex-end;border-top:1px solid var(--el-border-color-lighter);padding-top:8px}
</style>
