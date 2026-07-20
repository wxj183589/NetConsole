<script setup lang="ts" generic="Row extends object">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { t } from '../../i18n/runtime'
import NcColumnSettings, { type NcColumnSettingItem } from './NcColumnSettings.vue'
import NcTableCell from './NcTableCell.vue'
import {
  normalizeNcTableColumn,
  readTableCellValue,
  safeNcTableColumnAttrs,
  type NcTableEmptySpaceStrategy,
  type NcTableColumn,
  type ResolvedNcTableColumn,
} from './NcTableColumn'
import {
  clearTablePreferencesAsync,
  loadTablePreferences,
  loadTablePreferencesAsync,
  normalizeTablePreferences,
  saveTablePreferencesAsync,
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
  preferenceScope?: string
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
  emptySpaceStrategy?: NcTableEmptySpaceStrategy
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
  emptySpaceStrategy: 'stretch',
})

const emit = defineEmits<{
  'header-dragend': [newWidth: number, oldWidth: number, column: unknown, event: MouseEvent]
}>()

const tableRef = ref()
const containerRef = ref<HTMLElement>()
const scrollRef = ref<HTMLElement>()
const availableWidth = ref(0)
const displayRevision = ref(0)
const bodyFont = ref('400 14px "Microsoft YaHei UI", sans-serif')
const headerFont = ref('600 14px "Microsoft YaHei UI", sans-serif')
const currentLanguage = ref(props.language || documentLanguage())
const preferences = ref<NcTablePreferences>()
const manualWidths = ref<Record<string, number>>({})
const columnLayoutRevision = ref(0)
const preferenceMutationRevision = ref(0)
const preferenceSaveState = ref<'saved' | 'saving' | 'error'>('saved')
let rootObserver: MutationObserver | undefined
let resizeObserver: ResizeObserver | undefined
let preferenceLoadGeneration = 0
let preferenceSaveGeneration = 0

function documentLanguage(): string {
  return typeof document !== 'undefined' && document.documentElement?.lang
    ? document.documentElement.lang
    : 'zh-CN'
}

const identity = computed(() => ({
  userKey: props.userKey,
  routeKey: props.routeKey,
  tableId: props.preferenceScope ? `${props.tableId}:${props.preferenceScope}` : props.tableId,
  language: currentLanguage.value,
}))
const resolvedEmptyText = computed(() => props.emptyText || t('table.no_data', '暂无数据'))

watch(() => props.language, (language) => {
  if (language) currentLanguage.value = language
})

const normalizedColumns = computed(() => props.columns.map(normalizeNcTableColumn))

function normalizeCurrentPreference(value?: NcTablePreferences | null): NcTablePreferences {
  return normalizeTablePreferences(normalizedColumns.value, value)
}

function applyLoadedPreference(value: NcTablePreferences | undefined): NcTablePreferences {
  const next = normalizeCurrentPreference(value)
  preferences.value = next
  manualWidths.value = Object.fromEntries(
    next.columns.flatMap((column) => column.width == null ? [] : [[column.key, column.width]]),
  )
  return next
}

function samePreference(left: NcTablePreferences, right: NcTablePreferences): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

watch(identity, (nextIdentity) => {
  const generation = ++preferenceLoadGeneration
  const mutationRevision = preferenceMutationRevision.value
  const apply = (next: NcTablePreferences | undefined, persistNormalized = false) => {
    if (generation !== preferenceLoadGeneration) return
    if (preferenceMutationRevision.value !== mutationRevision) return
    const normalized = applyLoadedPreference(next)
    if (persistNormalized && next && !samePreference(next, normalized)) persistPreference(normalized)
  }
  apply(loadTablePreferences(nextIdentity))
  void loadTablePreferencesAsync(nextIdentity).then((next) => apply(next, true))
}, { immediate: true })

const resolvedColumns = computed<ResolvedNcTableColumn<Row>[]>(() => {
  const preferenceByKey = new Map((preferences.value?.columns ?? []).map((item) => [item.key, item]))
  const order = new Map((preferences.value?.order ?? []).map((key, index) => [key, index]))
  return normalizedColumns.value
    .map((column, sourceIndex) => {
      const saved = preferenceByKey.get(column.key)
      return {
        ...column,
        visible: column.hideable ? saved?.visible ?? column.visible : true,
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
  availableWidth,
  emptySpaceStrategy: props.emptySpaceStrategy,
  revision: displayRevision,
  sampleLimit: props.sampleLimit,
  bodyFont,
  headerFont,
})
const resolvedTableWidth = computed(() => Object.values(widths.value).reduce((total, width) => total + width, 0))
const tableStyle = computed(() => {
  if (!availableWidth.value || !resolvedTableWidth.value) return { width: '100%' }
  const centered = resolvedTableWidth.value < availableWidth.value
  return {
    width: `${resolvedTableWidth.value}px`,
    marginInline: centered ? 'auto' : '0',
  }
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
  const current = normalizeCurrentPreference(preferences.value)
  const nextByKey = new Map(nextColumns.map((column) => [column.key, column]))
  const next: NcTablePreferences = {
    version: 1,
    order: nextColumns.map((column) => column.key),
    columns: current.columns.map((column) => {
      const nextColumn = nextByKey.get(column.key)
      return {
        ...column,
        width: manualWidths.value[column.key],
        visible: nextColumn?.visible ?? column.visible,
        fixed: nextColumn?.fixed === 'left' || nextColumn?.fixed === 'right' ? nextColumn.fixed : false,
      }
    }),
  }
  commitPreference(next, false)
}

function persistPreference(next: NcTablePreferences): void {
  const generation = ++preferenceSaveGeneration
  preferenceSaveState.value = 'saving'
  void saveTablePreferencesAsync(identity.value, next).then(() => {
    if (generation === preferenceSaveGeneration) preferenceSaveState.value = 'saved'
  }).catch(() => {
    if (generation === preferenceSaveGeneration) {
      preferenceSaveState.value = 'error'
      ElMessage.warning('列设置保存失败，当前布局仅保留在本次运行。')
    }
  })
}

function commitPreference(value: NcTablePreferences, refresh = true): void {
  const next = normalizeCurrentPreference(value)
  preferenceMutationRevision.value += 1
  preferences.value = next
  persistPreference(next)
  if (refresh) void refreshColumnLayout(true)
}

function updatePreferenceColumns(update: (columns: NcTablePreferences['columns']) => void): void {
  const next = normalizeCurrentPreference(preferences.value)
  update(next.columns)
  commitPreference(next)
}

function toggleColumn(key: string, visible: boolean): void {
  if (!visible && visibleColumns.value.length <= 1) return
  if (!resolvedColumns.value.find((column) => column.key === key)?.hideable) return
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
  const next = normalizeCurrentPreference(preferences.value)
  commitPreference({ ...next, order })
}

function cyclePin(key: string): void {
  updatePreferenceColumns((columns) => {
    const target = columns.find((column) => column.key === key)
    if (!target) return
    target.fixed = target.fixed === 'left' ? 'right' : target.fixed === 'right' ? false : 'left'
  })
}

function resetLayout(): void {
  preferenceMutationRevision.value += 1
  const generation = ++preferenceSaveGeneration
  preferenceSaveState.value = 'saving'
  void clearTablePreferencesAsync(identity.value).then(() => {
    if (generation === preferenceSaveGeneration) preferenceSaveState.value = 'saved'
  }).catch(() => {
    if (generation === preferenceSaveGeneration) {
      preferenceSaveState.value = 'error'
      ElMessage.warning('默认列布局清理失败，请稍后重试。')
    }
  })
  preferences.value = normalizeCurrentPreference()
  manualWidths.value = {}
  void refreshColumnLayout(true)
}

function autoFit(): void {
  manualWidths.value = {}
  persist()
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

async function refreshColumnLayout(force = false): Promise<void> {
  await nextTick()
  columnLayoutRevision.value += 1
  await nextTick()
  tableRef.value?.doLayout?.()
  recalculate(force)
}

function clearSelection(): void {
  tableRef.value?.clearSelection?.()
}

function toggleRowSelection(row: Row, selected?: boolean): void {
  tableRef.value?.toggleRowSelection?.(row, selected)
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

function updateAvailableWidth(): void {
  const nextWidth = Math.max(0, Math.floor(scrollRef.value?.clientWidth ?? 0))
  if (nextWidth !== availableWidth.value) availableWidth.value = nextWidth
}

function handleViewportChange(): void {
  updateAvailableWidth()
  refreshFonts()
  clearTextMeasurementCache()
  displayRevision.value += 1
  schedule()
}

onMounted(() => {
  const rootElement = typeof document === 'undefined' ? undefined : document.documentElement
  if (!rootElement) return
  refreshFonts()
  updateAvailableWidth()
  recalculate()
  rootObserver = new MutationObserver((records) => {
    const languageChanged = records.some((record) => record.attributeName === 'lang')
    if (languageChanged && !props.language) currentLanguage.value = documentLanguage()
    handleViewportChange()
  })
  rootObserver.observe(rootElement, { attributes: true, attributeFilter: ['class', 'style', 'data-theme', 'lang'] })
  void document.fonts?.ready.then(() => {
    handleViewportChange()
  })
  if (typeof ResizeObserver !== 'undefined' && scrollRef.value) {
    resizeObserver = new ResizeObserver(handleViewportChange)
    resizeObserver.observe(scrollRef.value)
  }
  window.addEventListener?.('resize', handleViewportChange)
})

onBeforeUnmount(() => {
  rootObserver?.disconnect()
  resizeObserver?.disconnect()
  window.removeEventListener?.('resize', handleViewportChange)
})

defineExpose({ tableRef, availableWidth, resolvedTableWidth, recalculate, resetLayout, autoFit, clearSelection, toggleRowSelection })
</script>

<template>
  <div ref="containerRef" :class="['nc-data-table', { 'nc-data-table--compact': compact }]">
    <div v-if="showColumnSettings || $slots.tools" class="nc-data-table__tools">
      <slot name="tools" />
      <NcColumnSettings
        v-if="showColumnSettings"
        :columns="settingColumns"
        :preference-state="preferenceSaveState"
        @toggle="toggleColumn"
        @move="moveColumn"
        @pin="cyclePin"
        @reset="resetLayout"
        @autofit="autoFit"
      />
    </div>
    <div ref="scrollRef" class="nc-data-table__scroll">
      <el-table
        ref="tableRef"
        :key="columnLayoutRevision"
        v-bind="$attrs"
        :data="data"
        :height="height"
        :max-height="maxHeight"
        :empty-text="resolvedEmptyText"
        :row-key="rowKey"
        :stripe="stripe"
        :border="border"
        :fit="true"
        :style="tableStyle"
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
          >
            <template v-if="column.type === 'expand'" #default="scope">
              <slot :name="`cell-${column.key}`" v-bind="scope" :column-definition="column" />
            </template>
          </el-table-column>
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
.nc-data-table { display: flex; flex-direction: column; min-width: 0; width: 100%; height: 100%; overflow: hidden; }
.nc-data-table__tools { display: flex; flex: none; align-items: center; justify-content: flex-end; gap: 8px; min-height: 34px; padding: 0 0 8px; }
.nc-data-table__scroll { flex: 1; min-width: 0; overflow: auto; }
.nc-data-table :deep(.el-table) { color: var(--nc-text-primary); font-size: var(--nc-font-size-base); }
.nc-data-table :deep(.el-table__header th.el-table__cell) { height: var(--nc-table-row-height); padding: 0; background: var(--nc-table-header-bg); color: var(--nc-text-secondary); font-weight: 600; text-align: center; }
.nc-data-table :deep(.el-table__body td.el-table__cell) { height: var(--nc-table-row-height); padding: 0; vertical-align: middle; }
.nc-data-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: var(--nc-table-hover-bg); }
.nc-data-table :deep(.el-table__body tr.current-row > td.el-table__cell) { background: var(--nc-table-selected-bg); }
.nc-data-table--compact :deep(.el-table__header th.el-table__cell),
.nc-data-table--compact :deep(.el-table__body td.el-table__cell) { height: 34px; }
</style>
