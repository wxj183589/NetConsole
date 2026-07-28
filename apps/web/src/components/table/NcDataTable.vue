<script setup lang="ts" generic="Row extends object">
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch } from 'vue'
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
  reconcileTablePreferences,
  saveTablePreferencesAsync,
  type NcTablePreferences,
} from './tablePreferences'
import { calculateTableColumnWidths, useAutoColumnWidth } from './useAutoColumnWidth'
import { clearTextMeasurementCache } from './textMeasurement'
import {
  calculateNcDataTableContextMenuPosition,
  type NcDataTableContext,
  type NcDataTableContextMenuItem,
} from './NcDataTableContextMenu'

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
  contextMenuItems?: readonly NcDataTableContextMenuItem<Row>[]
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
  contextMenuItems: () => [],
})

const emit = defineEmits<{
  'header-dragend': [newWidth: number, oldWidth: number, column: unknown, event: MouseEvent]
  'row-contextmenu': [row: Row, column: { property?: string; columnKey?: string; label?: string }, event: MouseEvent]
  'selection-change': [rows: Row[]]
}>()

const tableRef = ref()
const containerRef = ref<HTMLElement>()
const scrollRef = ref<HTMLElement>()
const contextMenuRef = ref<HTMLElement>()
const contextMenu = shallowRef<{ visible: boolean; positioned: boolean; x: number; y: number; context: NcDataTableContext<Row> | null }>({
  visible: false,
  positioned: false,
  x: 0,
  y: 0,
  context: null,
})
const availableWidth = ref(0)
const displayRevision = ref(0)
const bodyFont = ref('400 14px "Microsoft YaHei UI", sans-serif')
const headerFont = ref('600 14px "Microsoft YaHei UI", sans-serif')
const currentLanguage = ref(props.language || documentLanguage())
const preferences = ref<NcTablePreferences>()
const manualWidths = ref<Record<string, number>>({})
const columnLayoutRevision = ref(0)
const rebuildingColumnLayout = ref(false)
const mountedColumnKeys = ref<Set<string>>(new Set())
let mountedColumnsInitialized = false
const preferenceMutationRevision = ref(0)
const preferenceSaveState = ref<'saved' | 'saving' | 'error'>('saved')
let rootObserver: MutationObserver | undefined
let resizeObserver: ResizeObserver | undefined
let preferenceLoadGeneration = 0
let preferenceSaveGeneration = 0
let contextMenuGeneration = 0

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
type RenderColumn = ResolvedNcTableColumn<Row> & { sourceIndex: number }

watch(() => props.language, (language) => {
  if (language) currentLanguage.value = language
})

const normalizedColumns = computed(() => props.columns.map(normalizeNcTableColumn))

function reconcileCurrentPreference(value?: NcTablePreferences | null): NcTablePreferences {
  return reconcileTablePreferences(normalizedColumns.value, value)
}

function applyLoadedPreference(value: NcTablePreferences | undefined): NcTablePreferences {
  const next = reconcileCurrentPreference(value)
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

const resolvedColumns = computed<RenderColumn[]>(() => {
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
const renderColumns = computed(() => resolvedColumns.value.filter((column) => mountedColumnKeys.value.has(column.key)))
watch(resolvedColumns, (columns) => {
  const missing = columns.filter((column) => column.visible && !mountedColumnKeys.value.has(column.key))
  if (!mountedColumnsInitialized) {
    mountedColumnKeys.value = new Set(columns.filter((column) => column.visible).map((column) => column.key))
    mountedColumnsInitialized = true
    return
  }
  if (!missing.length) return
  const hadMountedColumns = mountedColumnKeys.value.size > 0
  mountedColumnKeys.value = new Set([...mountedColumnKeys.value, ...missing.map((column) => column.key)])
  if (hadMountedColumns && props.data.length > props.sampleLimit) {
    void refreshColumnLayout(true, true)
  } else {
    columnLayoutRevision.value += 1
    void refreshColumnLayout(true)
  }
}, { immediate: true })
const rows = computed(() => props.data)
const sizingColumns = computed(() => renderColumns.value as readonly NcTableColumn<Row>[])
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
const tableStyle = computed(() => ({ width: '100%' }))
const tableData = computed(() => rebuildingColumnLayout.value ? [] : props.data)

function columnDomClass(column: RenderColumn): string {
  return `nc-data-table__column-${column.sourceIndex}`
}

function applyColumnVisibility(): void {
  const container = containerRef.value
  if (!container) return
  const visibility = new Map(resolvedColumns.value.map((column) => [column.key, column.visible]))
  for (const column of renderColumns.value) {
    const hidden = visibility.get(column.key) === false
    const cells = container.querySelectorAll<HTMLElement>(`.${columnDomClass(column)}`)
    const internalNames = new Set<string>()
    for (const cell of cells) {
      cell.classList.toggle('nc-data-table__column--hidden', hidden)
      cell.style.display = hidden ? 'none' : ''
      for (const name of cell.classList) {
        if (/^el-table_\d+_column_\d+$/.test(name)) internalNames.add(name)
      }
    }
    for (const name of internalNames) {
      for (const col of container.querySelectorAll<HTMLElement>(`col[name="${name}"]`)) {
        col.style.display = hidden ? 'none' : ''
      }
    }
  }
}

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
  const current = reconcileCurrentPreference(preferences.value)
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

function commitPreference(value: NcTablePreferences, refresh = true, remount = false): void {
  const next = reconcileCurrentPreference(value)
  preferenceMutationRevision.value += 1
  preferences.value = next
  persistPreference(next)
  if (refresh) void refreshColumnLayout(true, remount)
}

function updatePreferenceColumns(update: (columns: NcTablePreferences['columns']) => void): void {
  const next = reconcileCurrentPreference(preferences.value)
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
  const next = reconcileCurrentPreference(preferences.value)
  commitPreference({ ...next, order }, true, true)
}

function cyclePin(key: string): void {
  const next = reconcileCurrentPreference(preferences.value)
  const target = next.columns.find((column) => column.key === key)
  if (target) {
    target.fixed = target.fixed === 'left' ? 'right' : target.fixed === 'right' ? false : 'left'
    commitPreference(next, true, true)
  }
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
  preferences.value = reconcileCurrentPreference()
  manualWidths.value = {}
  void refreshColumnLayout(true, true)
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

function closeContextMenu(): void {
  contextMenuGeneration += 1
  contextMenu.value = { visible: false, positioned: false, x: 0, y: 0, context: null }
}

async function handleRowContextMenu(row: Row, column: { property?: string; columnKey?: string }, event: MouseEvent): Promise<void> {
  emit('row-contextmenu', row, column, event)
  if (!props.contextMenuItems.length) return
  event.preventDefault()
  event.stopPropagation()
  const columnKey = String(column?.columnKey || column?.property || '')
  const rowIndex = props.data.indexOf(row)
  const generation = ++contextMenuGeneration
  contextMenu.value = {
    visible: true,
    positioned: false,
    x: event.clientX,
    y: event.clientY,
    context: {
      row,
      rowIndex,
      columnKey,
      cellValue: column?.property ? (row as Record<string, unknown>)[column.property] : undefined,
    },
  }
  await nextTick()
  if (generation !== contextMenuGeneration) return
  const menu = contextMenuRef.value
  if (!menu) return
  const rect = menu.getBoundingClientRect()
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth || 0
  const viewportHeight = document.documentElement.clientHeight || window.innerHeight || 0
  const position = calculateNcDataTableContextMenuPosition({
    anchorX: event.clientX,
    anchorY: event.clientY,
    menuWidth: rect.width,
    menuHeight: rect.height,
    viewportWidth,
    viewportHeight,
  })
  contextMenu.value = {
    ...contextMenu.value,
    positioned: true,
    x: position.left,
    y: position.top,
  }
}

function contextItemDisabled(item: NcDataTableContextMenuItem<Row>): boolean {
  const context = contextMenu.value.context
  if (!context) return true
  return typeof item.disabled === 'function' ? item.disabled(context) : Boolean(item.disabled)
}

function contextItemReason(item: NcDataTableContextMenuItem<Row>): string {
  const context = contextMenu.value.context
  if (!context || !contextItemDisabled(item)) return ''
  return typeof item.disabledReason === 'function' ? item.disabledReason(context) : String(item.disabledReason || '')
}

function runContextItem(item: NcDataTableContextMenuItem<Row>): void {
  const context = contextMenu.value.context
  if (!context || contextItemDisabled(item)) return
  closeContextMenu()
  void item.action(context)
}

function handleDocumentPointerDown(event: Event): void {
  if (!contextMenu.value.visible || contextMenuRef.value?.contains(event.target as Node)) return
  closeContextMenu()
}

function handleDocumentKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeContextMenu()
}

function handleWindowScroll(event: Event): void {
  const target = event.target
  if (target instanceof Node && contextMenuRef.value?.contains(target)) return
  closeContextMenu()
}

async function refreshColumnLayout(force = false, remount = false): Promise<void> {
  if (remount) {
    rebuildingColumnLayout.value = true
    columnLayoutRevision.value += 1
    await nextTick()
    // 先完成输入事件和空表骨架，再恢复可能包含 1000 行的数据。
    await new Promise<void>((resolvePromise) => window.setTimeout(resolvePromise, 100))
    rebuildingColumnLayout.value = false
  }
  await nextTick()
  applyColumnVisibility()
  if (remount) tableRef.value?.doLayout?.()
  await nextTick()
  applyColumnVisibility()
  tableRef.value?.scrollBarRef?.update?.()
  if (remount) recalculate(force)
}

function clearSelection(): void {
  tableRef.value?.clearSelection?.()
}

function toggleRowSelection(row: Row, selected?: boolean): void {
  tableRef.value?.toggleRowSelection?.(row, selected)
}

function handleSelectionChange(rows: Row[]): void {
  emit('selection-change', rows)
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

function handleWindowResize(): void {
  closeContextMenu()
  handleViewportChange()
}

onMounted(() => {
  const rootElement = typeof document === 'undefined' ? undefined : document.documentElement
  if (!rootElement) return
  refreshFonts()
  updateAvailableWidth()
  recalculate()
  void nextTick(applyColumnVisibility)
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
  window.addEventListener?.('resize', handleWindowResize)
  window.addEventListener?.('scroll', handleWindowScroll, true)
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  document.addEventListener('keydown', handleDocumentKeyDown)
})

watch(() => props.data, closeContextMenu)
onDeactivated(closeContextMenu)

onBeforeUnmount(() => {
  rootObserver?.disconnect()
  resizeObserver?.disconnect()
  window.removeEventListener?.('resize', handleWindowResize)
  window.removeEventListener?.('scroll', handleWindowScroll, true)
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  document.removeEventListener('keydown', handleDocumentKeyDown)
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
        v-memo="[tableData, columnLayoutRevision, widths, height, maxHeight, rowKey, stripe, border]"
        v-bind="$attrs"
        :data="tableData"
        :height="height"
        :max-height="maxHeight"
        :empty-text="resolvedEmptyText"
        :row-key="rowKey"
        :stripe="stripe"
        :border="border"
        :fit="true"
        :style="tableStyle"
        flexible
        scrollbar-always-on
        @header-dragend="handleHeaderDragEnd"
        @row-contextmenu="handleRowContextMenu"
        @selection-change="handleSelectionChange"
      >
        <template
          v-for="(column, columnIndex) in renderColumns"
          :key="column.key"
          v-memo="[column.key, columnIndex, widths[column.key], column.fixed, column.label, column.prop, column.type]"
        >
          <el-table-column
            v-if="column.type"
            v-bind="safeNcTableColumnAttrs(column.columnAttrs)"
            :type="column.type"
            :column-key="column.key"
            :label="column.label"
            :width="widths[column.key]"
            :class-name="columnDomClass(column)"
            :label-class-name="columnDomClass(column)"
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
            :class-name="columnDomClass(column)"
            :label-class-name="columnDomClass(column)"
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
    <Teleport to="body">
      <div
        v-if="contextMenu.visible && contextMenu.context"
        ref="contextMenuRef"
        class="nc-data-table__context-menu"
        :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px`, visibility: contextMenu.positioned ? 'visible' : 'hidden' }"
        role="menu"
        @click.stop
        @contextmenu.prevent.stop
      >
        <template v-for="item in contextMenuItems" :key="item.key">
          <span v-if="item.separatorBefore" class="nc-data-table__context-separator" />
          <button
            type="button"
            :class="{ danger: item.danger }"
            :disabled="contextItemDisabled(item)"
            :title="contextItemReason(item)"
            role="menuitem"
            @click="runContextItem(item)"
          >
            <span>{{ item.label }}</span>
            <small v-if="contextItemReason(item)">{{ contextItemReason(item) }}</small>
          </button>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.nc-data-table { display: flex; flex-direction: column; min-width: 0; min-height: 0; width: 100%; height: 100%; overflow: hidden; }
.nc-data-table__tools { display: flex; flex: none; align-items: center; justify-content: flex-end; gap: 8px; min-height: 34px; padding: 0 0 8px; }
.nc-data-table__scroll { flex: 1; min-width: 0; min-height: 0; width: 100%; overflow: hidden; }
.nc-data-table :deep(.el-table) { width: 100%; color: var(--nc-text-primary); font-size: var(--nc-font-size-base); }
.nc-data-table :deep(.el-table__header th.el-table__cell) { height: var(--nc-table-row-height); padding: 0; background: var(--nc-table-header-bg); color: var(--nc-text-secondary); font-weight: 600; text-align: center; }
.nc-data-table :deep(.el-table__body td.el-table__cell) { height: var(--nc-table-row-height); padding: 0; vertical-align: middle; }
.nc-data-table :deep(.el-table__body tr:hover > td.el-table__cell) { background: var(--nc-table-hover-bg); }
.nc-data-table :deep(.el-table__body tr.current-row > td.el-table__cell) { background: var(--nc-table-selected-bg); }
.nc-data-table :deep(.nc-data-table__column--hidden) { display: none !important; }
.nc-data-table--compact :deep(.el-table__header th.el-table__cell),
.nc-data-table--compact :deep(.el-table__body td.el-table__cell) { height: 34px; }
.nc-data-table__context-menu { position: fixed; z-index: 4000; display: flex; flex-direction: column; min-width: min(190px, calc(100vw - 16px)); max-width: min(320px, calc(100vw - 16px)); max-height: calc(100vh - 16px); padding: 6px; overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; background: var(--nc-bg-panel); border: 1px solid var(--nc-border); border-radius: 8px; box-shadow: var(--el-box-shadow-light); }
.nc-data-table__context-menu button { display: flex; width: 100%; min-width: 0; flex: none; flex-direction: column; gap: 2px; padding: 7px 10px; overflow: hidden; background: transparent; border: 0; border-radius: 5px; color: var(--nc-text-primary); text-align: left; cursor: pointer; }
.nc-data-table__context-menu button > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nc-data-table__context-menu button:hover:not(:disabled) { background: var(--nc-table-hover-bg); }
.nc-data-table__context-menu button:disabled { color: var(--nc-text-secondary); cursor: not-allowed; opacity: .72; }
.nc-data-table__context-menu button.danger:not(:disabled) { color: var(--nc-danger); }
.nc-data-table__context-menu small { max-width: 280px; color: var(--nc-text-secondary); font-size: 11px; white-space: normal; }
.nc-data-table__context-separator { height: 1px; margin: 5px 2px; background: var(--nc-divider); }
</style>
