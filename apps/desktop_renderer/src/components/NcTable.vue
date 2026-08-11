<script setup lang="ts">
import { ref } from 'vue'

defineOptions({ inheritAttrs: false })

withDefaults(defineProps<{
  data?: unknown[]
  height?: string | number
  maxHeight?: string | number
  emptyText?: string
  stripe?: boolean
  border?: boolean
  compact?: boolean
}>(), {
  data: () => [],
  height: undefined,
  maxHeight: undefined,
  emptyText: '暂无数据',
  stripe: true,
  border: false,
  compact: false,
})

const tableRef = ref()

defineExpose({ tableRef })
</script>

<template>
  <div :class="['nc-table', { 'nc-table--compact': compact }]">
    <el-table
      ref="tableRef"
      v-bind="$attrs"
      :data="data"
      :height="height"
      :max-height="maxHeight"
      :empty-text="emptyText"
      :stripe="stripe"
      :border="border"
    >
      <slot />
      <template v-if="$slots.empty" #empty><slot name="empty" /></template>
      <template v-if="$slots.append" #append><slot name="append" /></template>
    </el-table>
  </div>
</template>

<style scoped>
.nc-table { min-width: 0; width: 100%; overflow-x: auto; }
.nc-table :deep(.el-table) { min-width: 100%; color: var(--nc-text-primary); font-size: var(--nc-font-size-base); }
.nc-table :deep(.el-table__header th.el-table__cell) { height: var(--nc-table-row-height); padding: 0; background: var(--nc-table-header-bg); color: var(--nc-text-secondary); font-weight: 600; }
.nc-table :deep(.el-table__body td.el-table__cell) { height: var(--nc-table-row-height); padding: 0; }
.nc-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: var(--nc-table-hover-bg); }
.nc-table :deep(.el-table__body tr.current-row > td.el-table__cell) { background: var(--nc-table-selected-bg); }
.nc-table--compact :deep(.el-table__header th.el-table__cell),
.nc-table--compact :deep(.el-table__body td.el-table__cell) { height: 34px; }
</style>
