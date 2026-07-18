<script setup lang="ts" generic="Row extends Record<string, unknown>">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { t } from '../../i18n/runtime'
import NcColumnSettings, { type NcColumnSettingItem } from './NcColumnSettings.vue'
import NcTableCell from './NcTableCell.vue'
import {
  normalizeNcTableColumn,
  readTableCellValue,
  safeNcTableColumnAttrs,
  type NcTableColumn,
  type ResolvedNcTableColumn,
} from './NcTableColumn'
import {
  clearTablePreferences,
  loadTablePreferences,
  saveTablePreferences,
  type NcTablePreferences,
} from './tablePreferences'
import { calculateTableColumnWidths, useAutoColumnWidth } from './useAutoColumnWidth'
import { clearTextMeasurementCache } from './textMeasurement'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  data?: readonly Row[]
  columns: readonly NcTableColumn<Row>[]
  tableId: string
  routeKey: string
  userKey?: string
  language?: string
  height?: string | number
  maxHeight?: string | number
  emptyText?: string
  rowKey?: string | ((row: Row) => string)
  stripe?: boolean
  border?: boolean
  compact?: boolean
  showColumnSettings?: boolean
  sampleLimit?: number
}>(), {
  data: () => [],
  userKey: 'local-user',
  language: '',
  height: undefined,
  maxHeight: undefined,
  emptyText: '',
  rowKey: undefined,
  stripe: true,
  border: false,
  compact: false,
  showColumnSettings: true,
  sampleLimit: 200,
})

const emit = defineEmits<{
  'header-dragend': [newWidth: number, oldWidth: number, column: unknown, event: MouseEvent]
}>()

const tableRef = ref()
const containerRef = ref<HTMLElement>()
const displayRevision = ref(0)
const bodyFont = ref('400 14px "Microsoft YaHei UI", sans-serif')
const headerFont = ref('600 14px "Microsoft YaHei UI", sans-serif')
const currentLanguage = ref(props.language || (typeof document === 'undefined' ? 'zh-CN' : document.documentElement.lang || 'zh-CN'))
const preferences = ref<NcTablePreferences>()
const manualWidths = ref<Record<string, number>>({})
let rootObserver: MutationObserver | undefined
let resizeObserver: ResizeObserver | undefined

const identity = computed(() => ({
  userKey: props.userKey,
  routeKey: props.routeKey,
  tableId: props.tableId,
  language: currentLanguage.value,
}))
const resolvedEmptyText = computed(() => props.emptyText || t('table.no_data', '暂无数据'))

watch(() => props.language, (language) => {
  if (language) currentLanguage.value = language
})

watch(identity, () => {
  preferences.value = loadTablePreferences(identity.value)
  manualWidths.value = Object.fromEntries(
    (preferences.value?.columns ?? []).flatMap((column) => column.width == null ? [] : [[column.key, column.width]]),
  )
}, { immediate: true })

const resolvedColumns = computed<ResolvedNcTableColumn<Row>[]>(() => {
  const normalized = props.columns.map(normalizeNcTableColumn)
  const preferenceByKey = new Map((preferences.value?.columns ?? []).map((item) => [item.key, item]))
  const order = new Map((preferences.value?.order ?? []).map((key, index) => [key, index]))
  return normalized
    .map((column, sourceIndex) => {
      const saved = preferenceByKey.get(column.key)
      return {
        ...column,
        visible: saved?.visible ?? column.visible,
        fixed: saved?.fixed == null ? column.fixed : saved.fixed,
        sourceIndex,
      }
    })
    .sort((left, right) => (order.get(left.key) ?? 10000 + left.sourceIndex) - (order.get(right.key) ?? 10000 + right.sourceIndex))
})

const visibleColumns = computed(() => resolvedColumns.value.filter((column) => column.visible))
const rows = computed(() => props.data)
const sizingColumns = computed(() => visibleColumns.value as readonly NcTableColumn<Row>[])
const { widths, recalculate, schedule } = useAutoColumnWidth({
  columns: sizingColumns,
  rows,
  manualWidths,
  revision: displayRevision,
  sampleLimit: props.sampleLimit,
  bodyFont,
  headerFont,
})

const settingColumns = computed<NcColumnSettingItem[]>(() => resolvedColumns.value.map((column) => ({
  key: column.key,
  label: column.label,
  visible: column.visible,
  hideable: column.hideable,
  fixed: column.fixed === 'left' || column.fixed === 'right' ? column.fixed : false,
})))

function cellValue(row: Row, column: ResolvedNcTableColumn<Row>, index: number): unknown {
  return readTableCellValue(row, column, index)
}

function persist(nextColumns = resolvedColumns.value): void {
  const next: NcTablePreferences = {
    version: 1,
    order: nextColumns.map((column) => column.key),
    columns: nextColumns.map((column) => ({
      key: column.key,
      width: manualWidths.value[column.key],
      visible: column.visible,
      fixed: column.fixed === 'left' || column.fixed === 'right' ? column.fixed : false,
    })),
  }
  preferences.value = next
  saveTablePreferences(identity.value, next)
}

function updatePreferenceColumns(update: (columns: NcTablePreferences['columns']) => void): void {
  const next: NcTablePreferences = preferences.value
    ? structuredClone(preferences.value)
    : {
        version: 1,
        order: resolvedColumns.value.map((column) => column.key),
        columns: resolvedColumns.value.map((column) => ({
          key: column.key,
          visible: column.visible,
          fixed: column.fixed === 'left' || column.fixed === 'right' ? column.fixed : false,
        })),
      }
  update(next.columns)
  preferences.value = next
  saveTablePreferences(identity.value, next)
}

function toggleColumn(key: string, visible: boolean): void {
  if (!visible && visibleColumns.value.length <= 1) return
  updatePreferenceColumns((columns) => {
    const target = columns.find((column) => column.key === key)
    if (target) target.visible = visible
  })
}

function moveColumn(key: string, direction: -1 | 1): void {
  const order = resolvedColumns.value.map((column) => column.key)
  const index = order.indexOf(key)
  const target = index + direction
  if (index < 0 || target < 0 || target >= order.length) return
  ;[order[index], order[target]] = [order[target], order[index]]
  const next = preferences.value ?? { version: 1 as const, order: [], columns: [] }
  preferences.value = { ...next, order }
  saveTablePreferences(identity.value, preferences.value)
}

function cyclePin(key: string): void {
  updatePreferenceColumns((columns) => {
    const target = columns.find((column) => column.key === key)
    if (!target) return
    target.fixed = target.fixed === 'left' ? 'right' : target.fixed === 'right' ? false : 'left'
  })
}

function resetLayout(): void {
  clearTablePreferences(identity.value)
  preferences.value = undefined
  manualWidths.value = {}
  recalculate(true)
}

function autoFit(): void {
  manualWidths.value = {}
  persist()
  recalculate(true)
}

function handleHeaderDragEnd(newWidth: number, oldWidth: number, column: { columnKey?: string }, event: MouseEvent): void {
  const key = column.columnKey
  if (key) {
    const target = resolvedColumns.value.find((item) => item.key === key)
    if (target) {
      const clamped = calculateTableColumnWidths({
        columns: [target],
        rows: props.data,
        manualWidths: { [key]: newWidth },
        sampleLimit: props.sampleLimit,
      })[key]
      manualWidths.value = { ...manualWidths.value, [key]: clamped }
      persist()
    }
  }
  emit('header-dragend', newWidth, oldWidth, column, event)
}

function refreshFonts(): void {
  const element = containerRef.value
  if (!element || typeof getComputedStyle === 'undefined') return
  const style = getComputedStyle(element)
  const family = style.fontFamily || '"Microsoft YaHei UI", sans-serif'
  const size = style.fontSize || '14px'
  bodyFont.value = `${style.fontWeight || '400'} ${size} ${family}`
  headerFont.value = `600 ${size} ${family}`
}

function handleViewportChange(): void {
  refreshFonts()
  clearTextMeasurementCache()
  displayRevision.value += 1
  schedule()
}

onMounted(() => {
  if (typeof document === 'undefined') return
  refreshFonts()
  rootObserver = new MutationObserver((records) => {
    const languageChanged = records.some((record) => record.attributeName === 'lang')
    if (languageChanged && !props.language) currentLanguage.value = document.documentElement.lang || 'zh-CN'
    handleViewportChange()
  })
  rootObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style', 'data-theme', 'lang'] })
  void document.fonts?.ready.then(() => {
    handleViewportChange()
  })
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(handleViewportChange)
    resizeObserver.observe(containerRef.value)
  }
  window.addEventListener('resize', handleViewportChange)
})

onBeforeUnmount(() => {
  rootObserver?.disconnect()
  resizeObserver?.disconnect()
  window.removeEventListener('resize', handleViewportChange)
})

defineExpose({ tableRef, recalculate, resetLayout, autoFit })
</script>

<template>
  <div ref="containerRef" :class="['nc-data-table', { 'nc-data-table--compact': compact }]">
    <div v-if="showColumnSettings || $slots.tools" class="nc-data-table__tools">
      <slot name="tools" />
      <NcColumnSettings
        v-if="showColumnSettings"
        :columns="settingColumns"
        @toggle="toggleColumn"
        @move="moveColumn"
        @pin="cyclePin"
        @reset="resetLayout"
        @autofit="autoFit"
      />
    </div>
    <div class="nc-data-table__scroll">
      <el-table
        ref="tableRef"
        v-bind="$attrs"
        :data="data"
        :height="height"
        :max-height="maxHeight"
        :empty-text="resolvedEmptyText"
        :row-key="rowKey"
        :stripe="stripe"
        :border="border"
        :fit="true"
        @header-dragend="handleHeaderDragEnd"
      >
        <template v-for="column in visibleColumns" :key="column.key">
          <el-table-column
            v-if="column.type"
            v-bind="safeNcTableColumnAttrs(column.columnAttrs)"
            :type="column.type"
            :column-key="column.key"
            :label="column.label"
            :width="widths[column.key]"
            :align="column.align"
            :header-align="column.headerAlign"
            :fixed="column.fixed"
            :sortable="column.sortable"
          />
          <el-table-column
            v-else
            v-bind="safeNcTableColumnAttrs(column.columnAttrs)"
            :prop="column.prop"
            :column-key="column.key"
            :label="column.label"
            :width="widths[column.key]"
            :align="column.align"
            :header-align="column.headerAlign"
            :fixed="column.fixed"
            :sortable="column.sortable"
          >
            <template #header="scope">
              <slot :name="`header-${column.key}`" v-bind="scope">{{ column.label }}</slot>
            </template>
            <template #default="scope">
              <slot :name="`cell-${column.key}`" v-bind="scope" :column-definition="column">
                <NcTableCell
                  :value="cellValue(scope.row, column, scope.$index)"
                  :align="column.align"
                  :tooltip="column.showOverflowTooltip"
                />
              </slot>
            </template>
          </el-table-column>
        </template>
        <template v-if="$slots.empty" #empty><slot name="empty" /></template>
        <template v-if="$slots.append" #append><slot name="append" /></template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.nc-data-table { min-width: 0; width: 100%; overflow: hidden; }
.nc-data-table__tools { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-height: 34px; padding: 0 0 8px; }
.nc-data-table__scroll { min-width: 0; overflow: auto; }
.nc-data-table :deep(.el-table) { min-width: 100%; color: var(--nc-text-primary); font-size: var(--nc-font-size-base); }
.nc-data-table :deep(.el-table__header th.el-table__cell) { height: var(--nc-table-row-height); padding: 0; background: var(--nc-table-header-bg); color: var(--nc-text-secondary); font-weight: 600; text-align: center; }
.nc-data-table :deep(.el-table__body td.el-table__cell) { height: var(--nc-table-row-height); padding: 0; vertical-align: middle; }
.nc-data-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: var(--nc-table-hover-bg); }
.nc-data-table :deep(.el-table__body tr.current-row > td.el-table__cell) { background: var(--nc-table-selected-bg); }
.nc-data-table--compact :deep(.el-table__header th.el-table__cell),
.nc-data-table--compact :deep(.el-table__body td.el-table__cell) { height: 34px; }
</style>
